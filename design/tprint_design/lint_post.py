"""Post-render lint pass — pixel inspection of the rendered raster."""
from __future__ import annotations

from PIL import Image
from printer_core.constants import DPMM

from tprint_design.lint import LintFinding, LintSeverity

_VERY_LONG_PX = 40000  # ~5 m of paper at 8 dpmm
_MOSTLY_EMPTY_RATIO = 0.05  # < 5 % ink → warn


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

    if _ink_ratio(one_bit) < _MOSTLY_EMPTY_RATIO:
        findings.append(LintFinding(
            rule="mostly_empty",
            severity=LintSeverity.WARNING,
            message="render is >95% white — likely missing content",
        ))

    return findings


def _has_color(img: Image.Image) -> bool:
    if img.mode != "RGB":
        img = img.convert("RGB")
    return any(r != g or g != b for r, g, b in img.getdata())  # type: ignore[attr-defined, misc]


def _ink_ratio(img: Image.Image) -> float:
    if img.mode != "1":
        img = img.convert("1")
    total = img.width * img.height
    if total == 0:
        return 0.0
    black = sum(1 for v in img.getdata() if v == 0)  # type: ignore[attr-defined, misc]
    return black / total
