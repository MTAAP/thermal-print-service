from __future__ import annotations


class Presence:
    """Reference-counted online presence for printers.

    A printer is "online" while >=1 of its /inbox polls is active. Overlapping
    polls happen normally -- a relay restart leaves the old held poll parked while
    the new process starts polling, or a Pi briefly runs two pollers. A plain set
    with add-on-entry / discard-on-exit would let the FIRST poll to finish drop
    presence even though a later poll is still holding /inbox, flickering the
    Friends view to "offline". Ref-counting fixes that: presence only clears when
    the LAST active poll for a printer releases.

    Single-event-loop only (v1, spec §8.3/§8.4): increments/decrements are not
    guarded by a lock because there is no await between read and write here, so a
    single asyncio loop never interleaves them.
    """

    def __init__(self) -> None:
        self._counts: dict[str, int] = {}

    def add(self, printer_id: str) -> None:
        self._counts[printer_id] = self._counts.get(printer_id, 0) + 1

    def release(self, printer_id: str) -> None:
        n = self._counts.get(printer_id, 0) - 1
        if n <= 0:
            # Drop the key entirely at zero so the map does not grow without bound
            # as printers come and go.
            self._counts.pop(printer_id, None)
        else:
            self._counts[printer_id] = n

    def __contains__(self, printer_id: object) -> bool:
        return self._counts.get(printer_id, 0) > 0 if isinstance(printer_id, str) else False
