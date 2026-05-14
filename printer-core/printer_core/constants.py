"""Pixel and physical constants for the thermal print stack.

DPMM is pinned from physical caliper measurement of a printed
calibration ruler. Nothing in the renderer depends on a specific
DPI — only mm conversions do (estimated_paper_mm, paper_used_mm,
max_length_mm enforcement).
"""

PRINT_HEAD_WIDTH_PX: int = 576
GUTTER_PX: int = 24
LIVE_WIDTH_PX: int = PRINT_HEAD_WIDTH_PX - 2 * GUTTER_PX  # = 528

DPMM_PLACEHOLDER: float = 180.0 / 25.4   # ~7.0866
# Pinned 2026-05-09. Caliper measurement on the NetumScan: 800 px = 99.9 mm
# (8.008 dpmm = 203.4 DPI). Rounded to a clean 8.0 dpmm.
DPMM_CALIBRATED: float = 8.0
DPMM: float = DPMM_CALIBRATED

MAX_LENGTH_MM_DEFAULT: int = 2000
FEED_LINES_AFTER_DEFAULT: int = 2


def mm_to_px(mm: float) -> int:
    return round(mm * DPMM)


def px_to_mm(px: int) -> float:
    return px / DPMM
