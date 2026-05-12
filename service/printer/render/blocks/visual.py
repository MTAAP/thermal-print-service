from __future__ import annotations

import math

from PIL import Image, ImageDraw

from printer.constants import LIVE_WIDTH_PX
from printer.render.blocks import register


@register("rule")
def render_rule(block, ctx) -> Image.Image:
    # All five styles now stroke at width=2 for consistent visual weight on
    # the thermal head — width=1 dashed/dotted/double/wave rules were nearly
    # invisible compared to solid. Wave rule uses thicker dot stamping for
    # the same reason.
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
        # Larger circles at wider spacing — width=1 ellipses read as smudges.
        for x in range(0, LIVE_WIDTH_PX, 10):
            d.ellipse([x, y - 2, x + 4, y + 2], fill=0)
    elif block.style == "double":
        # Two parallel rules at width=2 each, gap=3 px between centers, so
        # the pair reads as a deliberate "double" rather than a fuzzy single.
        d.line([(0, y - 3), (LIVE_WIDTH_PX - 1, y - 3)], fill=0, width=2)
        d.line([(0, y + 3), (LIVE_WIDTH_PX - 1, y + 3)], fill=0, width=2)
    elif block.style == "wave":
        prev = (0, y)
        for x in range(0, LIVE_WIDTH_PX):
            ny = y + int(2 * math.sin(x / 6))
            d.line([prev, (x, ny)], fill=0, width=2)
            prev = (x, ny)
    return canvas


@register("spacer")
def render_spacer(block, ctx) -> Image.Image:
    from printer.render.typography import BODY_LINE_H

    return Image.new("1", (LIVE_WIDTH_PX, BODY_LINE_H * block.lines), 1)


@register("ornament")
def render_ornament(block, ctx) -> Image.Image:
    """Decorative band, ~28 px tall. Each pattern uses Unicode dingbats or
    block elements rendered through supersample_render at display weight, so
    the ornaments survive the thermal head with the same stroke fidelity as
    other display text. Tokens are tiled to fill the live width.
    """
    from printer.render.typography import supersample_render

    tokens = {
        "stars": "★ ",
        "diamonds": "◆ ",
        "leaves": "❀ ",
        # Alternating filled / hollow squares — strong "geometric" feel that
        # tiles cleanly. ▰▱ would have been a closer match but BLACK
        # PARALLELOGRAM (U+25B0) isn't covered by any bundled font.
        "geometric": "■□ ",
        "waves": "～",
        # Alternating filled / hollow diamond run — the angular zigzag reads
        # as art-deco at receipt sizes. Distinct from `diamonds` (which is
        # solid ◆ alone).
        "art_deco": "◆◇ ",
        "minimal_dots": "·  ",
    }
    token = tokens[block.pattern]
    size_px = 22
    font = ctx.fonts.display(weight="bold", size_px=size_px)
    # The IBM Plex display face does not cover most dingbats (★ ◆ ❀ ■□ ～
    # ◆◇) — they all resolve to .notdef tofu glyphs and the patterns
    # collapse to identical renders. Noto Sans SC (the CJK fallback) covers
    # the full set, so route through the same per-glyph fallback path used
    # by render_body_line.
    fallback = ctx.fonts.cjk(bold=True) if ctx.fonts.has_cjk_font() else None
    # Measure token width via the fallback when available, so tiling counts
    # reflect the glyph actually composited at render time.
    measure_font = fallback if fallback is not None else font
    bbox = measure_font.getbbox(token)
    token_w = max(1, bbox[2] - bbox[0])
    tile_count = max(1, LIVE_WIDTH_PX // token_w)
    line = (token * tile_count).rstrip()
    img = supersample_render(
        text=line, font=font, fallback_font=fallback,
        target_size_px=size_px, max_width_px=LIVE_WIDTH_PX,
    )
    h = img.height + 8
    canvas = Image.new("1", (LIVE_WIDTH_PX, h), 1)
    x = max(0, (LIVE_WIDTH_PX - img.width) // 2)
    canvas.paste(img, (x, 4))
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
    assert px is not None
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
    from printer.render.typography import BODY_LINE_H, render_body_line

    bar_h = 16
    pad = 4
    if block.label:
        pct = int(round(block.value * 100))
        label_img = render_body_line(
            f"{block.label}  {pct}%", fonts=ctx.fonts, max_width_px=LIVE_WIDTH_PX,
        )
        # Reserve a full body line-height for the label so descenders don't
        # reach the bar's top edge. Raw d.text() at the body font produced
        # ~18 px of glyphs in a 14 px gap and crashed into the bar.
        label_band = max(BODY_LINE_H, label_img.height) + pad
    else:
        label_img = None
        label_band = 0
    h = label_band + bar_h
    canvas = Image.new("1", (LIVE_WIDTH_PX, h), 1)
    if label_img is not None:
        canvas.paste(label_img, (0, 0))
    d = ImageDraw.Draw(canvas)
    # Outer border
    d.rectangle(
        [0, label_band, LIVE_WIDTH_PX - 1, label_band + bar_h - 1],
        outline=0, width=1,
    )
    filled_w = int((LIVE_WIDTH_PX - 4) * block.value)
    if filled_w > 0:
        d.rectangle(
            [2, label_band + 2, 2 + filled_w, label_band + bar_h - 3], fill=0,
        )
    return canvas


@register("sparkline")
def render_sparkline(block, ctx) -> Image.Image:
    from printer.render.typography import BODY_LINE_H, render_body_line

    bar_h = 32
    pad = 2
    if block.label:
        label_img = render_body_line(
            block.label, fonts=ctx.fonts, max_width_px=LIVE_WIDTH_PX,
        )
        label_band = max(BODY_LINE_H, label_img.height) + pad
    else:
        label_img = None
        label_band = 0
    h = label_band + bar_h
    canvas = Image.new("1", (LIVE_WIDTH_PX, h), 1)
    if label_img is not None:
        canvas.paste(label_img, (0, 0))
    d = ImageDraw.Draw(canvas)
    top = label_band

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
    return canvas
