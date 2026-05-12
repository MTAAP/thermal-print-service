from __future__ import annotations

from PIL import Image, ImageDraw

from printer.constants import LIVE_WIDTH_PX
from printer.render.blocks import register


@register("tear_here")
def render_tear_here(block, ctx) -> Image.Image:
    from printer.render.typography import BODY_LINE_H, render_body_line

    dash_strip_h = 16
    if block.label:
        label_img = render_body_line(
            block.label, fonts=ctx.fonts, max_width_px=LIVE_WIDTH_PX,
        )
        label_band = max(BODY_LINE_H, label_img.height) + 4
    else:
        label_img = None
        label_band = 0
    h = label_band + dash_strip_h
    canvas = Image.new("1", (LIVE_WIDTH_PX, h), 1)
    if label_img is not None:
        canvas.paste(label_img, (0, 0))
    d = ImageDraw.Draw(canvas)
    y = label_band + dash_strip_h // 2
    for x in range(0, LIVE_WIDTH_PX, 8):
        d.line([(x, y), (x + 4, y)], fill=0, width=1)
    return canvas


@register("cut")
def render_cut(block, ctx) -> Image.Image:
    # Marker pixels for the renderer to split the document into sub-jobs.
    # Phase 5 honors this; in Phase 3 it's just a 1-px row.
    canvas = Image.new("1", (LIVE_WIDTH_PX, 1), 1)
    return canvas


@register("feed")
def render_feed(block, ctx) -> Image.Image:
    return Image.new("1", (LIVE_WIDTH_PX, 14 * block.lines), 1)
