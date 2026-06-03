from __future__ import annotations

import asyncio


class WakeupRegistry:
    """One asyncio.Event per recipient printer. A /send sets it; a held
    /inbox waits on it. v1 single-instance only; the Postgres LISTEN/NOTIFY
    scale path (spec §8.4) replaces this without touching callers."""

    def __init__(self) -> None:
        self._events: dict[str, asyncio.Event] = {}

    def _event(self, printer_id: str) -> asyncio.Event:
        ev = self._events.get(printer_id)
        if ev is None:
            ev = asyncio.Event()
            self._events[printer_id] = ev
        return ev

    def signal(self, printer_id: str) -> None:
        self._event(printer_id).set()

    async def wait(self, printer_id: str, timeout: float) -> bool:
        ev = self._event(printer_id)
        try:
            await asyncio.wait_for(ev.wait(), timeout=timeout)
            return True
        except TimeoutError:
            return False
        finally:
            ev.clear()
