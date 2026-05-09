import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from printer.queue.cache import PngCache
from printer.queue.joblog import JobLog, JobRecord
from printer.queue.worker import (
    DEFAULT_OPTIONS,
    PrintWorker,
    WorkerDeps,
    make_options_lookup,
    options_from_replay,
)
from printer.transport import PrinterUnavailable


class FakeTransport:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.fail_until: int = 0
        self.partial_fail: bool = False
        self.unavailable_until: int = 0

    async def print_png(self, png: bytes, *, auto_cut: bool, feed_lines_after: int) -> int:
        self.calls.append("print")
        if len(self.calls) <= self.unavailable_until:
            raise PrinterUnavailable("printer offline (test)")
        if len(self.calls) <= self.fail_until:
            raise RuntimeError("printer unavailable")
        if self.partial_fail:
            raise OSError("USB failed mid-stream")
        return 187


@pytest.mark.asyncio
async def test_worker_prints_pending_jobs(state_dir):
    log = JobLog(state_dir / "log.jsonl")
    cache = PngCache(state_dir / "cache", max_bytes=10_000_000, ttl_s=3600)
    transport = FakeTransport()

    job_id = "JOB-A"
    log.append(JobRecord.accepted(
        job_id=job_id, sender="cron", document_type="t",
        idempotency_key=None, payload_hash="x", kind="raw",
        estimated_paper_mm=200, renderer_version="0.1.0",
    ))
    cache.put_chunks(job_id, [b"PNGBYTES"])

    deps = WorkerDeps(
        joblog=log, png_cache=cache, transport=transport,
        retry_interval_s=0.05, max_retry_age_s=10.0,
    )
    worker = PrintWorker(deps, options_lookup=lambda j: (True, 2, None, False))

    await worker.start()
    await worker.enqueue(job_id)
    await asyncio.sleep(0.1)
    await worker.stop()

    events = [r.event for r in log.replay()]
    assert "printed" in events


@pytest.mark.asyncio
async def test_worker_drops_expired_jobs_at_dequeue(state_dir):
    log = JobLog(state_dir / "log.jsonl")
    cache = PngCache(state_dir / "cache", max_bytes=10_000_000, ttl_s=3600)
    transport = FakeTransport()

    job_id = "JOB-EXP"
    log.append(JobRecord.accepted(
        job_id=job_id, sender="cron", document_type="t",
        idempotency_key=None, payload_hash="x", kind="raw",
        estimated_paper_mm=10, renderer_version="0.1.0",
    ))
    cache.put_chunks(job_id, [b"X"])

    past = (datetime.now(UTC) - timedelta(seconds=10)).isoformat()
    deps = WorkerDeps(joblog=log, png_cache=cache, transport=transport,
                      retry_interval_s=0.01, max_retry_age_s=10.0)
    worker = PrintWorker(deps, options_lookup=lambda j: (True, 2, past, False))

    await worker.start()
    await worker.enqueue(job_id)
    await asyncio.sleep(0.05)
    await worker.stop()

    events = [r.event for r in log.replay()]
    assert "expired" in events
    assert transport.calls == []  # never attempted


@pytest.mark.asyncio
async def test_worker_retries_then_succeeds(state_dir):
    log = JobLog(state_dir / "log.jsonl")
    cache = PngCache(state_dir / "cache", max_bytes=10_000_000, ttl_s=3600)
    transport = FakeTransport()
    transport.fail_until = 1  # first attempt fails

    job_id = "JOB-RETRY"
    log.append(JobRecord.accepted(
        job_id=job_id, sender=None, document_type="t",
        idempotency_key=None, payload_hash="x", kind="raw",
        estimated_paper_mm=10, renderer_version="0.1.0",
    ))
    cache.put_chunks(job_id, [b"X"])

    deps = WorkerDeps(joblog=log, png_cache=cache, transport=transport,
                      retry_interval_s=0.05, max_retry_age_s=10.0)
    worker = PrintWorker(deps, options_lookup=lambda j: (True, 2, None, False))

    await worker.start()
    await worker.enqueue(job_id)
    await asyncio.sleep(0.2)
    await worker.stop()

    events = [r.event for r in log.replay()]
    assert events.count("retry") >= 1
    assert "printed" in events


