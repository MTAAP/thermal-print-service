from __future__ import annotations

from PIL import Image, ImageDraw

from printer.constants import LIVE_WIDTH_PX
from printer.render.blocks import register


@register("tear_here")
def render_tear_here(block, ctx) -> Image.Image:
    h = 24
    canvas = Image.new("1", (LIVE_WIDTH_PX, h), 1)
    d = ImageDraw.Draw(canvas)
    y = 12
    for x in range(0, LIVE_WIDTH_PX, 8):
        d.line([(x, y), (x + 4, y)], fill=0, width=1)
    if block.label:
        d.text((4, 0), block.label, fill=0, font=ctx.fonts.body())
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
