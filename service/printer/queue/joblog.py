from __future__ import annotations

import json
import os
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


JobEvent = Literal[
    "accepted",
    "printing",
    "printed",
    "retry",
    "retry_timeout",
    "expired",
    "unknown_partial",
]


@dataclass(frozen=True)
class JobRecord:
    event: JobEvent
    job_id: str
    ts: str
    sender: str | None = None
    document_type: str | None = None
    idempotency_key: str | None = None
    payload_hash: str | None = None
    kind: Literal["document", "raw"] | None = None
    estimated_paper_mm: int | None = None
    renderer_version: str | None = None
    paper_used_mm: int | None = None
    detail: str | None = None  # human-readable on retry/expired/etc.
    # Per-job print options. Persisted on ``accepted`` so that a crash/restart
    # can rebuild the in-memory ``options_store`` and continue to honor
    # ``auto_cut=False``, custom ``feed_lines_after``, and ``expires_at`` for
    # jobs queued before the restart. Pre-v0.5.2 records have these set to
    # None; the recovery helper skips them and the worker falls back to the
    # ``(True, 2, None)`` default, matching pre-fix behavior.
    auto_cut: bool | None = None
    feed_lines_after: int | None = None
    expires_at: str | None = None  # ISO 8601, may be naive (worker normalizes)
    # Multi-chunk metadata (v0.6.0). ``chunk_count`` is the number of PNGs
    # cached under the chunked layout (``<job>__<i>.png``). ``trailing_cut``
    # is True when the document had at least one ``cut`` block with no
    # printable content after it; the worker forces ``auto_cut=True`` on
    # the final chunk in that case, even if ``options.auto_cut`` is False.
    # Pre-v0.6.0 records leave both at ``None``; the worker treats absent
    # ``chunk_count`` as 1 and absent ``trailing_cut`` as False.
    chunk_count: int | None = None
    trailing_cut: bool | None = None

    @classmethod
    def accepted(cls, *, job_id: str, sender: str | None, document_type: str | None,
                 idempotency_key: str | None, payload_hash: str, kind: str,
                 estimated_paper_mm: int, renderer_version: str,
                 auto_cut: bool = True, feed_lines_after: int = 2,
                 expires_at: str | None = None,
                 chunk_count: int = 1, trailing_cut: bool = False) -> JobRecord:
        return cls(event="accepted", job_id=job_id, ts=_now(), sender=sender,
                   document_type=document_type, idempotency_key=idempotency_key,
                   payload_hash=payload_hash, kind=kind,
                   estimated_paper_mm=estimated_paper_mm,
                   renderer_version=renderer_version,
                   auto_cut=auto_cut, feed_lines_after=feed_lines_after,
                   expires_at=expires_at,
                   chunk_count=chunk_count, trailing_cut=trailing_cut)

    @classmethod
    def printing(cls, *, job_id: str) -> JobRecord:
        return cls(event="printing", job_id=job_id, ts=_now())

    @classmethod
    def printed(cls, *, job_id: str, paper_used_mm: int) -> JobRecord:
        return cls(event="printed", job_id=job_id, ts=_now(),
                   paper_used_mm=paper_used_mm)

    @classmethod
    def retry(cls, *, job_id: str, detail: str) -> JobRecord:
        return cls(event="retry", job_id=job_id, ts=_now(), detail=detail)

    @classmethod
    def retry_timeout(cls, *, job_id: str) -> JobRecord:
        return cls(event="retry_timeout", job_id=job_id, ts=_now())

    @classmethod
    def expired(cls, *, job_id: str, detail: str) -> JobRecord:
        return cls(event="expired", job_id=job_id, ts=_now(), detail=detail)

    @classmethod
    def unknown_partial(cls, *, job_id: str, detail: str) -> JobRecord:
        return cls(event="unknown_partial", job_id=job_id, ts=_now(), detail=detail)


_TERMINAL: set[str] = {"printed", "expired", "retry_timeout", "unknown_partial"}


class JobLog:
    """Append-only JSONL log. The single durability seam."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.touch(exist_ok=True)

    @staticmethod
    def _serialize(record: JobRecord) -> str:
        return json.dumps({k: v for k, v in asdict(record).items() if v is not None})

    def append(self, record: JobRecord) -> None:
        line = self._serialize(record)
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
            f.flush()
            os.fsync(f.fileno())

    def replay(self) -> Iterator[JobRecord]:
        with open(self._path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    yield JobRecord(**obj)
                except (json.JSONDecodeError, TypeError):
                    continue

    def pending_after_replay(self) -> list[JobRecord]:
        """Return one ``accepted`` record per still-pending job, in arrival order."""
        accepted: dict[str, JobRecord] = {}
        order: list[str] = []
        terminated: set[str] = set()
        for r in self.replay():
            if r.event == "accepted":
                if r.job_id not in accepted:
                    order.append(r.job_id)
                accepted[r.job_id] = r
            elif r.event in _TERMINAL:
                terminated.add(r.job_id)
        return [accepted[jid] for jid in order
                if jid in accepted and jid not in terminated]

    def prune(self, *, max_records: int, max_bytes: int) -> None:
        """Drop records for the oldest terminal jobs until under both limits.

        Currently-pending jobs (``accepted`` with no terminal event) are
        never dropped — replay must still re-enqueue them, otherwise their
        PNG cache rots and they vanish silently. If the log can't be
        brought under the limits without dropping pending jobs, the
        breach is accepted and the log is left at its current size.

        Atomic: the rewrite goes to a sibling tmp file and is then renamed,
        so a crash mid-prune leaves the original log untouched.
        """
        try:
            size = self._path.stat().st_size
        except FileNotFoundError:
            return
        records = list(self.replay())
        if len(records) <= max_records and size <= max_bytes:
            return

        pending_ids = {r.job_id for r in self.pending_after_replay()}
        by_job: dict[str, list[JobRecord]] = {}
        for r in records:
            by_job.setdefault(r.job_id, []).append(r)

        # Drop oldest terminal jobs first — sorted by the timestamp of the
        # job's most recent event so a long-failed job goes before a job
        # that was accepted earlier but completed yesterday.
        terminal_jobs = sorted(
            (jid for jid in by_job if jid not in pending_ids),
            key=lambda jid: by_job[jid][-1].ts,
        )
        keep_ids = set(by_job)

        def kept_count() -> int:
            return sum(len(by_job[jid]) for jid in keep_ids)

        def kept_bytes() -> int:
            return sum(
                len(self._serialize(r).encode("utf-8")) + 1
                for jid in keep_ids for r in by_job[jid]
            )

        while terminal_jobs:
            if kept_count() <= max_records and kept_bytes() <= max_bytes:
                break
            keep_ids.discard(terminal_jobs.pop(0))

        # If everything left is pending, there's nothing to drop — bail
        # without rewriting so we don't churn the file for no reason.
        kept_records = [r for r in records if r.job_id in keep_ids]
        if len(kept_records) == len(records):
            return

        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            for r in kept_records:
                f.write(self._serialize(r) + "\n")
            f.flush()
            os.fsync(f.fileno())
        tmp.replace(self._path)
