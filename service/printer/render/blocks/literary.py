from __future__ import annotations

from PIL import Image

from printer.constants import LIVE_WIDTH_PX
from printer.render.blocks import register
from printer.render.typography import (
    apply_italic,
    cjk_fallback,
    supersample_render,
    wrap_text,
)

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
    fallback = cjk_fallback(ctx.fonts, bold=False)
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
            fallback_font=cjk_fallback(ctx.fonts, bold=False),
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


# ===== byline =====


@register("byline")
def render_byline(block, ctx) -> Image.Image:
    """Author credit. Plex Medium italic 14 px, left-aligned, small."""
    size_px = 14
    font = ctx.fonts.display(weight="medium", size_px=size_px)
    fallback = cjk_fallback(ctx.fonts, bold=False)
    img = apply_italic(supersample_render(
        text=block.text, font=font, fallback_font=fallback,
        target_size_px=size_px, max_width_px=LIVE_WIDTH_PX,
    ))
    top_pad = 4
    bottom_pad = 8
    total_h = top_pad + img.height + bottom_pad
    canvas = Image.new("1", (LIVE_WIDTH_PX, total_h), 1)
    canvas.paste(img, (0, top_pad))
    return canvas


# ===== dateline =====


@register("dateline")
def render_dateline(block, ctx) -> Image.Image:
    """Journalistic location + date opener. Plex Bold 14, uppercased.

    Format: ``{LOCATION}, {DATE} ——`` (double em-dash).
    """
    size_px = 14
    font = ctx.fonts.display(weight="bold", size_px=size_px)
    fallback = cjk_fallback(ctx.fonts, bold=True)
    text = f"{block.location.upper()}, {block.date.upper()} ——"
    img = supersample_render(
        text=text, font=font, fallback_font=fallback,
        target_size_px=size_px, max_width_px=LIVE_WIDTH_PX,
    )
    top_pad = 4
    bottom_pad = 6
    total_h = top_pad + img.height + bottom_pad
    canvas = Image.new("1", (LIVE_WIDTH_PX, total_h), 1)
    canvas.paste(img, (0, top_pad))
    return canvas
