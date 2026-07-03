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


# (auto_cut, feed_lines_after, expires_at_iso_or_none, not_before_iso_or_none,
# trailing_cut)
# ``trailing_cut`` is the per-job flag set by the renderer when the doc
# ended with a ``cut`` block; it forces ``auto_cut=True`` on the final
# chunk even if ``options.auto_cut`` is False.
OptionsTuple = tuple[bool, int, str | None, str | None, bool]
LegacyOptionsTuple = tuple[bool, int, str | None, bool]
OptionsLookup = Callable[[str], OptionsTuple | LegacyOptionsTuple]


# Single source of truth for the worker fallback. Pre-v0.5.2 records are
# skipped by ``options_from_replay`` (their ``auto_cut`` is None), so the
# lookup falls back to this default. The shape MUST match the normalized
# unpack in ``_handle``; drift here can leave the job stuck behind retries.
DEFAULT_OPTIONS: OptionsTuple = (True, 2, None, None, False)

_STOP = "__STOP__"
_WAKE = "__WAKE__"
_CLOCK_UNSYNC_HOLD_POLL_S = 60.0


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


def _normalize_options(opts: OptionsTuple | LegacyOptionsTuple) -> OptionsTuple:
    if len(opts) == 4:
        auto_cut, feed_lines_after, expires_at_iso, trailing_cut = opts
        return auto_cut, feed_lines_after, expires_at_iso, None, trailing_cut
    return opts


def _retry_anchor_timestamp(enqueued_at_iso: str, not_before_iso: str | None) -> float:
    try:
        anchor = _parse_iso(enqueued_at_iso).timestamp()
    except (ValueError, TypeError):
        anchor = time.time()
    if not_before_iso is None:
        return anchor
    try:
        return max(anchor, _parse_iso(not_before_iso).timestamp())
    except (ValueError, TypeError):
        return anchor


