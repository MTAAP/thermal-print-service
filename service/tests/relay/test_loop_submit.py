import io

from PIL import Image
from printer_core.constants import PRINT_HEAD_WIDTH_PX

from printer.relay.config import RelayConfig
from printer.relay.hub_client import HubClient
from printer.relay.local_client import LocalClient, SubmitOutcome, SubmitResult
from printer.relay.loop import RelayClient
from printer.relay.store import AllowList, JobMap


def _cfg(relay_paths):
    return RelayConfig.from_env({
        "HUB_URL": "http://hub.test",
        "PRINTER_RELAY_STATE_DIR": str(relay_paths.root),
    })


def _client(cfg, relay_paths, hub_http, local_ac):
    return RelayClient(
        cfg, relay_paths,
        hub=HubClient(hub_http, device_token="dev-token", api_token="api-token"),
        local=LocalClient(local_ac),
    )


async def test_accepted_persists_jobmap_before_ack_then_reports_printed(
    relay_paths, mock_hub, hub_http, fake_deps,
):
    from tests.conftest import lifespan_client

    cfg = _cfg(relay_paths)
    AllowList(relay_paths.allowlist_path).add("alice", display_name="Alice",
                                              renderer_version=None)
    async with lifespan_client(fake_deps) as local_ac:
        client = _client(cfg, relay_paths, hub_http, local_ac)
        job = {
            "job_id": "hj1", "sender": "alice", "kind": "document",
            "sent_at": "2026-06-03T14:32:00+00:00",
            "payload": {"document": {"blocks": [{"type": "paragraph", "text": "hi"}]}},
        }
        await client.process_job(job)
        # The watch runs as a background task now; drain it before asserting on
        # the posted status (and before lifespan_client closes the local client).
        await client.join_watchers()
        # Drained by the worker (lifespan started it). The relay watched the
        # local job to terminal and posted the mapped status.
    # JobMap entry exists and is terminal. Local job ids are uuid4().hex
    # (32 hex chars, NO prefix) per app._new_job_id.
    jm = JobMap(relay_paths.jobmap_path)
    entry = jm.get("hj1")
    assert entry is not None
    assert len(entry["local_job_id"]) == 32 and all(
        c in "0123456789abcdef" for c in entry["local_job_id"]
    )
    assert mock_hub.acked == ["hj1"]  # acked AFTER the map was persisted
    assert ("hj1", "printed") in mock_hub.statuses


async def test_raw_png_band_submitted_and_printed(relay_paths, mock_hub, hub_http, fake_deps):
    from tests.conftest import lifespan_client

    cfg = _cfg(relay_paths)
    AllowList(relay_paths.allowlist_path).add("alice", display_name="Alice",
                                              renderer_version=None)
    buf = io.BytesIO()
    Image.new("L", (PRINT_HEAD_WIDTH_PX, 200), color=255).save(buf, format="PNG")
    import base64
    raw_b64 = base64.b64encode(buf.getvalue()).decode()
    async with lifespan_client(fake_deps) as local_ac:
        client = _client(cfg, relay_paths, hub_http, local_ac)
        job = {
            "job_id": "hjraw", "sender": "alice", "kind": "raw",
            "sent_at": "2026-06-03T14:32:00+00:00",
            "payload": {"raw_png_b64": raw_b64},
        }
        await client.process_job(job)
        await client.join_watchers()  # drain background watch before asserting
    assert mock_hub.acked == ["hjraw"]
    assert ("hjraw", "printed") in mock_hub.statuses


class _CountingLocal:
    """Counts how many times a job was actually submitted to the local printer."""

    def __init__(self) -> None:
        self.submits = 0

    async def print_document(self, document, *, sender, idempotency_key):
        self.submits += 1
        return SubmitResult(SubmitOutcome.ACCEPTED, local_job_id="loc1")

    async def print_raw(self, png_bytes, *, sender, idempotency_key):
        self.submits += 1
        return SubmitResult(SubmitOutcome.ACCEPTED, local_job_id="loc1")

    async def get_job_status(self, local_job_id):
        return "printed"


async def test_redelivered_hub_job_is_not_reprinted(relay_paths, mock_hub, hub_http):
    """A hub redelivery of an already-delivered job (its JobMap entry survives the
    local idempotency TTL) must re-ack and re-report -- never reprint (finding 2)."""
    cfg = _cfg(relay_paths)
    AllowList(relay_paths.allowlist_path).add("alice", display_name="Alice",
                                              renderer_version=None)
    local = _CountingLocal()
    client = RelayClient(
        cfg, relay_paths,
        hub=HubClient(hub_http, device_token="dev-token", api_token="api-token"),
        local=local,
    )
    job = {
        "job_id": "hj1", "sender": "alice", "kind": "document",
        "sent_at": "2026-06-03T14:32:00+00:00",
        "payload": {"document": {"blocks": [{"type": "paragraph", "text": "hi"}]}},
    }
    await client.process_job(job)
    await client.join_watchers()  # background watch reports printed + marks the map
    # Same job redelivered by the hub.
    await client.process_job(job)
    await client.join_watchers()
    # Printed exactly once; the redelivery took the durable-dedup path.
    assert local.submits == 1
    # Re-acked (idempotent) so the hub stops redelivering, and re-reported printed.
    assert mock_hub.acked == ["hj1", "hj1"]
    assert ("hj1", "printed") in mock_hub.statuses


async def test_preseeded_jobmap_redelivery_is_not_locally_submitted(
    relay_paths, mock_hub, hub_http
):
    """A relay restart can see a redelivered hub job only through the durable
    JobMap. That preexisting map entry must suppress local submission entirely."""
    cfg = _cfg(relay_paths)
    AllowList(relay_paths.allowlist_path).add("alice", display_name="Alice",
                                              renderer_version=None)
    JobMap(relay_paths.jobmap_path).put(
        "hj-preseed", local_job_id="loc-preseed", last_status="delivered"
    )
    local = _CountingLocal()
    client = RelayClient(
        cfg, relay_paths,
        hub=HubClient(hub_http, device_token="dev-token", api_token="api-token"),
        local=local,
    )
    await client.process_job({
        "job_id": "hj-preseed", "sender": "alice", "kind": "document",
        "sent_at": "2026-06-03T14:32:00+00:00",
        "payload": {"document": {"blocks": [{"type": "paragraph", "text": "hi"}]}},
    })

    assert local.submits == 0
    assert mock_hub.acked == ["hj-preseed"]
    assert ("hj-preseed", "printed") in mock_hub.statuses