@pytest.mark.asyncio
async def test_worker_retries_when_printer_unavailable(state_dir):
    """Spec §11: USB-disconnected printer keeps the job in the queue and
    retries every retry_interval. PrinterUnavailable is the transport seam
    for "device couldn't be opened" — it must NOT be misclassified as
    unknown_partial."""
    log = JobLog(state_dir / "log.jsonl")
    cache = PngCache(state_dir / "cache", max_bytes=10_000_000, ttl_s=3600)
    transport = FakeTransport()
    transport.unavailable_until = 1  # first attempt: printer offline

    job_id = "JOB-OFFLINE"
    log.append(JobRecord.accepted(
        job_id=job_id, sender=None, document_type="t",
        idempotency_key=None, payload_hash="x", kind="raw",
        estimated_paper_mm=10, renderer_version="0.1.0",
    ))
    cache.put_chunks(job_id, [b"X"])

    deps = WorkerDeps(joblog=log, png_cache=cache, transport=transport,
                      retry_interval_s=0.05, max_retry_age_s=10.0)
    worker = PrintWorker(deps, options_lookup=lambda j: (True, 2, None, False))

    await worker.start()
    await worker.enqueue(job_id)
    await asyncio.sleep(0.2)
    await worker.stop()

    events = [r.event for r in log.replay()]
    # Exactly the spec semantics: stays in queue, retries, then prints once
    # the printer comes back. NOT unknown_partial.
    assert events.count("retry") >= 1
    assert "printed" in events
    assert "unknown_partial" not in events


@pytest.mark.asyncio
async def test_worker_tolerates_naive_expires_at(state_dir):
    """A client that submits ``expires_at`` without a timezone offset
    (naive datetime) must not wedge the worker. ``datetime.fromisoformat``
    returns a naive value, comparing it to a tz-aware ``now`` raises
    TypeError. Pre-fix behavior: TypeError bubbled past the
    ``except ValueError`` clause and the unexpected-exception branch
    re-enqueued the job as a transient retry — the job stayed pending
    and was never honored or rejected.

    Post-fix: naive ``expires_at`` is treated as UTC. A naive past timestamp
    expires the job; a naive future timestamp lets it print.
    """
    log = JobLog(state_dir / "log.jsonl")
    cache = PngCache(state_dir / "cache", max_bytes=10_000_000, ttl_s=3600)
    transport = FakeTransport()

    job_id = "JOB-NAIVE-PAST"
    log.append(JobRecord.accepted(
        job_id=job_id, sender=None, document_type="t",
        idempotency_key=None, payload_hash="x", kind="raw",
        estimated_paper_mm=10, renderer_version="0.5.2",
    ))
    cache.put_chunks(job_id, [b"X"])

    # Past timestamp, NO trailing offset, NO 'Z' — pure naive ISO.
    past_naive = (datetime.now(UTC) - timedelta(seconds=30)) \
        .replace(tzinfo=None).isoformat(timespec="seconds")
    assert "+" not in past_naive and "Z" not in past_naive  # really naive

    deps = WorkerDeps(joblog=log, png_cache=cache, transport=transport,
                      retry_interval_s=0.01, max_retry_age_s=10.0)
    worker = PrintWorker(deps, options_lookup=lambda j: (True, 2, past_naive, False))

    await worker.start()
    await asyncio.sleep(0.05)
    await worker.stop()

    events = [r.event for r in log.replay()]
    assert "expired" in events
    assert transport.calls == []  # never attempted
    # Crucially: NOT marked as a retry. Pre-fix, this would have been
    # ``retry`` (or several) because TypeError fell through.
    assert "retry" not in events


