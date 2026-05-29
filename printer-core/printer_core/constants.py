"""Pixel and physical constants for the thermal print stack.

DPMM is pinned from physical caliper measurement of a printed
calibration ruler. Nothing in the renderer depends on a specific
DPI — only mm conversions do (estimated_paper_mm, paper_used_mm,
max_length_mm enforcement).
"""

PRINT_HEAD_WIDTH_PX: int = 576
GUTTER_PX: int = 24
LIVE_WIDTH_PX: int = PRINT_HEAD_WIDTH_PX - 2 * GUTTER_PX  # = 528

# Density: dots per mm. Placeholder kept for reference; the runtime uses CALIBRATED.
DPMM_PLACEHOLDER: float = 180.0 / 25.4   # ~7.0866
# Pinned 2026-05-09. Caliper measurement on the NetumScan: 800 px = 99.9 mm
# (8.008 dpmm = 203.4 DPI). Rounded to a clean 8.0 dpmm because:
#   - 0.1% off measurement, well under caliper precision
#   - canonical 203-DPI thermal heads land at 7.992 dpmm — 8.0 is essentially
#     the same density (±0.1%)
#   - mm <-> px conversions become trivially clean: 1 mm = 8 px, 100 mm = 800 px,
#     so estimated_paper_mm / paper_used_mm / max_length_mm enforcement is
#     mental-math friendly when reasoning about long jobs
DPMM_CALIBRATED: float = 8.0
DPMM: float = DPMM_CALIBRATED

# Spec defaults
MAX_LENGTH_MM_DEFAULT: int = 2000
FEED_LINES_AFTER_DEFAULT: int = 2


def mm_to_px(mm: float) -> int:
    return round(mm * DPMM)


def px_to_mm(px: int) -> float:
    return px / DPMM
