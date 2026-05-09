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
    ) -> None:
        self._sr = status_reader
        self._depth = queue_depth
        self._last_print_at = last_print_at
        self._started = process_started_at
        self._now = clock_now

    def snapshot(self) -> HealthSnapshot:
        s = self._sr.read()
        return HealthSnapshot(
            printer_connected=s.printer_connected,
            paper_present=s.paper_present,
            cover_closed=s.cover_closed,
            clock_synchronized=_read_clock_synchronized(),
            queue_depth=self._depth(),
            last_print_at=self._last_print_at(),
            uptime_s=int(self._now() - self._started),
        )
