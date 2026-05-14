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

from tprint_design.render import RenderResult, render_html_to_png

_TRIM_FLOOR_PX = 80
_TRIM_LOOKBACK_ROWS = 16


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
        ink_pixel_ratio=_ink_ratio(trimmed),
        render_ms=raw.duration_ms,
        blocked_external_requests=raw.blocked_external_requests,
        raw_render=raw,
    )


def _trim_trailing_white(img: Image.Image) -> Image.Image:
    """Drop trailing all-white rows. Floor at 80 px image height.

    Strategy: walk bottom-up looking for a run of `_TRIM_LOOKBACK_ROWS`
    consecutive ink-bearing rows. The bottom-most row of that run is the
    last legitimate content; crop just below it. The lookback guards
    against stray dither pixels in the trailing whitespace producing a
    too-tall result. If no such run exists (very short content), fall
    back to the bottom-most ink row.
    """
    if img.mode != "1":
        img = img.convert("1")
    width, height = img.size
    if height <= _TRIM_FLOOR_PX:
        return img
    px = img.load()
    assert px is not None

    consecutive_ink = 0
    last_meaningful_row = -1
    for y in range(height - 1, -1, -1):
        if any(px[x, y] == 0 for x in range(width)):  # type: ignore[arg-type]
            consecutive_ink += 1
            if consecutive_ink == _TRIM_LOOKBACK_ROWS:
                last_meaningful_row = y + (_TRIM_LOOKBACK_ROWS - 1)
                break
        else:
            consecutive_ink = 0

    if last_meaningful_row < 0:
        for y in range(height - 1, -1, -1):
            if any(px[x, y] == 0 for x in range(width)):  # type: ignore[arg-type]
                last_meaningful_row = y
                break

    new_height = max(last_meaningful_row + 1, _TRIM_FLOOR_PX)
    if new_height >= height:
        return img
    return img.crop((0, 0, width, new_height))


def _ink_ratio(img: Image.Image) -> float:
    if img.mode != "1":
        img = img.convert("1")
    total = img.width * img.height
    if total == 0:
        return 0.0
    # mode "1" pixels are 0 or 255 -- count black (0) as ink.
    # Pillow stubs mark getdata() as non-iterable, but it iterates fine at runtime;
    # see dither.py for the same workaround pattern with `# type: ignore`.
    black = sum(1 for v in img.getdata() if v == 0)  # type: ignore[attr-defined,misc]
    return black / total
