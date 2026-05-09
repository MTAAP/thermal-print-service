from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from .cache import PngCache
from .joblog import JobLog, JobRecord


class Transport(Protocol):
    async def print_png(
        self, png: bytes, *, auto_cut: bool, feed_lines_after: int
    ) -> int: ...


# (auto_cut, feed_lines_after, expires_at_iso_or_none, trailing_cut)
# ``trailing_cut`` is the per-job flag set by the renderer when the doc
# ended with a ``cut`` block; it forces ``auto_cut=True`` on the final
# chunk even if ``options.auto_cut`` is False.
OptionsTuple = tuple[bool, int, str | None, bool]
OptionsLookup = Callable[[str], OptionsTuple]


# Single source of truth for the worker fallback. Pre-v0.5.2 records are
# skipped by ``options_from_replay`` (their ``auto_cut`` is None), so the
# lookup falls back to this default. The shape MUST match the unpack in
# ``_handle`` — drift here lands as a ``ValueError`` that the worker logs
# as a transient retry but never re-enqueues, leaving the job stuck.
DEFAULT_OPTIONS: OptionsTuple = (True, 2, None, False)


def make_options_lookup(store: dict[str, OptionsTuple]) -> OptionsLookup:
    """Build the worker's ``options_lookup`` from the in-memory store.

    Production wiring (``cli/main.py``) and the test fixtures share this
    factory so the fallback shape can never drift between them.
    """
    return lambda jid: store.get(jid, DEFAULT_OPTIONS)


@dataclass
class WorkerDeps:
    joblog: JobLog
    png_cache: PngCache
    transport: Transport
    retry_interval_s: float
    max_retry_age_s: float
    # Spec §11: while the Pi clock is unsynchronized (boot before NTP, or
    # time-sync daemon unhealthy), comparing ``expires_at`` to local time
    # would falsely drop fresh jobs. The worker calls ``clock_ok()`` before
    # the expiry check; when it returns False, the check is skipped and the
    # job is allowed to print. Default is conservative: assume sync is fine.
    clock_ok: Callable[[], bool] = lambda: True


def _now_utc() -> datetime:
    return datetime.now(UTC)


def _parse_iso(ts: str) -> datetime:
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    dt = datetime.fromisoformat(ts)
    # ISO 8601 strings without a timezone offset (``2026-05-09T12:00:00``)
    # parse to a naive datetime; comparing naive vs tz-aware raises TypeError
    # at the ``_now_utc() > parsed`` check below. Treat naive as UTC: the spec
    # wants expiry honored, and refusing to interpret it would leave the job
    # queued instead. The API layer should ideally reject naive at submission,
    # but defending here keeps the worker robust.
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