class PrintWorker:
    """Single worker draining pending jobs FIFO among eligible records.

    Replay on start: every still-pending job from the durable log is
    re-enqueued in arrival order. New POSTs append to the durable log
    (via the HTTP layer) AND call ``enqueue``. The queue is just a wakeup.
    """

    def __init__(self, deps: WorkerDeps, *, options_lookup: OptionsLookup) -> None:
        self._d = deps
        self._opts = options_lookup
        self._q: asyncio.Queue[str] = asyncio.Queue()
        self._task: asyncio.Task | None = None
        self._hold_wakeup: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._first_seen: dict[str, float] = {}
        self._retry_after: dict[str, float] = {}

    async def start(self) -> None:
        for rec in self._d.joblog.pending_after_replay():
            # Seed ``_first_seen`` from the durable accepted timestamp, but
            # anchor scheduled jobs at eligibility so a future ``not_before``
            # does not burn retry budget before the job can print.
            self._first_seen[rec.job_id] = _retry_anchor_timestamp(
                rec.ts, rec.not_before
            )
            await self._q.put(rec.job_id)
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._stop.set()
        self._cancel_hold_wakeup()
        if self._task is not None:
            await self._q.put(_STOP)
            await self._task

    async def enqueue(self, job_id: str) -> None:
        _, _, _, not_before_iso, _ = _normalize_options(self._opts(job_id))
        if job_id not in self._first_seen:
            enqueued_at = datetime.fromtimestamp(time.time(), UTC).isoformat()
            self._first_seen[job_id] = _retry_anchor_timestamp(
                enqueued_at, not_before_iso
            )
        await self._q.put(job_id)

    async def _run(self) -> None:
        while not self._stop.is_set():
            wake = await self._q.get()
            if wake == _STOP:
                return
            selected, wakeup_s = self._select_next_eligible()
            if selected is None:
                self._schedule_hold_wakeup(wakeup_s)
                continue
            self._cancel_hold_wakeup()
            try:
                completed = await self._handle(selected)
            except Exception as exc:
                self._d.joblog.append(JobRecord.retry(
                    job_id=selected, detail=f"unexpected: {exc!r}"
                ))
                completed = False
            if completed:
                next_job, next_wakeup_s = self._select_next_eligible()
                if next_job is not None:
                    await self._q.put(_WAKE)
                else:
                    self._schedule_hold_wakeup(next_wakeup_s)

    def is_held(self, job_id: str) -> bool:
        _, _, _, not_before_iso, _ = _normalize_options(self._opts(job_id))
        held, _ = self._hold_state(not_before_iso)
        return held

    def _select_next_eligible(self) -> tuple[str | None, float | None]:
        earliest_wakeup_s: float | None = None
        for rec in self._d.joblog.pending_after_replay():
            retry_wakeup_s = self._retry_wakeup_delay(rec.job_id)
            if retry_wakeup_s is not None:
                if earliest_wakeup_s is None:
                    earliest_wakeup_s = retry_wakeup_s
                else:
                    earliest_wakeup_s = min(earliest_wakeup_s, retry_wakeup_s)
                continue
            _, _, _, not_before_iso, _ = _normalize_options(self._opts(rec.job_id))
            held, wakeup_s = self._hold_state(not_before_iso)
            if not held:
                # FIFO among eligible jobs: held jobs are skipped here so
                # later eligible work can print without waiting for them.
                return rec.job_id, None
            if wakeup_s is not None:
                if earliest_wakeup_s is None:
                    earliest_wakeup_s = wakeup_s
                else:
                    earliest_wakeup_s = min(earliest_wakeup_s, wakeup_s)
        return None, earliest_wakeup_s

    def _retry_wakeup_delay(self, job_id: str) -> float | None:
        retry_after = self._retry_after.get(job_id)
        if retry_after is None:
            return None
        delay_s = retry_after - time.time()
        if delay_s <= 0:
            self._retry_after.pop(job_id, None)
            return None
        return delay_s

    def _hold_state(self, not_before_iso: str | None) -> tuple[bool, float | None]:
        if not not_before_iso:
            return False, None
        if not self._d.clock_ok():
            return True, min(self._d.retry_interval_s, _CLOCK_UNSYNC_HOLD_POLL_S)
        try:
            not_before = _parse_iso(not_before_iso)
        except (ValueError, TypeError):
            return False, None
        delay_s = (not_before - _now_utc()).total_seconds()
        if delay_s > 0:
            return True, delay_s
        return False, None

    def _schedule_hold_wakeup(self, delay_s: float | None) -> None:
        self._cancel_hold_wakeup()
        if delay_s is None or self._stop.is_set():
            return
        self._hold_wakeup = asyncio.create_task(self._wake_after(delay_s))

    def _cancel_hold_wakeup(self) -> None:
        if self._hold_wakeup is not None and not self._hold_wakeup.done():
            self._hold_wakeup.cancel()
        self._hold_wakeup = None

    async def _wake_after(self, delay_s: float) -> None:
        try:
            await asyncio.sleep(max(0.0, delay_s))
            if not self._stop.is_set():
                await self._q.put(_WAKE)
        except asyncio.CancelledError:
            return

    async def _handle(self, job_id: str) -> bool:
        auto_cut, feed_lines_after, expires_at_iso, _, trailing_cut = (
            _normalize_options(self._opts(job_id))
        )

        if expires_at_iso and self._d.clock_ok():
            try:
                if _now_utc() > _parse_iso(expires_at_iso):
                    self._d.joblog.append(JobRecord.expired(
                        job_id=job_id, detail=f"past expires_at={expires_at_iso}"
                    ))
                    self._retry_after.pop(job_id, None)
                    return True
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
            self._retry_after.pop(job_id, None)
            return True

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
                self._retry_after.pop(job_id, None)
                return True
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
                    self._retry_after.pop(job_id, None)
                    return True
                # First chunk failed, no paper consumed: retryable.
                now = time.time()
                first = self._first_seen.setdefault(job_id, now)
                if (now - first) > self._d.max_retry_age_s:
                    self._d.joblog.append(JobRecord.retry_timeout(job_id=job_id))
                    self._first_seen.pop(job_id, None)
                    self._retry_after.pop(job_id, None)
                    return True
                self._d.joblog.append(JobRecord.retry(
                    job_id=job_id, detail=str(exc)
                ))
                self._retry_after[job_id] = now + self._d.retry_interval_s
                asyncio.create_task(self._reschedule(job_id))
                return False

        # All chunks printed successfully.
        self._d.joblog.append(JobRecord.printed(
            job_id=job_id, paper_used_mm=paper_total
        ))
        self._first_seen.pop(job_id, None)
        self._retry_after.pop(job_id, None)
        return True

    async def _reschedule(self, job_id: str) -> None:
        await asyncio.sleep(self._d.retry_interval_s)
        if not self._stop.is_set():
            await self._q.put(job_id)


def options_from_replay(log: JobLog) -> dict[str, OptionsTuple]:
    """Reconstruct the in-memory options_store from the durable log so the
    worker honors per-job ``auto_cut``, ``feed_lines_after``,
    ``expires_at``, ``not_before``, and ``trailing_cut`` after a crash/restart.

    Records predating the v0.5.2 schema have ``auto_cut=None``; for those we
    emit no entry so ``options_lookup`` falls back to the
    default options. That matches pre-v0.5.2 restart
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
            rec.not_before,
            bool(rec.trailing_cut),
        )
    return out
