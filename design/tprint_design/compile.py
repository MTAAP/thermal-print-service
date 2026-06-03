"""End-to-end HTML file -> 1-bit thermal PNG.

Pipeline (per spec Render pipeline):
  1. Load HTML from disk
  2. Render via Playwright at 576-px viewport, full-page screenshot
  3. Persist the RGB raster as `<out>.rgb.png` (post-render lint reads it)
  4. Convert to grayscale (mode "L") and write `<out>.preview.png`
  5. Atkinson-dither to 1-bit (mode "1")
  6. Trim trailing white rows (floor 80 px)
  7. Save final PNG and return stats for the lint report
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image
from printer_core.constants import DPMM, PRINT_HEAD_WIDTH_PX
from printer_core.dither import atkinson_dither
from printer_core.ink import ink_ratio

from tprint_design.render import RenderResult, render_html_to_png

_TRIM_FLOOR_PX = 80
# Minimum inked-pixel count for a row to count as "meaningful content"
# rather than a stray Atkinson-dither speckle. A real glyph row easily
# clears 3 ink pixels; isolated single-pixel artifacts in trailing
# whitespace are filtered out by this threshold.
_TRIM_MIN_INK_PIXELS_PER_ROW = 3


@dataclass(frozen=True)
class CompileResult:
    out_path: Path
    preview_path: Path
    rgb_path: Path
    rendered_height_px: int
    estimated_paper_mm: float
    ink_pixel_ratio: float
    render_ms: int
    blocked_external_requests: int
    raw_render: RenderResult


def compile_html(
    src: Path,
    *,
    out_path: Path | None = None,
    width: int = PRINT_HEAD_WIDTH_PX,
    timeout_ms: int = 5000,
) -> CompileResult:
    src = Path(src)
    html = src.read_text()
    if out_path is None:
        out_path = src.with_suffix(".png")
    preview_path = out_path.with_name(out_path.stem + ".preview.png")
    rgb_path = out_path.with_name(out_path.stem + ".rgb.png")

    raw = render_html_to_png(
        html,
        out_path=out_path.with_suffix(".raw.png"),
        source_path=src,
        width=width,
        timeout_ms=timeout_ms,
    )

    with Image.open(raw.png_path) as raster:
        rgb = raster.convert("RGB")
        rgb.save(rgb_path, format="PNG")
        gray = raster.convert("L")
    gray.save(preview_path, format="PNG")

    one_bit = atkinson_dither(gray)
    trimmed = _trim_trailing_white(one_bit)
    trimmed.save(out_path, format="PNG")

    raw.png_path.unlink(missing_ok=True)

    height = trimmed.height
    return CompileResult(
        out_path=out_path,
        preview_path=preview_path,
        rgb_path=rgb_path,
        rendered_height_px=height,
        estimated_paper_mm=height / DPMM,
        ink_pixel_ratio=ink_ratio(trimmed),
        render_ms=raw.duration_ms,
        blocked_external_requests=raw.blocked_external_requests,
        raw_render=raw,
    )


def _trim_trailing_white(img: Image.Image) -> Image.Image:
    """Drop trailing rows below the last row with meaningful content.

    Walk bottom-up. The first row encountered with at least
    ``_TRIM_MIN_INK_PIXELS_PER_ROW`` ink pixels is the last legitimate
    content row; crop just below it. The density threshold filters
    stray single-pixel Atkinson dither artifacts in trailing whitespace
    so they don't extend the page, while still preserving sparse but
    intentional trailing content (e.g. a caption line below a heavier
    block separated by a margin). If no row clears the threshold, fall
    back to the bottom-most row with any ink at all. Floor at
    ``_TRIM_FLOOR_PX``.
    """
    if img.mode != "1":
        img = img.convert("1")
    width, height = img.size
    if height <= _TRIM_FLOOR_PX:
        return img
    px = img.load()
    assert px is not None

    last_meaningful_row = -1
    for y in range(height - 1, -1, -1):
        ink_count = sum(
            1 for x in range(width) if px[x, y] == 0  # type: ignore[arg-type]
        )
        if ink_count >= _TRIM_MIN_INK_PIXELS_PER_ROW:
            last_meaningful_row = y
            break

    if last_meaningful_row < 0:
        for y in range(height - 1, -1, -1):
            if any(px[x, y] == 0 for x in range(width)):  # type: ignore[arg-type]
                last_meaningful_row = y
                break

    new_height = max(last_meaningful_row + 1, _TRIM_FLOOR_PX)
    if new_height >= height:
        return img
    return img.crop((0, 0, width, new_height))
