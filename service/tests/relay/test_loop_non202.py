from printer.relay.config import RelayConfig
from printer.relay.hub_client import HubClient
from printer.relay.local_client import SubmitOutcome, SubmitResult
from printer.relay.loop import RelayClient
from printer.relay.store import AllowList, JobMap


def _cfg(relay_paths):
    return RelayConfig.from_env({
        "HUB_URL": "http://hub.test",
        "PRINTER_RELAY_STATE_DIR": str(relay_paths.root),
    })


class _StubLocal:
    """Returns a fixed SubmitOutcome; records whether get_job_status was called."""

    def __init__(self, outcome: SubmitOutcome) -> None:
        self._outcome = outcome
        self.status_polled = False

    async def print_document(self, document, *, sender, idempotency_key):
        return SubmitResult(self._outcome, local_job_id=None)

    async def print_raw(self, png_bytes, *, sender, idempotency_key):
        return SubmitResult(self._outcome, local_job_id=None)

    async def get_job_status(self, local_job_id):
        self.status_polled = True
        return "printed"


def _job(jid="hj1"):
    return {
        "job_id": jid, "sender": "alice", "kind": "document",
        "sent_at": "2026-06-03T14:32:00+00:00",
        "payload": {"document": {"blocks": [{"type": "paragraph", "text": "hi"}]}},
    }


async def _run(relay_paths, mock_hub, hub_http, outcome):
    AllowList(relay_paths.allowlist_path).add("alice", display_name="Alice",
                                              renderer_version=None)
    client = RelayClient(
        _cfg(relay_paths), relay_paths,
        hub=HubClient(hub_http, device_token="dev-token", api_token="api-token"),
        local=_StubLocal(outcome),
    )
    await client.process_job(_job())
    return client


async def test_400_maps_rejected_incompatible_no_retry(relay_paths, mock_hub, hub_http):
    await _run(relay_paths, mock_hub, hub_http, SubmitOutcome.INCOMPATIBLE)
    assert ("hj1", "rejected_incompatible") in mock_hub.statuses
    assert mock_hub.acked == []


async def test_413_maps_failed(relay_paths, mock_hub, hub_http):
    await _run(relay_paths, mock_hub, hub_http, SubmitOutcome.TOO_LARGE)
    assert ("hj1", "failed") in mock_hub.statuses
    assert mock_hub.acked == []


async def test_503_is_retryable_no_ack_no_status(relay_paths, mock_hub, hub_http):
    await _run(relay_paths, mock_hub, hub_http, SubmitOutcome.QUEUE_FULL)
    # Neither acked nor terminal-reported: the hub lease expires -> redelivery.
    assert mock_hub.acked == []
    assert mock_hub.statuses == []
    # And nothing was persisted to the job map.
    assert JobMap(relay_paths.jobmap_path).get("hj1") is None


async def test_409_canary_failed_no_loop(relay_paths, mock_hub, hub_http):
    await _run(relay_paths, mock_hub, hub_http, SubmitOutcome.IDEMPOTENCY_MISMATCH)
    assert ("hj1", "failed") in mock_hub.statuses
    assert mock_hub.acked == []
