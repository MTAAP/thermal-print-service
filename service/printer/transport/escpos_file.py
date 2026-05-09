from __future__ import annotations

from pathlib import Path

from escpos.printer import File
from PIL import Image


class FilePrinter:
    """python-escpos File backend wrapper.

    The ``File`` backend is write-only. Status reads are not available;
    /healthz returns ``None`` for printer/paper/cover states. To get
    bidirectional status, switch to the Usb backend (requires unloading
    the kernel ``usblp`` module via udev rule); deferred to Phase 6.
    """

    def __init__(self, device: str | Path) -> None:
        self._device = str(device)
        self._p = File(self._device, auto_flush=True)
        self._p.hw("INIT")  # send ESC @ to reset printer to known state

    def print_image(
        self,
        image: Image.Image,
        *,
        auto_cut: bool = True,
        feed_lines_after: int = 2,
    ) -> None:
        if image.mode != "1":
            image = image.convert("1")
        if image.width != 576:
            raise ValueError(f"image must be 576 px wide, got {image.width}")
        # python-escpos handles raster transfer (GS v 0) for 1-bit images
        self._p.image(image, impl="bitImageRaster")
        if feed_lines_after:
            self._p.ln(feed_lines_after)
        if auto_cut:
            self._p.cut(mode="PART")  # partial cut

    def close(self) -> None:
        self._p.close()
