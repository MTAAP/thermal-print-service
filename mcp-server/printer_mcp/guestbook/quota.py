"""Persisted send quotas for the guestbook.

Persisted, not in-memory, because the process restarts with its stack and an
in-memory window would hand every restart a fresh allowance. The file is the
only thing standing between an anonymous crowd and a roll of paper, so it is
written atomically and tolerates its own corruption by starting empty."""

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from pathlib import Path

logger = logging.getLogger("printer.guestbook")

_HOUR_S = 3600.0
_DAY_S = 24 * 3600.0


class QuotaExceeded(Exception):
    """Carries the guest-facing sentence, since the model relays it verbatim."""


def _coerce(raw: object) -> tuple[dict[str, list[float]], list[float]]:
    """Accept only the current shape; anything else starts empty.

    Validating here is what keeps a bad file from becoming a crash on every
    send. Forgetting a window costs at most one extra window of paper, while
    raising inside the tool costs the feature."""
    if not isinstance(raw, dict):
        raise ValueError(f"expected an object, got {type(raw).__name__}")
    guests_raw = raw.get("guests", {})
    total_raw = raw.get("total", [])
    if not isinstance(guests_raw, dict) or not isinstance(total_raw, list):
        raise ValueError("guests must be an object and total a list")
    guests: dict[str, list[float]] = {}
    for gid, stamps in guests_raw.items():
        if not isinstance(gid, str) or not isinstance(stamps, list):
            raise ValueError(f"guest {gid!r} maps to {type(stamps).__name__}, expected list")
        guests[gid] = [float(t) for t in stamps if isinstance(t, (int, float))]
    total = [float(t) for t in total_raw if isinstance(t, (int, float))]
    return guests, total


class QuotaStore:
    def __init__(self, path: Path, *, per_guest_per_hour: int, global_per_hour: int,
                 global_per_day: int) -> None:
        self._path = path
        self._per_guest_per_hour = per_guest_per_hour
        self._global_per_hour = global_per_hour
        self._global_per_day = global_per_day
        self._guests: dict[str, list[float]] = {}
        self._total: list[float] = []
        if path.exists():
            try:
                self._guests, self._total = _coerce(json.loads(path.read_text()))
            except (json.JSONDecodeError, OSError, TypeError, ValueError) as exc:
                logger.warning("guestbook: quota file unusable (%s); starting empty", exc)

    def _flush(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(self._path.parent),
                                   prefix=self._path.name, suffix=".tmp")
        with os.fdopen(fd, "wb") as f:
            f.write(json.dumps({"guests": self._guests, "total": self._total},
                               sort_keys=True).encode())
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self._path)

    def _prune(self, now: float) -> None:
        # Drop guests whose window has emptied so the file stays proportional to
        # recent activity rather than to every session that ever said hello.
        self._guests = {
            gid: live
            for gid, stamps in self._guests.items()
            if (live := [t for t in stamps if t > now - _HOUR_S])
        }
        self._total = [t for t in self._total if t > now - _DAY_S]

    def check_and_record(self, guest_id: str, *, now: float | None = None) -> None:
        """Consume one slot, or raise QuotaExceeded without consuming anything."""
        now = time.time() if now is None else now
        self._prune(now)
        if len(self._total) >= self._global_per_day:
            raise QuotaExceeded(
                "The printer has taken all the messages it can hold for today. "
                "Tell the guest to try again tomorrow."
            )
        # An hourly total as well as a daily one, because the recipient's relay
        # enforces its own per-sender hourly ceiling and rejects silently: the
        # hub answers "queued" before the relay ever sees the job, so a guest
        # who trips that ceiling is told the note was sent and no paper appears.
        # Staying under it keeps the refusal here, where the guest is told.
        if len([t for t in self._total if t > now - _HOUR_S]) >= self._global_per_hour:
            raise QuotaExceeded(
                "The printer has had a lot of messages this hour and is taking a "
                "break. Tell the guest to try again a bit later."
            )
        if len(self._guests.get(guest_id, [])) >= self._per_guest_per_hour:
            raise QuotaExceeded(
                f"This guest has already sent {self._per_guest_per_hour} messages "
                "in the last hour. Tell them to give it an hour before sending more."
            )
        self._guests.setdefault(guest_id, []).append(now)
        self._total.append(now)
        self._flush()

    def snapshot(self, *, now: float | None = None) -> dict[str, int]:
        """Counts for the audit log. Does not mutate the persisted window."""
        now = time.time() if now is None else now
        return {
            "sent_this_hour": len([t for t in self._total if t > now - _HOUR_S]),
            "global_per_hour": self._global_per_hour,
            "sent_today": len([t for t in self._total if t > now - _DAY_S]),
            "global_per_day": self._global_per_day,
        }
