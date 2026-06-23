from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("printer.relay")


def _epoch(sent_at: str) -> float:
    ts = sent_at[:-1] + "+00:00" if sent_at.endswith("Z") else sent_at
    return datetime.fromisoformat(ts).timestamp()


class PerFriendRateLimiter:
    """Sliding-window N/hour/friend, evaluated against the job's immutable
    sent_at (spec 7.1). Using sent_at (not wall-clock) keeps the decision
    deterministic on redelivery: the same job is allowed/denied identically.

    The window is keyed on hub_job_id, NOT sent_at: the hub stamps ONE sent_at
    for every recipient of a /send, so to=['bob','bob'] (or any two distinct
    jobs that happen to share a microsecond) would otherwise collapse into a
    single slot and let N distinct prints through one window slot. Recording
    hub_job_id makes a redelivery (same hub_job_id) free while still counting
    two genuinely distinct jobs that share a sent_at.

    The decision (allow) is split from the durable commit (record_accepted) so a
    slot is only burned once a job is durably ACCEPTED locally -- a deterministic
    non-accept (malformed payload, INCOMPATIBLE, TOO_LARGE) never consumes a slot
    a misbehaving sender could use to exhaust its own quota."""

    def __init__(self, path: Path, *, per_hour: int) -> None:
        self._path = path
        self._per_hour = per_hour
        # handle -> {hub_job_id: sent_at_epoch}. Persisted so the dedup memory
        # survives restart: replay re-evaluates jobs and must not re-count an
        # already-recorded hub_job_id.
        self._hits: dict[str, dict[str, float]] = {}
        if path.exists():
            try:
                self._hits = json.loads(path.read_text())
            except (json.JSONDecodeError, OSError, TypeError) as exc:
                # A power cut mid-write on a Pi Zero can leave a torn rate.json.
                # An empty window is self-healing (it just forgets recent hits),
                # so fall back to empty rather than crash RelayClient.__init__ and
                # let systemd crash-loop the relay until hand-repaired. Mirrors
                # JobMap's bad-line tolerance.
                logger.warning("relay: rate.json unreadable (%s); starting with empty window", exc)
                self._hits = {}

    def _flush(self) -> None:
        fd, tmp = tempfile.mkstemp(dir=str(self._path.parent),
                                   prefix=self._path.name, suffix=".tmp")
        with os.fdopen(fd, "wb") as f:
            f.write(json.dumps(self._hits, sort_keys=True).encode())
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self._path)

    def _prune(self, handle: str, cutoff: float) -> dict[str, float]:
        return {
            jid: ts for jid, ts in self._hits.get(handle, {}).items() if ts > cutoff
        }

    def allow(self, handle: str, hub_job_id: str, sent_at: str) -> bool:
        """Decide whether this job may proceed, WITHOUT durably consuming a slot.

        Idempotent on hub_job_id: a redelivery of an already-recorded job (e.g. a
        QUEUE_FULL outcome left it leased and the hub redelivered it) is always
        allowed and never counts twice -- counting it twice would let an unprinted,
        retrying job eventually trip its own limit and become rejected_rate_limited.
        The commit of a fresh slot is deferred to record_accepted (called only on a
        durable local ACCEPT), so a deterministic non-accept never burns a slot."""
        now = _epoch(sent_at)
        cutoff = now - 3600.0
        window = self._prune(handle, cutoff)
        if hub_job_id in window:
            return True  # already recorded this exact job -> redelivery, free
        return len(window) < self._per_hour

    def record_accepted(self, handle: str, hub_job_id: str, sent_at: str) -> None:
        """Durably consume a window slot for a job that ACCEPTED locally. Idempotent
        on hub_job_id so a redelivery that re-accepts does not double-count."""
        now = _epoch(sent_at)
        cutoff = now - 3600.0
        window = self._prune(handle, cutoff)
        window[hub_job_id] = now
        # Re-prune EVERY handle against this cutoff and drop any that empty out, so
        # the file stays proportional to currently-active friends rather than
        # accumulating a permanent key per sender ever seen. The just-recorded
        # handle keeps its live entry. (Sent_at is hub-monotonic enough that a
        # shared cutoff is a safe over-keep, never an under-keep, of live slots.)
        pruned = {h: self._prune(h, cutoff) for h in self._hits}
        pruned[handle] = window
        self._hits = {h: w for h, w in pruned.items() if w}
        self._flush()