@pytest.mark.asyncio
async def test_worker_preserves_retry_age_across_restart(state_dir):
    """Codex P1 (#6): ``max_retry_age_s`` is the wall-clock budget a job
    has between first failure and abandoning it. Pre-fix ``start()``
    seeded ``_first_seen`` to ``time.time()`` for every replayed pending
    job, so a job that had been failing for 23h would reset to age 0 on
    each restart and could be retried indefinitely. The fix seeds
    ``_first_seen`` from the durable ``accepted`` timestamp so the budget
    is preserved across crashes/restarts.
    """
    log = JobLog(state_dir / "log.jsonl")
    cache = PngCache(state_dir / "cache", max_bytes=10_000_000, ttl_s=3600)
    transport = FakeTransport()
    transport.fail_until = 999  # always fails (RuntimeError, retryable)

    job_id = "JOB-AGED"
    # Append an accepted record with an old ts — older than max_retry_age_s.
    old_ts = (datetime.now(UTC) - timedelta(seconds=120)) \
        .isoformat(timespec="seconds").replace("+00:00", "Z")
    log.append(JobRecord(
        event="accepted", job_id=job_id, ts=old_ts,
        sender=None, document_type="t",
        idempotency_key=None, payload_hash="x", kind="raw",
        estimated_paper_mm=10, renderer_version="0.6.0",
        auto_cut=True, feed_lines_after=2, expires_at=None,
        chunk_count=1, trailing_cut=False,
    ))
    cache.put_chunks(job_id, [b"X"])

    # Budget is 60s; the accepted ts is 120s ago. First failure must trip
    # ``retry_timeout`` immediately, NOT log a transient retry.
    deps = WorkerDeps(joblog=log, png_cache=cache, transport=transport,
                      retry_interval_s=0.05, max_retry_age_s=60.0)
    worker = PrintWorker(deps, options_lookup=lambda j: (True, 2, None, False))

    await worker.start()
    await asyncio.sleep(0.1)
    await worker.stop()

    events = [r.event for r in log.replay()]
    # The fix flips this from "retry" (pre-fix) to "retry_timeout" (post-fix).
    assert "retry_timeout" in events
    assert events.count("retry") == 0


def test_options_from_replay_rebuilds_persisted_options(state_dir):
    """Spec §11 + Codex P1: the worker must honor per-job options after a
    crash/restart. ``cmd_run`` rebuilds ``options_store`` by replaying the
    durable log. Without this fix, restarted jobs printed with the
    ``(True, 2, None)`` fallback — losing ``auto_cut=False``, custom
    ``feed_lines_after``, and (worst) ``expires_at``, so expired jobs
    could print after a restart.
    """
    log = JobLog(state_dir / "log.jsonl")
    expires = "2099-01-01T00:00:00+00:00"
    log.append(JobRecord.accepted(
        job_id="JOB-A", sender=None, document_type="t",
        idempotency_key=None, payload_hash="h", kind="document",
        estimated_paper_mm=42, renderer_version="0.5.2",
        auto_cut=False, feed_lines_after=4, expires_at=expires,
    ))
    log.append(JobRecord.accepted(
        job_id="JOB-B", sender=None, document_type="t",
        idempotency_key=None, payload_hash="h", kind="document",
        estimated_paper_mm=10, renderer_version="0.5.2",
        # Defaults; explicitly passed
        auto_cut=True, feed_lines_after=2, expires_at=None,
    ))

    out = options_from_replay(log)
    assert out["JOB-A"] == (False, 4, expires, False)
    assert out["JOB-B"] == (True, 2, None, False)


def test_default_options_is_four_tuple_matching_unpack_arity(state_dir):
    """Codex P1 (#9): the in-memory ``options_store`` fallback MUST match
    the worker's 4-tuple unpack ``(auto_cut, feed_lines_after,
    expires_at_iso, trailing_cut)``. Pre-fix the production wiring fell
    back to a 3-tuple and triggered ``ValueError`` for any pending job
    skipped by ``options_from_replay`` (i.e. pre-v0.5.2 records). The
    helper exists so cli/main.py and the test fixture share one shape.
    """
    assert len(DEFAULT_OPTIONS) == 4
    auto_cut, feed_lines_after, expires_at, trailing_cut = DEFAULT_OPTIONS
    assert auto_cut is True and feed_lines_after == 2
    assert expires_at is None and trailing_cut is False


