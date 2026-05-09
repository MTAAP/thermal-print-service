from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StatusSnapshot:
    printer_connected: bool | None
    paper_present: bool | None
    cover_closed: bool | None


class StatusReader:
    """Single source of truth for printer status capability.

    The File-backed transport is write-only — every signal is None.
    A future Usb-backed transport (Phase 6 if needed) can fill these
    by reading DLE EOT 1..4. The reader holds a capability flag rather
    than a transport handle so it composes with any backend.
    """

    def __init__(
        self,
        *,
        supports_status: bool,
        _stub_online: bool | None = None,
    ) -> None:
        self._supports = supports_status
        self._stub_online = _stub_online  # tests only

    def read(self) -> StatusSnapshot:
        if not self._supports:
            return StatusSnapshot(None, None, None)
        # Real implementation lives next to the Usb-backed transport.
        return StatusSnapshot(self._stub_online, None, None)
