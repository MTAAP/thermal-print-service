"""Ink-coverage metric for 1-bit thermal rasters.

Single source of truth for every caller that reasons about how much black a
page lays down: the design-side lint passes (pre-render emptiness heuristic,
post-render ink-ratio check) and the compile trim step. Lives here next to the
dither pipeline so the design and (future) service callers share one
implementation rather than each carrying a private copy.
"""

from __future__ import annotations

from PIL import Image


def ink_ratio(img: Image.Image) -> float:
    """Fraction of black (ink) pixels in a raster, in ``[0.0, 1.0]``.

    Converts to mode ``"1"`` first, so grayscale or RGB input is accepted.
    An empty image returns ``0.0``.
    """
    if img.mode != "1":
        img = img.convert("1")
    total = img.width * img.height
    if total == 0:
        return 0.0
    # mode "1" pixels are 0 or 255 -- count black (0) as ink.
    # Pillow stubs mark getdata() as non-iterable, but it iterates fine at
    # runtime; see dither.py for the same `# type: ignore` workaround pattern.
    black = sum(1 for v in img.getdata() if v == 0)  # type: ignore[attr-defined,misc]
    return black / total
