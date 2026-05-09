from __future__ import annotations

import math

from PIL import Image, ImageDraw

from printer.constants import LIVE_WIDTH_PX
from printer.render.blocks import register


@register("rule")
def render_rule(block, ctx) -> Image.Image:
    h = 8
    canvas = Image.new("1", (LIVE_WIDTH_PX, h), 1)
    d = ImageDraw.Draw(canvas)
    y = h // 2
    if block.style == "solid":
        d.line([(0, y), (LIVE_WIDTH_PX - 1, y)], fill=0, width=2)
    elif block.style == "dashed":
        for x in range(0, LIVE_WIDTH_PX, 12):
            d.line([(x, y), (x + 8, y)], fill=0, width=2)
    elif block.style == "dotted":
        for x in range(0, LIVE_WIDTH_PX, 6):
            d.ellipse([x, y - 1, x + 2, y + 1], fill=0)
    elif block.style == "double":
        d.line([(0, y - 2), (LIVE_WIDTH_PX - 1, y - 2)], fill=0, width=1)
        d.line([(0, y + 2), (LIVE_WIDTH_PX - 1, y + 2)], fill=0, width=1)
    elif block.style == "wave":
        prev = (0, y)
        for x in range(0, LIVE_WIDTH_PX):
            ny = y + int(2 * math.sin(x / 6))
            d.line([prev, (x, ny)], fill=0, width=1)
            prev = (x, ny)
    return canvas


@register("spacer")
def render_spacer(block, ctx) -> Image.Image:
    h = 14 * block.lines
    return Image.new("1", (LIVE_WIDTH_PX, h), 1)


@register("ornament")
def render_ornament(block, ctx) -> Image.Image:
    # Single-line decorative band, ~24 px tall. Patterns are repeated tokens;
    # we measure the token width once and tile to fit the live area exactly,
    # so wide patterns like ``geometric`` never clip mid-glyph at the right
    # edge regardless of font metrics.
    h = 24
    canvas = Image.new("1", (LIVE_WIDTH_PX, h), 1)
    d = ImageDraw.Draw(canvas)
    tokens = {
        "stars": "* ",
        "diamonds": "<> ",
        "leaves": "~ * ",
        "geometric": "[] /\\ ",
    }
    token = tokens[block.pattern]
    font = ctx.fonts.body()
    bbox = font.getbbox(token)
    token_w = max(1, bbox[2] - bbox[0])
    tile_count = max(1, LIVE_WIDTH_PX // token_w)
    # Drop the trailing space on the final token so the rendered string
    # bounding box reflects the inked glyphs only and centers cleanly.
    line = (token * tile_count).rstrip()
    line_bbox = font.getbbox(line)
    line_w = line_bbox[2] - line_bbox[0]
    x = max(0, (LIVE_WIDTH_PX - line_w) // 2)
    d.text((x, 4), line, fill=0, font=font)
    return canvas


@register("gradient_band")
def render_gradient_band(block, ctx) -> Image.Image:
    # Top-to-bottom grey ramp dithered to 1-bit. Two failure modes to avoid:
    #   - Atkinson on a uniform ramp: each row sheds the same error to the
    #     same downstream cells, producing visible horizontal stripes.
    #   - Bayer 8x8: mathematically correct but at this band height (~8 cell-
    #     repeats vertically) the matrix's deterministic pattern shows as
    #     periodic cross-hatching.
    # PIL's Floyd-Steinberg with serpentine scan produces a noise-like
    # texture without periodic structure, which reads as a clean fade on
    # the head. Doubled band height (was 64) so the gradient has more
    # vertical room to develop before reaching saturation.
    from printer.render.dither import floyd_steinberg

    h = 128
    base = Image.new("L", (LIVE_WIDTH_PX, h), 255)
    px = base.load()
    for y in range(h):
        # ``down`` = darker at top, fading to white at bottom; ``up``
        # reverses. The grey value goes 0 (black) → 255 (white) along that
        # axis.
        if block.direction == "down":
            v = int(255 * (y / max(1, h - 1)))
        else:
            v = int(255 * (1 - y / max(1, h - 1)))
        for x in range(LIVE_WIDTH_PX):
            px[x, y] = v
    return floyd_steinberg(base)


@register("progress_bar")
def render_progress_bar(block, ctx) -> Image.Image:
    bar_h = 16
    label_h = 14
    pad = 4
    h = bar_h + (label_h + pad if block.label else 0)
    canvas = Image.new("1", (LIVE_WIDTH_PX, h), 1)
    d = ImageDraw.Draw(canvas)
    bar_top = label_h + pad if block.label else 0
    # Outer border
    d.rectangle(
        [0, bar_top, LIVE_WIDTH_PX - 1, bar_top + bar_h - 1],
        outline=0,
        width=1,
    )
    # Filled portion
    filled_w = int((LIVE_WIDTH_PX - 4) * block.value)
    if filled_w > 0:
        d.rectangle([2, bar_top + 2, 2 + filled_w, bar_top + bar_h - 3], fill=0)
    if block.label:
        pct = int(round(block.value * 100))
        text = f"{block.label}  {pct}%"
        d.text((0, 0), text, fill=0, font=ctx.fonts.body())
    return canvas


@register("sparkline")
def render_sparkline(block, ctx) -> Image.Image:
    bar_h = 32
    label_h = 14
    pad = 2
    h = bar_h + (label_h + pad if block.label else 0)
    canvas = Image.new("1", (LIVE_WIDTH_PX, h), 1)
    d = ImageDraw.Draw(canvas)
    top = label_h + pad if block.label else 0

    vmin = min(block.values)
    vmax = max(block.values)
    span = vmax - vmin if vmax > vmin else 1.0

    n = len(block.values)
    bar_w = max(1, LIVE_WIDTH_PX // n)
    gap = 1 if bar_w >= 3 else 0
    actual_bar_w = max(1, bar_w - gap)
    for i, v in enumerate(block.values):
        x = i * bar_w
        norm = (v - vmin) / span
        bar_height = max(1, int(norm * (bar_h - 2)))
        y0 = top + (bar_h - bar_height)
        y1 = top + bar_h
        d.rectangle([x, y0, x + actual_bar_w - 1, y1 - 1], fill=0)

    if block.label:
        d.text((0, 0), block.label, fill=0, font=ctx.fonts.body())
    return canvas
