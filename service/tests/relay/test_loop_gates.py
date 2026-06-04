import asyncio

import pytest

from printer.relay.config import RelayConfig
from printer.relay.loop import RelayClient
from printer.relay.store import AllowList, CredsStore


def _cfg(relay_paths):
    return RelayConfig.from_env({
        "HUB_URL": "http://hub.test",
        "PRINTER_RELAY_STATE_DIR": str(relay_paths.root),
        "PRINTER_RELAY_RATE_PER_HOUR": "2",
    })


async def test_non_allowlisted_sender_rejected(relay_paths, mock_hub, hub_http, fake_deps):
    from printer.relay.hub_client import HubClient
    from printer.relay.local_client import LocalClient
    from tests.conftest import lifespan_client

    cfg = _cfg(relay_paths)
    async with lifespan_client(fake_deps) as local_ac:
        client = RelayClient(
            cfg, relay_paths,
            hub=HubClient(hub_http, device_token="dev-token", api_token="api-token"),
            local=LocalClient(local_ac),
        )
        job = {
            "job_id": "hj1", "sender": "stranger", "kind": "document",
            "sent_at": "2026-06-03T14:32:00+00:00",
            "payload": {"document": {"blocks": [{"type": "paragraph", "text": "hi"}]}},
        }
        await client.process_job(job)
    assert ("hj1", "rejected_not_allowlisted") in mock_hub.statuses
    assert mock_hub.acked == []  # never acked a rejected job


async def test_rate_limited_sender_rejected(relay_paths, mock_hub, hub_http, fake_deps):
    from printer.relay.hub_client import HubClient
    from printer.relay.local_client import LocalClient
    from tests.conftest import lifespan_client

    cfg = _cfg(relay_paths)  # rate = 2/hour
    AllowList(relay_paths.allowlist_path).add("alice", display_name="Alice",
                                              renderer_version=None)
    async with lifespan_client(fake_deps) as local_ac:
        client = RelayClient(
            cfg, relay_paths,
            hub=HubClient(hub_http, device_token="dev-token", api_token="api-token"),
            local=LocalClient(local_ac),
        )

        def job(jid, minute):
            return {
                "job_id": jid, "sender": "alice", "kind": "document",
                "sent_at": f"2026-06-03T14:{minute}:00+00:00",
                "payload": {"document": {"blocks": [{"type": "paragraph", "text": "hi"}]}},
            }

        await client.process_job(job("hj1", "00"))
        await client.process_job(job("hj2", "10"))
        await client.process_job(job("hj3", "20"))  # 3rd in the hour -> limited
    assert ("hj3", "rejected_rate_limited") in mock_hub.statuses


async def test_malformed_job_is_marked_failed_not_crashed(
    relay_paths, mock_hub, hub_http, fake_deps
):
    """A malformed inbox job must become terminal ('failed') or be dropped, never
    raise out of process_job -- an escape would kill run_forever and stop the
    per-cycle replay every other path relies on (adversarial-review finding #4)."""
    from printer.relay.hub_client import HubClient
    from printer.relay.local_client import LocalClient
    from tests.conftest import lifespan_client

    cfg = _cfg(relay_paths)
    AllowList(relay_paths.allowlist_path).add("alice", display_name="Alice",
                                              renderer_version=None)
    async with lifespan_client(fake_deps) as local_ac:
        client = RelayClient(
            cfg, relay_paths,
            hub=HubClient(hub_http, device_token="dev-token", api_token="api-token"),
            local=LocalClient(local_ac),
        )
        # payload missing the "document" key -> KeyError in _submit -> failed
        await client.process_job({
            "job_id": "hj-bad1", "sender": "alice", "kind": "document",
            "sent_at": "2026-06-03T14:00:00+00:00", "payload": {},
        })
        # missing sender -> failed (bad-shape branch), before the gates
        await client.process_job({
            "job_id": "hj-bad2", "kind": "document",
            "sent_at": "2026-06-03T14:05:00+00:00", "payload": {},
        })
        # missing job_id -> unreportable -> dropped silently, must not raise
        await client.process_job({"sender": "alice", "kind": "document"})
    assert ("hj-bad1", "failed") in mock_hub.statuses
    assert ("hj-bad2", "failed") in mock_hub.statuses
    assert mock_hub.acked == []  # poison jobs are never acked