@pytest.mark.asyncio
async def test_worker_prints_pre_v052_record_via_default_fallback(state_dir):
    """End-to-end regression for Codex P1 (#9): replay a record persisted
    under the pre-v0.5.2 schema (``auto_cut=None``). ``options_from_replay``
    skips it; the production lookup must return ``DEFAULT_OPTIONS`` —
    not the pre-fix 3-tuple — so the worker can unpack four values and
    actually drain the job. Pre-fix this raised ``ValueError`` on unpack,
    the unexpected-exception branch logged a transient retry, and the
    job stayed pending forever.
    """
    log = JobLog(state_dir / "log.jsonl")
    cache = PngCache(state_dir / "cache", max_bytes=10_000_000, ttl_s=3600)
    transport = FakeTransport()

    job_id = "JOB-OLD"
    log.append(JobRecord(
        event="accepted", job_id=job_id, ts="2026-04-01T00:00:00Z",
        sender="cron", document_type="briefing",
        idempotency_key=None, payload_hash="x", kind="document",
        estimated_paper_mm=10, renderer_version="0.5.0",
        # auto_cut/feed_lines_after/expires_at/trailing_cut all None — the
        # exact shape of a record persisted before the v0.5.2 options-
        # persistence fix.
    ))
    cache.put_chunks(job_id, [b"X"])

    options_store = options_from_replay(log)
    assert job_id not in options_store  # confirms the fallback path is hit

    deps = WorkerDeps(joblog=log, png_cache=cache, transport=transport,
                      retry_interval_s=0.05, max_retry_age_s=10.0)
    worker = PrintWorker(deps, options_lookup=make_options_lookup(options_store))

    await worker.start()
    await asyncio.sleep(0.1)
    await worker.stop()

    events = [r.event for r in log.replay()]
    # Without the fix this asserts "retry" appears and "printed" doesn't.
    assert "printed" in events
    assert "retry" not in events


def test_options_from_replay_skips_pre_v052_records(state_dir):
    """Backward compat: records persisted before the v0.5.2 fix have
    ``auto_cut=None``. ``options_from_replay`` must skip them so the
    worker falls back to the ``(True, 2, None)`` default — that is exactly
    pre-fix behavior, so we don't silently rewrite options for old jobs."""
    log = JobLog(state_dir / "log.jsonl")
    log.append(JobRecord(
        event="accepted", job_id="OLD", ts="2026-05-09T00:00:00Z",
        kind="document", estimated_paper_mm=10, renderer_version="0.5.0",
        # auto_cut, feed_lines_after, expires_at all default to None
    ))

    out = options_from_replay(log)
    assert "OLD" not in out


@pytest.mark.asyncio
async def test_worker_marks_unknown_partial_on_mid_write_ioerror(state_dir):
    """Spec §11: USB IOError mid-print is non-retryable; we cannot know
    how much paper was consumed, so duplicate-printing risk forces
    unknown_partial."""
    log = JobLog(state_dir / "log.jsonl")
    cache = PngCache(state_dir / "cache", max_bytes=10_000_000, ttl_s=3600)
    transport = FakeTransport()
    transport.partial_fail = True

    job_id = "JOB-PARTIAL"
    log.append(JobRecord.accepted(
        job_id=job_id, sender=None, document_type="t",
        idempotency_key=None, payload_hash="x", kind="raw",
        estimated_paper_mm=10, renderer_version="0.1.0",
    ))
    cache.put_chunks(job_id, [b"X"])

    deps = WorkerDeps(joblog=log, png_cache=cache, transport=transport,
                      retry_interval_s=0.05, max_retry_age_s=10.0)
    worker = PrintWorker(deps, options_lookup=lambda j: (True, 2, None, False))

    # start() replays the accepted job from the log and enqueues it once.
    # No manual enqueue — that would duplicate the dispatch.
    await worker.start()
    await asyncio.sleep(0.1)
    await worker.stop()

    events = [r.event for r in log.replay()]
    assert "unknown_partial" in events
    # No retry — exactly one transport call; spec is explicit.
    assert transport.calls == ["print"]
    assert "printed" not in events
