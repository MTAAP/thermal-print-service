from __future__ import annotations

import asyncio
import io

from escpos.exceptions import Error as EscposError
from PIL import Image

from printer.constants import px_to_mm
from printer.transport import PrinterUnavailable
from printer.transport.escpos_file import FilePrinter


class FilePrinterAdapter:
    """Async wrapper. python-escpos is sync; we offload to a thread.

    The single asyncio lock serializes prints — the printer is one physical
    resource and the worker already enforces FIFO, but the adapter holds the
    lock as a defensive layer in case something else ever calls it.

    Failure classification (spec §11):
    - Device cannot be opened (printer unplugged, missing /dev node, perms) →
      raise ``PrinterUnavailable``. No bytes were sent; the worker's generic
      Exception branch retries every ``retry_interval_s``.
    - I/O error during ``print_image`` (cable yanked mid-stream, kernel pipe
      broken, USB reset between bytes) → propagate IOError as-is. The worker
      maps IOError to ``unknown_partial`` because we cannot know how much
      paper was consumed; the spec is explicit that auto-retry would risk
      duplicate output.
    """

    def __init__(self, device: str) -> None:
        self._device = device
        self._lock = asyncio.Lock()

    async def print_png(self, png: bytes, *, auto_cut: bool, feed_lines_after: int) -> int:
        async with self._lock:
            def _do() -> int:
                img = Image.open(io.BytesIO(png))
                img.load()
                # Open + INIT happens inside FilePrinter.__init__. ESC @ is a
                # control sequence (no paper consumed); if it fails the printer
                # is offline, not "started printing" — surface as
                # PrinterUnavailable so the worker retries.
                # python-escpos wraps OSError as its own DeviceNotFoundError
                # (subclass of escpos.exceptions.Error, not OSError) — catch
                # both branches.
                try:
                    p = FilePrinter(self._device)
                except (OSError, EscposError) as exc:
                    raise PrinterUnavailable(
                        f"failed to open {self._device}: {exc}"
                    ) from exc
                try:
                    p.print_image(img, auto_cut=auto_cut, feed_lines_after=feed_lines_after)
                finally:
                    p.close()
                return int(px_to_mm(img.height))
            return await asyncio.to_thread(_do)
