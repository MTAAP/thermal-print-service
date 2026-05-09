"""Multi-chunk worker behavior (v0.6.0).

Once any chunk has hit the printer, paper has been consumed and the cutter
has likely fired between chunks. A later chunk failing — even with
``PrinterUnavailable``, normally retryable — must not be retried, because
re-running the job would re-print the already-completed chunks.
"""
import asyncio

import pytest

from printer.queue.cache import PngCache
from printer.queue.joblog import JobLog, JobRecord
from printer.queue.worker import PrintWorker, WorkerDeps
from printer.transport import PrinterUnavailable


class ChunkRecordingTransport:
    """Records auto_cut/feed per call. Optional ``fail_on_chunk`` (1-indexed
    by call count) raises a configurable exception type."""

    def __init__(self, fail_on_chunk: int = 0,
                 fail_with: type[Exception] = RuntimeError) -> None:
        self.calls: list[tuple[bool, int]] = []
        self.fail_on_chunk = fail_on_chunk
        self.fail_with = fail_with

    async def print_png(self, png: bytes, *, auto_cut: bool, feed_lines_after: int) -> int:
        self.calls.append((auto_cut, feed_lines_after))
        if len(self.calls) == self.fail_on_chunk:
            raise self.fail_with("simulated failure")
        return 17


@pytest.mark.asyncio
async def test_worker_prints_each_chunk_with_correct_cut_and_feed(state_dir):
    """Two chunks: intermediate gets ``auto_cut=True, feed=0``; final
    inherits the job's options (``auto_cut=True`` here, ``feed=2``)."""
    log = JobLog(state_dir / "log.jsonl")
    cache = PngCache(state_dir / "cache", max_bytes=10_000_000, ttl_s=3600)
    transport = ChunkRecordingTransport()

    job_id = "JOB-CHUNKS"
    log.append(JobRecord.accepted(
        job_id=job_id, sender=None, document_type="t",
        idempotency_key=None, payload_hash="x", kind="document",
        estimated_paper_mm=20, renderer_version="0.6.0",
        chunk_count=2, trailing_cut=False,
    ))
    cache.put_chunks(job_id, [b"CHUNK0", b"CHUNK1"])

    deps = WorkerDeps(joblog=log, png_cache=cache, transport=transport,
                      retry_interval_s=0.05, max_retry_age_s=10.0)
    worker = PrintWorker(deps, options_lookup=lambda j: (True, 2, None, False))

    await worker.start()
    await asyncio.sleep(0.1)
    await worker.stop()

    assert transport.calls == [(True, 0), (True, 2)]
    events = [r.event for r in log.replay()]
    assert "printed" in events


@pytest.mark.asyncio
async def test_final_chunk_honors_auto_cut_false(state_dir):
    """Two chunks, options.auto_cut=False, no trailing_cut: the cut between
    chunks (forced) still fires, but the FINAL chunk skips the cut."""
    log = JobLog(state_dir / "log.jsonl")
    cache = PngCache(state_dir / "cache", max_bytes=10_000_000, ttl_s=3600)
    transport = ChunkRecordingTransport()

    job_id = "JOB-NOFINAL"
    log.append(JobRecord.accepted(
        job_id=job_id, sender=None, document_type="t",
        idempotency_key=None, payload_hash="x", kind="document",
        estimated_paper_mm=20, renderer_version="0.6.0",
        auto_cut=False, chunk_count=2, trailing_cut=False,
    ))
    cache.put_chunks(job_id, [b"A", b"B"])

    deps = WorkerDeps(joblog=log, png_cache=cache, transport=transport,
                      retry_interval_s=0.05, max_retry_age_s=10.0)
    worker = PrintWorker(deps, options_lookup=lambda j: (False, 2, None, False))

    await worker.start()
    await asyncio.sleep(0.1)
    await worker.stop()

    assert transport.calls == [(True, 0), (False, 2)]


