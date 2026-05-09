import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from printer.queue.cache import PngCache
from printer.queue.joblog import JobLog, JobRecord
from printer.queue.worker import PrintWorker, WorkerDeps


class FakeTransport:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def print_png(self, png, *, auto_cut, feed_lines_after) -> int:
        self.calls.append("print")
        return 50


@pytest.mark.asyncio
async def test_worker_does_not_expire_when_clock_unsynced(state_dir):
    log = JobLog(state_dir / "log.jsonl")
    cache = PngCache(state_dir / "cache", max_bytes=10_000_000, ttl_s=3600)
    transport = FakeTransport()

    job_id = "JOB-CLOCK"
    log.append(JobRecord.accepted(
        job_id=job_id, sender=None, document_type="t",
        idempotency_key=None, payload_hash="x", kind="raw",
        estimated_paper_mm=10, renderer_version="0.5.0",
    ))
    cache.put_chunks(job_id, [b"PNG"])

    # expires_at is in the past
    past = (datetime.now(UTC) - timedelta(seconds=10)).isoformat()
    deps = WorkerDeps(
        joblog=log, png_cache=cache, transport=transport,
        retry_interval_s=0.01, max_retry_age_s=10.0,
        clock_ok=lambda: False,  # unsynchronized
    )
    worker = PrintWorker(deps, options_lookup=lambda j: (True, 2, past, False))

    # ``start()`` replays the pending job via ``pending_after_replay()`` —
    # no explicit enqueue is needed, and avoids double-print.
    await worker.start()
    await asyncio.sleep(0.1)
    await worker.stop()

    events = [r.event for r in log.replay()]
    # Job is NOT expired despite past expires_at because clock is unsynced;
    # the worker prints it instead.
    assert "expired" not in events
    assert "printed" in events
    assert transport.calls == ["print"]


@pytest.mark.asyncio
async def test_worker_resumes_expiry_when_clock_recovers(state_dir):
    log = JobLog(state_dir / "log.jsonl")
    cache = PngCache(state_dir / "cache", max_bytes=10_000_000, ttl_s=3600)
    transport = FakeTransport()

    job_id = "JOB-RESUME"
    log.append(JobRecord.accepted(
        job_id=job_id, sender=None, document_type="t",
        idempotency_key=None, payload_hash="x", kind="raw",
        estimated_paper_mm=10, renderer_version="0.5.0",
    ))
    cache.put_chunks(job_id, [b"PNG"])

    past = (datetime.now(UTC) - timedelta(seconds=10)).isoformat()

    # Start with clock unsynced, then flip the flag mid-run.
    clock_state = {"ok": False}
    deps = WorkerDeps(
        joblog=log, png_cache=cache, transport=transport,
        retry_interval_s=0.01, max_retry_age_s=10.0,
        clock_ok=lambda: clock_state["ok"],
    )
    worker = PrintWorker(deps, options_lookup=lambda j: (True, 2, past, False))

    # Flip BEFORE starting so the first dequeue sees clock_ok = True
    clock_state["ok"] = True

    await worker.start()
    await asyncio.sleep(0.05)
    await worker.stop()

    events = [r.event for r in log.replay()]
    # Now clock is fine, so expiry kicks in
    assert "expired" in events
    assert transport.calls == []