class PrintWorker:
    """Single FIFO worker draining an asyncio.Queue.

    Replay on start: every still-pending job from the durable log is
    re-enqueued in arrival order. New POSTs append to the durable log
    (via the HTTP layer) AND call ``enqueue``. The queue is just a wakeup.
    """

    def __init__(self, deps: WorkerDeps, *, options_lookup: OptionsLookup) -> None:
        self._d = deps
        self._opts = options_lookup
        self._q: asyncio.Queue[str] = asyncio.Queue()
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._first_seen: dict[str, float] = {}

    async def start(self) -> None:
        for rec in self._d.joblog.pending_after_replay():
            # Seed ``_first_seen`` from the durable accepted timestamp so
            # ``max_retry_age_s`` spans across crashes and restarts. Pre-fix
            # this was ``time.time()`` for every replay, so a job that had
            # been failing for 23h would reset to age 0 on each restart and
            # could be retried indefinitely instead of transitioning to
            # ``retry_timeout``. ``rec.ts`` for pending records is the
            # accepted-event ISO timestamp.
            try:
                accepted_at = _parse_iso(rec.ts).timestamp()
            except (ValueError, TypeError):
                accepted_at = time.time()
            self._first_seen[rec.job_id] = accepted_at
            await self._q.put(rec.job_id)
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            await self._q.put("__STOP__")
            await self._task

    async def enqueue(self, job_id: str) -> None:
        self._first_seen.setdefault(job_id, time.time())
        await self._q.put(job_id)

    async def _run(self) -> None:
        while not self._stop.is_set():
            job_id = await self._q.get()
            if job_id == "__STOP__":
                return
            try:
                await self._handle(job_id)
            except Exception as exc:
                self._d.joblog.append(JobRecord.retry(
                    job_id=job_id, detail=f"unexpected: {exc!r}"
                ))

    async def _handle(self, job_id: str) -> None:
        auto_cut, feed_lines_after, expires_at_iso, trailing_cut = self._opts(job_id)

        if expires_at_iso and self._d.clock_ok():
            try:
                if _now_utc() > _parse_iso(expires_at_iso):
                    self._d.joblog.append(JobRecord.expired(
                        job_id=job_id, detail=f"past expires_at={expires_at_iso}"
                    ))
                    return
            except (ValueError, TypeError):
                # Malformed timestamp or pathological tz state: don't expire
                # on garbage input, fall through to print. The unexpected-
                # exception branch upstream would otherwise classify this as
                # a transient retry.
                pass

        chunks = self._d.png_cache.get_chunks(job_id)
        if not chunks:
            self._d.joblog.append(JobRecord.unknown_partial(
                job_id=job_id, detail="cached PNG missing at dequeue"
            ))
            return

        n = len(chunks)
        chunks_printed = 0
        paper_total = 0
        # Per-chunk failure semantics (advisor-flagged correctness trap):
        # once any chunk has hit the printer, paper has been consumed and
        # the cutter has likely fired. A later chunk failing — for ANY
        # reason, including ``PrinterUnavailable`` (which is normally
        # retryable) — must NOT be retried, because rerunning the job
        # re-prints the already-printed chunks and the user gets duplicate
        # output. ``unknown_partial`` is the spec-correct terminal state.
        for i, png in enumerate(chunks):
            is_last = (i == n - 1)
            cut = (trailing_cut or auto_cut) if is_last else True
            feed = feed_lines_after if is_last else 0
            try:
                paper_total += await self._d.transport.print_png(
                    png, auto_cut=cut, feed_lines_after=feed,
                )
                chunks_printed += 1
            except OSError as exc:
                # I/O mid-stream: cable yanked, kernel pipe broken, USB
                # reset between bytes. We always classify as
                # ``unknown_partial`` — even on chunk 0 — because we cannot
                # know how much of that chunk was rasterized to paper.
                self._d.joblog.append(JobRecord.unknown_partial(
                    job_id=job_id,
                    detail=(
                        f"transport IOError on chunk {i}/{n}: {exc!r}; "
                        f"chunks_printed={chunks_printed}"
                    ),
                ))
                self._first_seen.pop(job_id, None)
                return
            except Exception as exc:
                if chunks_printed > 0:
                    # Cannot retry: earlier chunks already on paper and cut.
                    # A retry would duplicate them.
                    self._d.joblog.append(JobRecord.unknown_partial(
                        job_id=job_id,
                        detail=(
                            f"transport error on chunk {i}/{n} after "
                            f"{chunks_printed} chunks already printed: {exc!r}"
                        ),
                    ))
                    self._first_seen.pop(job_id, None)
                    return
                # First chunk failed, no paper consumed: retryable.
                now = time.time()
                first = self._first_seen.setdefault(job_id, now)
                if (now - first) > self._d.max_retry_age_s:
                    self._d.joblog.append(JobRecord.retry_timeout(job_id=job_id))
                    self._first_seen.pop(job_id, None)
                    return
                self._d.joblog.append(JobRecord.retry(
                    job_id=job_id, detail=str(exc)
                ))
                asyncio.create_task(self._reschedule(job_id))
                return

        # All chunks printed successfully.
        self._d.joblog.append(JobRecord.printed(
            job_id=job_id, paper_used_mm=paper_total
        ))
        self._first_seen.pop(job_id, None)

    async def _reschedule(self, job_id: str) -> None:
        await asyncio.sleep(self._d.retry_interval_s)
        if not self._stop.is_set():
            await self._q.put(job_id)


def options_from_replay(log: JobLog) -> dict[str, OptionsTuple]:
    """Reconstruct the in-memory options_store from the durable log so the
    worker honors per-job ``auto_cut``, ``feed_lines_after``,
    ``expires_at``, and ``trailing_cut`` after a crash/restart.

    Records predating the v0.5.2 schema have ``auto_cut=None``; for those we
    emit no entry so ``options_lookup`` falls back to the
    ``(True, 2, None, False)`` default. That matches pre-v0.5.2 restart
    behavior — the fix only helps newly-accepted jobs going forward, never
    silently rewrites old ones. Pre-v0.6.0 records have
    ``trailing_cut=None``; we treat that as False (the cut block was a 1-px
    marker, not a hardware cut).
    """
    out: dict[str, OptionsTuple] = {}
    for rec in log.pending_after_replay():
        if rec.auto_cut is None:
            continue
        out[rec.job_id] = (
            rec.auto_cut,
            rec.feed_lines_after if rec.feed_lines_after is not None else 2,
            rec.expires_at,
            bool(rec.trailing_cut),
        )
    return out