@pytest.mark.asyncio
async def test_trailing_cut_overrides_auto_cut_false(state_dir):
    """A doc that ended with a ``cut`` block gets a hardware cut even if
    options.auto_cut=False — the explicit cut block expresses intent at
    that position. (v0.6.0 precedence rule.)"""
    log = JobLog(state_dir / "log.jsonl")
    cache = PngCache(state_dir / "cache", max_bytes=10_000_000, ttl_s=3600)
    transport = ChunkRecordingTransport()

    job_id = "JOB-TRAIL"
    log.append(JobRecord.accepted(
        job_id=job_id, sender=None, document_type="t",
        idempotency_key=None, payload_hash="x", kind="document",
        estimated_paper_mm=10, renderer_version="0.6.0",
        auto_cut=False, chunk_count=1, trailing_cut=True,
    ))
    cache.put_chunks(job_id, [b"ONLY"])

    deps = WorkerDeps(joblog=log, png_cache=cache, transport=transport,
                      retry_interval_s=0.05, max_retry_age_s=10.0)
    worker = PrintWorker(deps, options_lookup=lambda j: (False, 2, None, True))

    await worker.start()
    await asyncio.sleep(0.1)
    await worker.stop()

    # Single chunk, but trailing_cut forces auto_cut=True
    assert transport.calls == [(True, 2)]


@pytest.mark.asyncio
async def test_chunk_one_fails_with_printer_unavailable_marks_unknown_partial(state_dir):
    """Advisor's flagged correctness trap: chunk 0 prints OK (paper consumed,
    cutter fired), chunk 1 raises PrinterUnavailable. Pre-fix, the worker
    classified PrinterUnavailable as retryable — but retrying re-prints
    chunk 0, duplicating output. Post-fix: any error after chunks_printed > 0
    is unknown_partial, never retried."""
    log = JobLog(state_dir / "log.jsonl")
    cache = PngCache(state_dir / "cache", max_bytes=10_000_000, ttl_s=3600)
    transport = ChunkRecordingTransport(fail_on_chunk=2, fail_with=PrinterUnavailable)

    job_id = "JOB-MID-FAIL"
    log.append(JobRecord.accepted(
        job_id=job_id, sender=None, document_type="t",
        idempotency_key=None, payload_hash="x", kind="document",
        estimated_paper_mm=20, renderer_version="0.6.0",
        chunk_count=2, trailing_cut=False,
    ))
    cache.put_chunks(job_id, [b"A", b"B"])

    deps = WorkerDeps(joblog=log, png_cache=cache, transport=transport,
                      retry_interval_s=0.05, max_retry_age_s=10.0)
    worker = PrintWorker(deps, options_lookup=lambda j: (True, 2, None, False))

    await worker.start()
    await asyncio.sleep(0.2)
    await worker.stop()

    events = [r.event for r in log.replay()]
    # Exactly 2 transport calls (chunk 0 succeeded, chunk 1 failed). No retry.
    assert len(transport.calls) == 2
    assert "unknown_partial" in events
    assert "retry" not in events
    assert "printed" not in events


@pytest.mark.asyncio
async def test_chunk_zero_failure_with_unavailable_still_retries(state_dir):
    """Without any chunk on paper yet, PrinterUnavailable on chunk 0 is
    safely retryable — the spec's USB-disconnect semantics still apply
    when zero chunks have hit the printer."""
    log = JobLog(state_dir / "log.jsonl")
    cache = PngCache(state_dir / "cache", max_bytes=10_000_000, ttl_s=3600)
    # Fail chunk 1 only on the FIRST attempt; subsequent attempts succeed.
    # We track call count to make the first call fail and the rest succeed.
    state = {"calls": 0}

    class FlakyTransport:
        async def print_png(self, png, *, auto_cut, feed_lines_after) -> int:
            state["calls"] += 1
            if state["calls"] == 1:
                raise PrinterUnavailable("first call offline")
            return 17

    transport = FlakyTransport()
    job_id = "JOB-RETRY-OK"
    log.append(JobRecord.accepted(
        job_id=job_id, sender=None, document_type="t",
        idempotency_key=None, payload_hash="x", kind="document",
        estimated_paper_mm=10, renderer_version="0.6.0",
        chunk_count=1, trailing_cut=False,
    ))
    cache.put_chunks(job_id, [b"ONLY"])

    deps = WorkerDeps(joblog=log, png_cache=cache, transport=transport,
                      retry_interval_s=0.05, max_retry_age_s=10.0)
    worker = PrintWorker(deps, options_lookup=lambda j: (True, 2, None, False))

    await worker.start()
    await asyncio.sleep(0.3)
    await worker.stop()

    events = [r.event for r in log.replay()]
    assert events.count("retry") >= 1
    assert "printed" in events
    assert "unknown_partial" not in events
