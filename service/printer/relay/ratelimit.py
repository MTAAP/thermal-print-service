from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path


def _epoch(sent_at: str) -> float:
    ts = sent_at[:-1] + "+00:00" if sent_at.endswith("Z") else sent_at
    return datetime.fromisoformat(ts).timestamp()


class PerFriendRateLimiter:
    """Sliding-window N/hour/friend, evaluated against the job's immutable
    sent_at (spec 7.1). Using sent_at (not wall-clock) keeps the decision
    deterministic on redelivery: the same job is allowed/denied identically."""

    def __init__(self, path: Path, *, per_hour: int) -> None:
        self._path = path
        self._per_hour = per_hour
        self._hits: dict[str, list[float]] = {}
        if path.exists():
            self._hits = json.loads(path.read_text())

    def _flush(self) -> None:
        fd, tmp = tempfile.mkstemp(dir=str(self._path.parent),
                                   prefix=self._path.name, suffix=".tmp")
        with os.fdopen(fd, "wb") as f:
            f.write(json.dumps(self._hits, sort_keys=True).encode())
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self._path)

    def check_and_record(self, handle: str, sent_at: str) -> bool:
        now = _epoch(sent_at)
        cutoff = now - 3600.0
        window = [t for t in self._hits.get(handle, []) if t > cutoff]
        # Idempotent by sent_at: a single job occupies at most one window slot no
        # matter how many times it is redelivered. sent_at is the hub's immutable,
        # microsecond-precision timestamp (not sender-controlled), so within one
        # sender bucket an exact match means the SAME job is being re-evaluated --
        # e.g. a QUEUE_FULL outcome left it leased and the hub redelivered it.
        # Counting that twice would let an unprinted, retrying job eventually trip
        # its own limit and become rejected_rate_limited. This is what the class
        # docstring's "same job allowed/denied identically" guarantee requires.
        # Bound: two GENUINELY distinct jobs could share a sent_at only via a
        # duplicate-recipient send (to=["bob","bob"]) reaching one relay; deduping
        # that to a single slot is a negligible (and arguably correct) under-count.
        if now in window:
            self._hits[handle] = window
            self._flush()
            return True
        if len(window) >= self._per_hour:
            self._hits[handle] = window
            self._flush()
            return False
        window.append(now)
        self._hits[handle] = window
        self._flush()
        return True
