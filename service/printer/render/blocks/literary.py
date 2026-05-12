from __future__ import annotations

from PIL import Image

from printer.constants import LIVE_WIDTH_PX
from printer.render.blocks import register
from printer.render.typography import (
    apply_italic,
    supersample_render,
    wrap_text,
)


def _cjk_fallback(ctx, *, bold: bool):
    """Noto Sans SC handle for non-Latin codepoints; ``None`` when the CJK
    font isn't bundled (so callers stay on the fast path).

    Duplicated from `text.py` to avoid cross-block imports that would
    introduce registration-order coupling. Cheap to repeat.
    """
    if not ctx.fonts.has_cjk_font():
        return None
    return ctx.fonts.cjk(bold=bold)


# ===== epigraph =====


@register("epigraph")
def render_epigraph(block, ctx) -> Image.Image:
    """Quiet quoted opener. Italic Plex Medium 16, indented 60 px L+R,
    no vertical bar (literary tradition favors plain indent over the
    rule-bar pull_quote uses).
    """
    side_indent = 60
    text_w = LIVE_WIDTH_PX - 2 * side_indent
    text_size_px = 16
    primary = ctx.fonts.display(weight="medium", size_px=text_size_px)
    fallback = _cjk_fallback(ctx, bold=False)
    lines = wrap_text(
        block.text, primary_font=primary, fallback_font=fallback,
        max_width_px=text_w,
    )
    line_imgs = [
        apply_italic(supersample_render(
            text=line, font=primary, fallback_font=fallback,
            target_size_px=text_size_px, max_width_px=text_w,
        )) for line in lines
    ]
    line_step = max((img.height for img in line_imgs), default=text_size_px) + 2
    parts_h = line_step * len(line_imgs)

    attr_img = None
    if block.attribution:
        attr_size_px = 13
        attr_font = ctx.fonts.display(weight="medium", size_px=attr_size_px)
        attr_img = apply_italic(supersample_render(
            text=f"— {block.attribution}", font=attr_font,
            fallback_font=_cjk_fallback(ctx, bold=False),
            target_size_px=attr_size_px, max_width_px=text_w,
        ))
        parts_h += attr_img.height + 4

    top_pad = 6
    bottom_pad = 10
    total_h = top_pad + parts_h + bottom_pad
    canvas = Image.new("1", (LIVE_WIDTH_PX, total_h), 1)
    y = top_pad
    for img in line_imgs:
        canvas.paste(img, (side_indent, y))
        y += line_step
    if attr_img is not None:
        # Right-aligned within the indented text column.
        ax = LIVE_WIDTH_PX - side_indent - attr_img.width
        canvas.paste(attr_img, (ax, y + 4))
    return canvas
