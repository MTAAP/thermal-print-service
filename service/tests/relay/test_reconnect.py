import asyncio

import httpx
import pytest
from httpx import ASGITransport

from printer.relay import loop as loop_mod
from printer.relay.config import RelayConfig
from printer.relay.hub_client import HubClient
from printer.relay.local_client import LocalClient
from printer.relay.loop import RelayClient
from printer.relay.store import CredsStore


def _cfg(relay_paths):
    return RelayConfig.from_env({
        "HUB_URL": "http://hub.test",
        "PRINTER_RELAY_STATE_DIR": str(relay_paths.root),
        "PRINTER_RELAY_BACKOFF_BASE_S": "0.01",
        "PRINTER_RELAY_BACKOFF_MAX_S": "0.05",
    })


def _patch_asgi_clients(monkeypatch, hub_app, local_url):
    """Route run_forever's internally-built httpx.AsyncClient(base_url=...) onto
    ASGI apps so the REAL httpx request path (and its error/raise_for_status) is
    exercised end-to-end. The hub base_url gets the MockHub app; the local service
    URL gets a trivial app serving only /schema (the only local endpoint these
    tests' _poll_once cycles touch)."""
    real_cls = httpx.AsyncClient
    local_app = _local_stub_app()

    def factory(*args, **kwargs):
        base_url = kwargs.get("base_url", "")
        app = local_app if base_url == local_url else hub_app
        kwargs["transport"] = ASGITransport(app=app)
        return real_cls(*args, **kwargs)

    monkeypatch.setattr(loop_mod.httpx, "AsyncClient", factory)


def _local_stub_app():
    from fastapi import FastAPI

    api = FastAPI()

    @api.get("/schema")
    async def schema() -> dict:
        # report_capabilities_if_changed needs this; the value is irrelevant to
        # the reconnect/creds-rotation behavior under test.
        return {"renderer_version": "1.0.0", "blocks": {}, "block_types": ["paragraph"]}

    return api


async def test_capability_reported_once_per_version(relay_paths, mock_hub, hub_http, fake_deps):
    from tests.conftest import lifespan_client

    async with lifespan_client(fake_deps) as local_ac:
        client = RelayClient(
            _cfg(relay_paths), relay_paths,
            hub=HubClient(hub_http, device_token="dev-token", api_token="api-token"),
            local=LocalClient(local_ac),
        )
        await client.report_capabilities_if_changed()
        await client.report_capabilities_if_changed()  # same version -> no re-report
    assert len(mock_hub.capabilities) == 1
    # The reported schema is the local /schema's full blocks + renderer_version.
    assert "renderer_version" in mock_hub.capabilities[0]
    assert "blocks_schema" in mock_hub.capabilities[0]


async def test_poll_once_recovers_after_503(relay_paths, mock_hub, hub_http, fake_deps):
    from tests.conftest import lifespan_client

    mock_hub.fail_inbox_times = 2  # first two /inbox calls 503, then recover
    async with lifespan_client(fake_deps) as local_ac:
        client = RelayClient(
            _cfg(relay_paths), relay_paths,
            hub=HubClient(hub_http, device_token="dev-token", api_token="api-token"),
            local=LocalClient(local_ac),
        )

        # Drive the reconnect logic directly: two failures then an empty success.
        backoff = client._cfg.reconnect_backoff_base_s
        successes = 0
        for _ in range(5):
            try:
                await client._poll_once()
                successes += 1
                if successes >= 1:
                    break
            except Exception:
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, client._cfg.reconnect_backoff_max_s)
    assert mock_hub.fail_inbox_times == 0  # both failures consumed
    assert successes == 1


