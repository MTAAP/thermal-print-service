from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class HealthSnapshot:
    printer_connected: bool | None
    paper_present: bool | None
    cover_closed: bool | None
    clock_synchronized: bool
    queue_depth: int
    last_print_at: str | None
    last_error: str | None
    oldest_pending_age_s: int | None
    uptime_s: int


def _read_clock_synchronized() -> bool:
    try:
        out = subprocess.run(
            ["timedatectl", "show", "--property=NTPSynchronized", "--value"],
            capture_output=True, text=True, timeout=2,
        )
        return out.stdout.strip().lower() == "yes"
    except Exception:
        return False


class HealthCollector:
    def __init__(
        self,
        *,
        status_reader,
        queue_depth: Callable[[], int],
        last_print_at: Callable[[], str | None],
        process_started_at: float,
        clock_now: Callable[[], float],
        last_error: Callable[[], str | None] = lambda: None,
        oldest_pending_age_s: Callable[[], int | None] = lambda: None,
    ) -> None:
        self._sr = status_reader
        self._depth = queue_depth
        self._last_print_at = last_print_at
        self._started = process_started_at
        self._now = clock_now
        self._last_error = last_error
        self._oldest_pending_age_s = oldest_pending_age_s

    def snapshot(self) -> HealthSnapshot:
        s = self._sr.read()
        return HealthSnapshot(
            printer_connected=s.printer_connected,
            paper_present=s.paper_present,
            cover_closed=s.cover_closed,
            clock_synchronized=_read_clock_synchronized(),
            queue_depth=self._depth(),
            last_print_at=self._last_print_at(),
            last_error=self._last_error(),
            oldest_pending_age_s=self._oldest_pending_age_s(),
            uptime_s=int(self._now() - self._started),
        )
