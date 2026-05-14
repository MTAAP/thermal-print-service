"""Pixel and physical constants — re-exported from printer_core.

The single source of truth lives in ``printer_core.constants``. This shim
keeps existing imports inside ``printer.*`` working unchanged.
"""
from printer_core.constants import (  # noqa: F401
    DPMM,
    DPMM_CALIBRATED,
    DPMM_PLACEHOLDER,
    FEED_LINES_AFTER_DEFAULT,
    GUTTER_PX,
    LIVE_WIDTH_PX,
    MAX_LENGTH_MM_DEFAULT,
    PRINT_HEAD_WIDTH_PX,
    mm_to_px,
    px_to_mm,
)
