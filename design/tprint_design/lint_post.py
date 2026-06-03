"""Post-render lint pass — pixel inspection of the rendered raster."""
from __future__ import annotations

from PIL import Image, ImageChops
from printer_core.constants import DPMM
from printer_core.ink import ink_ratio

from tprint_design.lint import LintFinding, LintSeverity

_VERY_LONG_PX = 40000  # ~5 m of paper at 8 dpmm
_MOSTLY_EMPTY_RATIO = 0.05  # < 5 % ink → warn

# Per-pixel chroma threshold (max |R-G|, |G-B|, |R-B|) above which we count
# the pixel as colored. Subpixel font antialiasing under some Chromium builds
# produces fringes up to ~20 even with --disable-lcd-text — keep slack.
_COLOR_CHROMA_TOLERANCE = 24
# Fraction of total pixels that must be colored before we flag the render.
# A few stray colored pixels from glyph rasterization shouldn't trip the
# check; an intentional color block always covers far more.
_COLOR_RATIO_THRESHOLD = 0.001  # 0.1%


def post_render_lint(
    *,
    rgb: Image.Image,
    one_bit: Image.Image,
    effective_max_length_mm: int,
) -> list[LintFinding]:
    findings: list[LintFinding] = []

    if _has_color(rgb):
        findings.append(LintFinding(
            rule="color_used",
            severity=LintSeverity.ERROR,
            message=(
                "non-grayscale color detected in rendered output — "
                "thermal head is monochrome; switch to gray/black/white"
            ),
        ))

    height_px = one_bit.height
    if height_px > _VERY_LONG_PX:
        findings.append(LintFinding(
            rule="very_long_print",
            severity=LintSeverity.WARNING,
            message=f"render is {height_px} px tall (~{height_px / DPMM:.0f} mm of paper)",
        ))
    if height_px > effective_max_length_mm * DPMM:
        findings.append(LintFinding(
            rule="max_length_exceeded",
            severity=LintSeverity.ERROR,
            message=(
                f"render is {height_px / DPMM:.0f} mm tall, exceeds "
                f"max_length_mm = {effective_max_length_mm} mm"
            ),
        ))

    if ink_ratio(one_bit) < _MOSTLY_EMPTY_RATIO:
        findings.append(LintFinding(
            rule="mostly_empty",
            severity=LintSeverity.WARNING,
            message="render is >95% white — likely missing content",
        ))

    return findings


def _has_color(img: Image.Image) -> bool:
    if img.mode != "RGB":
        img = img.convert("RGB")
    r, g, b = img.split()
    max_chroma = ImageChops.lighter(
        ImageChops.lighter(
            ImageChops.difference(r, g),
            ImageChops.difference(g, b),
        ),
        ImageChops.difference(r, b),
    )
    mask = max_chroma.point(lambda v: 255 if v > _COLOR_CHROMA_TOLERANCE else 0)
    colored_pixels = mask.histogram()[255]
    total = mask.width * mask.height
    return total > 0 and (colored_pixels / total) > _COLOR_RATIO_THRESHOLD