async def test_run_forever_backs_off_on_httpx_error_then_recovers(
    relay_paths, mock_hub, monkeypatch,
):
    # Drive the REAL run_forever (not a re-implementation in the test body): the
    # hub's first inbox call 503s -> httpx.HTTPStatusError, which run_forever must
    # catch and back off; the second cycle succeeds-empty. A CancelledError on the
    # third cycle breaks the otherwise-infinite loop. Proves the real
    # `except httpx.HTTPError` path AND that polling resumes after a backoff.
    cfg = _cfg(relay_paths)
    CredsStore(relay_paths.creds_path).save({
        "printer_id": "p", "handle": "me", "hub_url": "http://hub.test",
        "device_token": "dev-token", "api_token": "api-token",
    })
    _patch_asgi_clients(monkeypatch, mock_hub.app(), cfg.local_service_url)
    mock_hub.fail_inbox_times = 1  # first /inbox 503s, then recovers

    sleeps = {"n": 0}

    async def counting_sleep(*_a, **_k):
        sleeps["n"] += 1

    monkeypatch.setattr(asyncio, "sleep", counting_sleep)

    # Break the loop on the cycle after recovery by raising CancelledError once the
    # hub has served at least one successful (non-503) inbox poll.
    real_poll = RelayClient._poll_once
    cycles = {"n": 0}

    async def wrapped_poll(self):
        cycles["n"] += 1
        if cycles["n"] >= 3:
            raise asyncio.CancelledError()
        await real_poll(self)

    monkeypatch.setattr(RelayClient, "_poll_once", wrapped_poll)

    client = RelayClient(cfg, relay_paths)
    with pytest.raises(asyncio.CancelledError):
        await client.run_forever()

    assert sleeps["n"] >= 1  # at least one backoff sleep on the 503
    assert cycles["n"] >= 2  # the loop came back for a second (recovered) cycle
    # The hub served the recovered (non-503) inbox poll after the failure.
    assert mock_hub.fail_inbox_times == 0


async def test_run_forever_rebuilds_clients_on_creds_change(
    relay_paths, mock_hub, monkeypatch,
):
    # Mid-loop the creds.json is rewritten with a NEW device_token. run_forever
    # must notice (current_creds != creds), tear down the hub client, and rebuild
    # it so the next hub call carries the new Bearer token.
    cfg = _cfg(relay_paths)
    CredsStore(relay_paths.creds_path).save({
        "printer_id": "p", "handle": "me", "hub_url": "http://hub.test",
        "device_token": "tok-old", "api_token": "api-token",
    })
    _patch_asgi_clients(monkeypatch, mock_hub.app(), cfg.local_service_url)

    async def no_sleep(*_a, **_k):
        return None

    monkeypatch.setattr(asyncio, "sleep", no_sleep)

    real_poll = RelayClient._poll_once
    cycles = {"n": 0}

    async def wrapped_poll(self):
        cycles["n"] += 1
        if cycles["n"] == 1:
            # Run a real first cycle (old token reaches the hub), then rotate creds.
            await real_poll(self)
            CredsStore(relay_paths.creds_path).save({
                "printer_id": "p", "handle": "me", "hub_url": "http://hub.test",
                "device_token": "tok-new", "api_token": "api-token",
            })
            return
        if cycles["n"] == 2:
            # After the reconnect, run one real cycle with the rebuilt client so
            # the new token rides a hub call, then break the loop.
            await real_poll(self)
            raise asyncio.CancelledError()
        raise asyncio.CancelledError()

    monkeypatch.setattr(RelayClient, "_poll_once", wrapped_poll)

    client = RelayClient(cfg, relay_paths)
    with pytest.raises(asyncio.CancelledError):
        await client.run_forever()

    # The hub saw the old token first, then the rotated one after the reconnect.
    assert "Bearer tok-old" in mock_hub.auth_seen
    assert "Bearer tok-new" in mock_hub.auth_seen
    # The new token appears only AFTER the old one (clients were rebuilt, not stale).
    assert mock_hub.auth_seen.index("Bearer tok-new") > mock_hub.auth_seen.index(
        "Bearer tok-old"
    )
