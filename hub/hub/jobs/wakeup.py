from __future__ import annotations

import asyncio


class WakeupRegistry:
    """Cross-poll wakeup for held /inbox long-polls. A /send signals the
    recipient; a held /inbox waits to be signalled. v1 single-instance only; the
    Postgres LISTEN/NOTIFY scale path (spec §8.4) replaces this without touching
    callers.

    Lost-wakeup-free by design. Each waiter registers a FRESH Future under the
    printer_id; signal() pops every Future for that printer and resolves it. A
    Future is owned by exactly one waiter and is never cleared by another, so the
    shared-Event hazard is gone: with overlapping polls for one printer (a relay
    restart leaves the old /inbox parked while the new process polls), one
    waiter finishing can no longer clear a flag and swallow a concurrent signal,
    which previously stranded a queued job for up to long_poll_wait_s.

    signal() is synchronous and lock-free (Future.set_result needs no lock), so a
    /send can wake held polls inline after its commit without awaiting.
    """

    def __init__(self) -> None:
        # printer_id -> the set of Futures for its currently-held waiters.
        self._waiters: dict[str, set[asyncio.Future[None]]] = {}

    def signal(self, printer_id: str) -> None:
        # Pop the whole waiter set so a Future is resolved exactly once even if a
        # second signal races in; late-arriving waiters register a fresh set.
        for fut in self._waiters.pop(printer_id, set()):
            if not fut.done():
                fut.set_result(None)

    async def wait(self, printer_id: str, timeout: float) -> bool:
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[None] = loop.create_future()
        self._waiters.setdefault(printer_id, set()).add(fut)
        try:
            await asyncio.wait_for(fut, timeout=timeout)
            return True
        except TimeoutError:
            # Timeout is a normal long-poll outcome, never an error to callers.
            return False
        finally:
            # Drop our own Future. On the signal path it was already popped with
            # the whole set; on timeout/cancel we remove just ours and tidy the
            # empty bucket so the map does not grow without bound.
            bucket = self._waiters.get(printer_id)
            if bucket is not None:
                bucket.discard(fut)
                if not bucket:
                    self._waiters.pop(printer_id, None)