async def test_undecodable_raw_payload_marked_failed_not_looped(
    relay_paths, mock_hub, hub_http, fake_deps
):
    """A raw job whose base64 decodes but is not a valid image must become
    terminal 'failed', never escape as an OSError into the backoff loop and
    redeliver forever (finding 8)."""
    import base64

    from printer.relay.hub_client import HubClient
    from printer.relay.local_client import LocalClient
    from tests.conftest import lifespan_client

    cfg = _cfg(relay_paths)
    AllowList(relay_paths.allowlist_path).add("alice", display_name="Alice",
                                              renderer_version=None)
    async with lifespan_client(fake_deps) as local_ac:
        client = RelayClient(
            cfg, relay_paths,
            hub=HubClient(hub_http, device_token="dev-token", api_token="api-token"),
            local=LocalClient(local_ac),
        )
        bad = base64.b64encode(b"definitely not a png").decode()
        await client.process_job({
            "job_id": "hj-rawbad", "sender": "alice", "kind": "raw",
            "sent_at": "2026-06-03T14:00:00+00:00",
            "payload": {"raw_png_b64": bad},
        })
    assert ("hj-rawbad", "failed") in mock_hub.statuses
    assert mock_hub.acked == []


async def test_malformed_payload_shapes_marked_failed_not_looped(
    relay_paths, mock_hub, hub_http, fake_deps
):
    """Payloads with a wrong SHAPE -- a non-str raw_png_b64, a None document, a
    None payload -- raise TypeError/AttributeError inside _submit. Those are
    deterministic client errors and must become terminal 'failed', never escape
    process_job into the backoff loop and redeliver forever (findings 4 + 8)."""
    from printer.relay.hub_client import HubClient
    from printer.relay.local_client import LocalClient
    from tests.conftest import lifespan_client

    cfg = _cfg(relay_paths)
    AllowList(relay_paths.allowlist_path).add("alice", display_name="Alice",
                                              renderer_version=None)
    async with lifespan_client(fake_deps) as local_ac:
        client = RelayClient(
            cfg, relay_paths,
            hub=HubClient(hub_http, device_token="dev-token", api_token="api-token"),
            local=LocalClient(local_ac),
        )
        # sent_at spaced >1h apart so the per-friend rate gate (2/hour here) never
        # pre-empts _submit -- we are testing the malformed-payload path, not gate 2.
        # non-str raw_png_b64 -> TypeError in base64.b64decode
        await client.process_job({
            "job_id": "hj-typ1", "sender": "alice", "kind": "raw",
            "sent_at": "2026-06-03T12:00:00+00:00", "payload": {"raw_png_b64": 12345},
        })
        # None document -> AttributeError in from_header_block
        await client.process_job({
            "job_id": "hj-typ2", "sender": "alice", "kind": "document",
            "sent_at": "2026-06-03T14:00:00+00:00", "payload": {"document": None},
        })
        # None payload -> TypeError on subscripting payload["document"]
        await client.process_job({
            "job_id": "hj-typ3", "sender": "alice", "kind": "document",
            "sent_at": "2026-06-03T16:00:00+00:00", "payload": None,
        })
    assert ("hj-typ1", "failed") in mock_hub.statuses
    assert ("hj-typ2", "failed") in mock_hub.statuses
    assert ("hj-typ3", "failed") in mock_hub.statuses
    assert mock_hub.acked == []


async def test_run_forever_survives_non_httpx_error(relay_paths, monkeypatch):
    """A non-httpx error from a poll cycle (e.g. OSError from a fsync, or a
    JSONDecodeError from a corrupted 200) must be caught and backed off, not kill
    run_forever -- replay only runs while the loop lives (review finding #4)."""
    CredsStore(relay_paths.creds_path).save({
        "printer_id": "p", "handle": "me", "hub_url": "http://hub.test",
        "device_token": "d", "api_token": "a",
    })
    cfg = _cfg(relay_paths)
    client = RelayClient(cfg, relay_paths)

    async def _no_sleep(*_a, **_k):
        return None

    monkeypatch.setattr(asyncio, "sleep", _no_sleep)

    calls = {"n": 0}

    async def fake_poll():
        calls["n"] += 1
        if calls["n"] == 1:
            raise ValueError("boom: a non-httpx error")  # must be caught by the guard
        raise asyncio.CancelledError()  # break the loop (BaseException -> propagates)

    client._poll_once = fake_poll  # type: ignore[method-assign]

    with pytest.raises(asyncio.CancelledError):
        await client.run_forever()
    # n==2 proves the first (non-httpx) error did NOT propagate: the loop caught it
    # and came back for a second cycle.
    assert calls["n"] == 2
