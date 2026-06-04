from __future__ import annotations

import asyncio
import base64
import logging
from typing import Any

import httpx

from printer.relay.config import RelayConfig
from printer.relay.from_tag import composite_from_band, from_header_block
from printer.relay.hub_client import HubClient
from printer.relay.local_client import LocalClient, SubmitOutcome, SubmitResult
from printer.relay.paths import RelayPaths
from printer.relay.ratelimit import PerFriendRateLimiter
from printer.relay.store import AllowList, CredsStore, InviteStore, JobMap
from printer.relay.sync import sync_friends

logger = logging.getLogger("printer.relay")

# Local job statuses -> hub terminal statuses (spec 8.1 mapping table).
_LOCAL_TO_HUB = {
    "printed": "printed",
    "expired": "printer_expired",
    "retry_timeout": "printer_retry_timeout",
    "unknown_partial": "printer_unknown_partial",
}
_LOCAL_TERMINAL = set(_LOCAL_TO_HUB)
# Hub statuses that end the job from the relay's perspective (for JobMap.unfinished).
_HUB_TERMINAL = set(_LOCAL_TO_HUB.values()) | {
    "rejected_not_allowlisted", "rejected_rate_limited",
    "rejected_incompatible", "failed",
}


class RelayClient:
    def __init__(
        self, config: RelayConfig, paths: RelayPaths, *,
        hub: HubClient | None = None, local: LocalClient | None = None,
    ) -> None:
        self._cfg = config
        self._paths = paths
        self._hub = hub
        self._local = local
        self._allowlist = AllowList(paths.allowlist_path)
        self._ratelimit = PerFriendRateLimiter(
            paths.root / "rate.json", per_hour=config.per_friend_rate_per_hour
        )
        self._jobmap = JobMap(paths.jobmap_path)
        self._last_reported_renderer_version: str | None = None
        # Strong refs to in-flight terminal-watch tasks. asyncio only holds a
        # weak reference to a bare create_task() result, so without this set a
        # watch could be garbage-collected mid-flight and silently drop a status
        # report. The done-callback discards each task once it completes.
        self._watch_tasks: set[asyncio.Task[None]] = set()

    # ----- per-job pipeline (spec 7.1-7.3) -----

    async def process_job(self, job: dict[str, Any]) -> None:
        assert self._hub is not None and self._local is not None
        # Defensive shape check: a malformed inbox job (a hub bug, a truncated
        # body, a captive-portal/proxy response decoded oddly) must NOT raise out
        # of the poll loop -- that would kill run_forever and stop the per-cycle
        # replay_unfinished that every other path relies on. Terminate the poison
        # job instead of crashing.
        hub_job_id = job.get("job_id")
        if not isinstance(hub_job_id, str) or not hub_job_id:
            logger.error("relay: inbox job missing job_id; dropping: %r", job)
            return
        sender = job.get("sender")
        sent_at = job.get("sent_at")
        if not isinstance(sender, str) or not isinstance(sent_at, str):
            logger.warning("relay: malformed job %s (bad sender/sent_at); marking failed",
                           hub_job_id)
            await self._hub.post_status(hub_job_id, "failed")
            return

        # Gate 1: local allow-list (spec 7.1).
        if not self._allowlist.contains(sender):
            await self._hub.post_status(hub_job_id, "rejected_not_allowlisted")
            return

        # Gate 2: per-friend rate limit (spec 7.1), deterministic by sent_at.
        if not self._ratelimit.check_and_record(sender, sent_at):
            await self._hub.post_status(hub_job_id, "rejected_rate_limited")
            return

        # Transform (spec 7.2/7.4) + submit. A malformed payload (missing keys,
        # bad base64) surfaces as KeyError/ValueError -> deterministic failure, so
        # the poison job becomes terminal rather than redelivering forever.
        try:
            result = await self._submit(job, hub_job_id, sender, sent_at)
        except (ValueError, KeyError) as exc:
            logger.warning("relay: transform rejected/malformed job %s: %s", hub_job_id, exc)
            await self._hub.post_status(hub_job_id, "failed")
            return

        await self._handle_submit_result(hub_job_id, result)

    async def _submit(
        self, job: dict[str, Any], hub_job_id: str, sender: str, sent_at: str
    ) -> SubmitResult:
        assert self._local is not None
        namespaced = f"friend:{sender}"
        if job["kind"] == "raw":
            png = base64.b64decode(job["payload"]["raw_png_b64"])
            composed = composite_from_band(png, sender=sender, sent_at=sent_at)
            return await self._local.print_raw(
                composed, sender=namespaced, idempotency_key=hub_job_id
            )
        document = job["payload"]["document"]
        tagged = from_header_block(document, sender=sender, sent_at=sent_at)
        return await self._local.print_document(
            tagged, sender=namespaced, idempotency_key=hub_job_id
        )

    async def _handle_submit_result(self, hub_job_id: str, result: SubmitResult) -> None:
        assert self._hub is not None
        if result.outcome is SubmitOutcome.ACCEPTED:
            await self._on_accepted(hub_job_id, result.local_job_id or "")
            return
        if result.outcome is SubmitOutcome.INCOMPATIBLE:
            # Deterministic rejection: a retry just reprints the rejection (spec 7.3).
            await self._hub.post_status(hub_job_id, "rejected_incompatible")
            return
        if result.outcome is SubmitOutcome.TOO_LARGE:
            await self._hub.post_status(hub_job_id, "failed")
            return
        if result.outcome is SubmitOutcome.QUEUE_FULL:
            # Retryable: do NOT ack, do NOT post status. Let the hub lease expire
            # and redeliver (spec 7.3). Stop processing this job for now.
            logger.info("relay: local queue full for job %s; leaving leased for redelivery",
                        hub_job_id)
            return
        if result.outcome is SubmitOutcome.IDEMPOTENCY_MISMATCH:
            # Determinism-bug canary (spec 7.3): impossible if the FROM transform
            # is truly deterministic. Log loudly, fail, do not loop.
            logger.error(
                "relay: idempotency_key_payload_mismatch for job %s -- the FROM "
                "transform is not deterministic; investigate before re-enabling", hub_job_id,
            )
            await self._hub.post_status(hub_job_id, "failed")
            return

    async def _on_accepted(self, hub_job_id: str, local_job_id: str) -> None:
        assert self._hub is not None and self._local is not None
        # ORDER IS LOAD-BEARING (spec 7.3): persist+fsync the map BEFORE the ack.
        # If we crash before the ack, the lease survives -> redelivery; the local
        # idempotency layer returns the same local_job_id and we re-ack. The hub
        # ack is idempotent (Plan 1 Task 13A): re-acking an already-delivered job
        # returns {ok: true}, so the re-ack never raises.
        self._jobmap.put(hub_job_id, local_job_id=local_job_id, last_status="delivered")
        await self._hub.ack(hub_job_id)
        # Watch to terminal in the BACKGROUND so a slow job (backlog, out-of-paper
        # retry) cannot block the long-poll loop from delivering other friends'
        # jobs for up to local_terminal_timeout_s. Periodic replay finishes any
        # watch that times out, and Fix A makes a resulting double-post safe.
        task = asyncio.create_task(self._watch_to_terminal(hub_job_id, local_job_id))
        self._watch_tasks.add(task)
        task.add_done_callback(self._on_watch_done)

    def _on_watch_done(self, task: asyncio.Task[None]) -> None:
        self._watch_tasks.discard(task)
        # Retrieve any exception so it does not surface as an "exception was never
        # retrieved" warning at GC. A failed watch is not lost work: the per-cycle
        # replay_unfinished re-reports the still-'delivered' job next cycle.
        if not task.cancelled() and (exc := task.exception()) is not None:
            logger.warning("relay: terminal-watch task failed (%s); replay will retry", exc)

    async def _watch_to_terminal(self, hub_job_id: str, local_job_id: str) -> None:
        assert self._hub is not None and self._local is not None
        deadline = asyncio.get_event_loop().time() + self._cfg.local_terminal_timeout_s
        while asyncio.get_event_loop().time() < deadline:
            status = await self._local.get_job_status(local_job_id)
            if status is None:
                # Local job gone (joblog aged out past the deadline) -> report
                # printer_expired and stop (spec 7.3). Same status the startup
                # replay path uses for the identical 404 condition; the two paths
                # must agree on the hub status for a vanished local job.
                await self._report_terminal(hub_job_id, local_job_id, "printer_expired")
                return
            if status in _LOCAL_TERMINAL:
                await self._report_terminal(hub_job_id, local_job_id,
                                            _LOCAL_TO_HUB[status])
                return
            await asyncio.sleep(0.5)
        # Timed out waiting: leave the map at 'delivered'; startup replay will
        # finish reporting once the local job reaches terminal.

    async def _report_terminal(self, hub_job_id: str, local_job_id: str,
                               hub_status: str) -> None:
        assert self._hub is not None
        await self._hub.post_status(hub_job_id, hub_status)
        self._jobmap.put(hub_job_id, local_job_id=local_job_id, last_status=hub_status)

    async def join_watchers(self) -> None:
        """Await all outstanding background watch tasks. Used by run_forever's
        shutdown path and by tests that call process_job directly and then need
        the terminal status to have been posted before asserting."""
        # Snapshot: the done-callback mutates the set as tasks finish.
        for task in list(self._watch_tasks):
            await asyncio.gather(task, return_exceptions=True)

    # ----- startup replay (spec 7.3) -----

    async def replay_unfinished(self) -> None:
        assert self._local is not None
        for hub_job_id, entry in self._jobmap.unfinished(terminal=_HUB_TERMINAL).items():
            local_job_id = entry["local_job_id"]
            status = await self._local.get_job_status(local_job_id)
            if status is None:
                await self._report_terminal(hub_job_id, local_job_id, "printer_expired")
            elif status in _LOCAL_TERMINAL:
                await self._report_terminal(hub_job_id, local_job_id, _LOCAL_TO_HUB[status])
            # still queued/printing: leave for the next replay/poll cycle.

    # ----- friend sync (spec 5) -----

    async def sync_friends_once(self) -> None:
        """Pull the hub's friend list and reconcile it against the local
        allow-list (spec 5 inviter-side auto-add + unfriend removal).

        Without this the §5 auto-add never runs at runtime: when A invites B and
        B joins, A's relay never adds B, so B's prints back are rejected forever.

        Failure isolation is load-bearing: sync_friends removes every allow-list
        handle NOT present in the passed list, so an empty list from a swallowed
        fetch error would prune the allow-list toward empty. We therefore call
        sync_friends ONLY in the `else` branch -- on a genuinely successful,
        complete fetch -- and let a transient error log-and-continue without ever
        passing a bogus [] into the reconciler."""
        assert self._hub is not None
        # Best-effort maintenance: friend sync must NEVER crash the poll loop, and
        # must reconcile ONLY a genuinely successful fetch (a swallowed error must
        # not pass [] to sync_friends, which prunes the allow-list of handles not
        # in the list). Both hold here: sync_friends runs only after get_friends
        # returns inside the try, and ANY failure (httpx OR a malformed-response
        # parse error) is logged and skipped rather than escaping to run_forever.
        try:
            friends = await self._hub.get_friends()
            sync_friends(
                friends, allowlist=self._allowlist,
                invites=InviteStore(self._paths.invites_path),
            )
        except Exception as exc:
            logger.warning("relay: friend sync skipped (%s)", exc)

    # ----- capability reporting (spec 6.2) -----

    async def report_capabilities_if_changed(self) -> None:
        assert self._hub is not None and self._local is not None
        schema = await self._local.get_schema()
        version = schema["renderer_version"]
        if version == self._last_reported_renderer_version:
            return
        await self._hub.put_capabilities(
            renderer_version=version,
            blocks_schema=schema["blocks"],
            block_types=schema["block_types"],
        )
        self._last_reported_renderer_version = version

    # ----- the long-poll loop + reconnect (spec 4, 7) -----

    async def run_forever(self) -> None:
        creds = CredsStore(self._paths.creds_path).load()
        if creds is None:
            raise RuntimeError("not joined to a hub; run `printer-svc hub join <code>` first")
        backoff = self._cfg.reconnect_backoff_base_s
        async with httpx.AsyncClient(base_url=creds["hub_url"]) as hub_http, \
                httpx.AsyncClient(base_url=self._cfg.local_service_url) as local_http:
            self._hub = HubClient(
                hub_http, device_token=creds["device_token"], api_token=creds["api_token"]
            )
            self._local = LocalClient(local_http)
            try:
                while True:
                    try:
                        # Replay + capability report + friend sync all run INSIDE
                        # the reconnect guard so a transient hub error during
                        # startup replay (e.g. a 409 that was a permanent
                        # crash-loop before Fix A) backs off instead of killing
                        # the process. _poll_once long-polls the inbox last.
                        await self._poll_once()
                        backoff = self._cfg.reconnect_backoff_base_s  # reset on success
                    except httpx.HTTPError as exc:
                        logger.warning("relay: hub unreachable (%s); backing off %.1fs",
                                       exc, backoff)
                        await asyncio.sleep(backoff)
                        backoff = min(backoff * 2, self._cfg.reconnect_backoff_max_s)
                    except Exception:
                        # A non-httpx error (malformed response, disk fault, an
                        # unforeseen bug) must NOT kill the loop: replay_unfinished
                        # only runs while run_forever lives, so a crash here strands
                        # every 'delivered' job forever. Log and back off like a
                        # transient fault. CancelledError is a BaseException, so it
                        # still propagates and shutdown works.
                        logger.exception(
                            "relay: unexpected error in poll cycle; backing off %.1fs", backoff)
                        await asyncio.sleep(backoff)
                        backoff = min(backoff * 2, self._cfg.reconnect_backoff_max_s)
            finally:
                # Cancel + drain outstanding watch tasks before the local client
                # closes; a watch awaiting GET /jobs/{id} on a closed client
                # would raise. Snapshot first: the done-callback mutates the set.
                for task in list(self._watch_tasks):
                    task.cancel()
                await self.join_watchers()

    async def _poll_once(self) -> None:
        assert self._hub is not None
        # Per-cycle maintenance, before the long-poll so it never sits behind a
        # 25s inbox wait: (1) replay catches a job that reached terminal AFTER
        # the in-loop watch deadline while the relay stayed up (otherwise it is
        # stranded at 'delivered' forever); (2) friend sync wires the §5
        # inviter-side auto-add into the runtime; (3) capabilities re-report on a
        # renderer-version change.
        await self.replay_unfinished()
        await self.report_capabilities_if_changed()
        await self.sync_friends_once()
        job = await self._hub.get_inbox(wait_s=self._cfg.long_poll_wait_s)
        if job is None:
            return
        await self.process_job(job)
