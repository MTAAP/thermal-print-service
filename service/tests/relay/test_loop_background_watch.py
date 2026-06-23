"""Fix C regression: the terminal watch must run in the BACKGROUND so a slow
job cannot block the long-poll loop, and a job that reaches terminal AFTER the
watch deadline must still be reported via the periodic replay path (not stranded
at 'delivered' until a restart)."""
import asyncio

from printer.relay.config import RelayConfig
from printer.relay.hub_client import HubClient
from printer.relay.local_client import SubmitOutcome, SubmitResult
from printer.relay.loop import RelayClient
from printer.relay.store import AllowList, JobMap


def _cfg(relay_paths, **extra):
    env = {
        "HUB_URL": "http://hub.test",
        "PRINTER_RELAY_STATE_DIR": str(relay_paths.root),
    }
    env.update(extra)
    return RelayConfig.from_env(env)


class _ControllableLocal:
    """Accepts every submit; get_job_status returns whatever ``status`` is set to.
    Lets a test hold a watch non-terminal (slow job) or flip it to terminal."""

    def __init__(self) -> None:
        self.status: str | None = "queued"  # non-terminal until the test flips it
        self._next_id = 0

    async def print_document(self, document, *, sender, idempotency_key):
        self._next_id += 1
        return SubmitResult(SubmitOutcome.ACCEPTED, local_job_id=f"local{self._next_id}")

    async def print_raw(self, png_bytes, *, sender, idempotency_key):
        return await self.print_document(None, sender=sender, idempotency_key=idempotency_key)

    async def get_job_status(self, local_job_id):
        return self.status

    async def get_schema(self):
        # Lets _poll_once's report_capabilities_if_changed step run against the
        # stub so the full per-cycle maintenance path (incl. periodic replay)
        # is exercised, not just replay_unfinished() in isolation.
        return {"renderer_version": "1.0.0", "blocks": {}, "block_types": ["paragraph"]}


def _job(jid):
    return {
        "job_id": jid, "sender": "alice", "kind": "document",
        "sent_at": "2026-06-03T14:32:00+00:00",
        "payload": {"document": {"blocks": [{"type": "paragraph", "text": "hi"}]}},
    }


async def test_slow_watch_runs_in_background_and_does_not_block(
    relay_paths, mock_hub, hub_http,
):
    # A slow job (status never reaches terminal) must not block processing a
    # second job. With an inline watch this would hang for local_terminal_timeout_s.
    AllowList(relay_paths.allowlist_path).add("alice", display_name="Alice",
                                              renderer_version=None)
    local = _ControllableLocal()
    client = RelayClient(
        _cfg(relay_paths), relay_paths,
        hub=HubClient(hub_http, device_token="dev-token", api_token="api-token"),
        local=local,
    )

    # First (slow) job: returns quickly even though the watch is still spinning.
    await asyncio.wait_for(client.process_job(_job("hj1")), timeout=2.0)
    assert mock_hub.acked == ["hj1"]
    assert len(client._watch_tasks) == 1  # watch is tracked, not awaited inline
    watch = next(iter(client._watch_tasks))
    assert not watch.done()  # still watching the slow job

    # Second job proceeds without waiting for the first watch to finish.
    await asyncio.wait_for(client.process_job(_job("hj2")), timeout=2.0)
    assert mock_hub.acked == ["hj1", "hj2"]

    # Cleanup: cancel the still-running watches (run_forever's finally does this).
    for t in list(client._watch_tasks):
        t.cancel()
    await client.join_watchers()


async def test_post_deadline_terminal_reported_via_periodic_replay(
    relay_paths, mock_hub, hub_http,
):
    # The in-loop watch deadline passes while the job is still non-terminal, so
    # the map stays at 'delivered'. When the job later reaches terminal, the
    # periodic replay (not just startup) must report it -- otherwise the web
    # history shows 'delivered' forever while the relay stays up.
    AllowList(relay_paths.allowlist_path).add("alice", display_name="Alice",
                                              renderer_version=None)
    local = _ControllableLocal()
    client = RelayClient(
        _cfg(relay_paths,
             PRINTER_RELAY_LOCAL_TERMINAL_TIMEOUT_S="0.0",
             PRINTER_RELAY_LONG_POLL_WAIT_S="0.1"),
        relay_paths,
        hub=HubClient(hub_http, device_token="dev-token", api_token="api-token"),
        local=local,
    )

    # local_terminal_timeout_s == 0 -> the watch deadline is already past, so the
    # background watch returns immediately leaving the map at 'delivered'.
    await client.process_job(_job("hj1"))
    await client.join_watchers()
    assert JobMap(relay_paths.jobmap_path).get("hj1")["last_status"] == "delivered"
    assert not any(s == "printed" for (_, s) in mock_hub.statuses)

    # The job finally prints. Drive a full poll CYCLE (not replay_unfinished
    # directly) so the test pins the wiring: the periodic replay step inside
    # _poll_once must report the terminal status without a restart. Deleting the
    # replay call from _poll_once must fail this assertion.
    local.status = "printed"
    await client._poll_once()

    assert ("hj1", "printed") in mock_hub.statuses
    assert JobMap(relay_paths.jobmap_path).get("hj1")["last_status"] == "printed"


async def test_vanished_local_job_uses_printer_lost_in_both_paths(
    relay_paths, mock_hub, hub_http,
):
    # A vanished local job (GET /jobs/{id} 404) must map to the SAME hub status
    # from the in-loop watch and from replay. Both use printer_lost (the joblog
    # pruned the record, which may have aged out AFTER printing) -- NOT
    # printer_expired, which is reserved for the genuine local `expired` event.
    AllowList(relay_paths.allowlist_path).add("alice", display_name="Alice",
                                              renderer_version=None)
    local = _ControllableLocal()
    local.status = None  # GET /jobs/{id} -> 404 for every poll

    # Seed the replay-path job into the durable map BEFORE constructing the
    # client: RelayClient loads its in-memory JobMap at __init__, so a later
    # external write would be invisible to replay_unfinished (matches the
    # existing replay tests' crash-then-fresh-client pattern).
    JobMap(relay_paths.jobmap_path).put(
        "hjreplay", local_job_id="gone", last_status="delivered"
    )

    client = RelayClient(
        _cfg(relay_paths), relay_paths,
        hub=HubClient(hub_http, device_token="dev-token", api_token="api-token"),
        local=local,
    )

    # Watch path: process a fresh job; the background watch sees the 404.
    await client.process_job(_job("hjwatch"))
    await client.join_watchers()

    # Replay path: the pre-seeded delivered job whose local id 404s.
    await client.replay_unfinished()

    watch_status = next(s for (j, s) in mock_hub.statuses if j == "hjwatch")
    replay_status = next(s for (j, s) in mock_hub.statuses if j == "hjreplay")
    assert watch_status == replay_status == "printer_lost"
