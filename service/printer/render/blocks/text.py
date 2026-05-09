from __future__ import annotations

import textwrap

from PIL import Image, ImageDraw

from printer.constants import LIVE_WIDTH_PX
from printer.render.blocks import register
from printer.render.typography import (
    apply_italic,
    apply_underline,
    contains_cjk,
    render_body_text_mixed,
    supersample_render,
    supersample_render_mixed,
)


def _render_display_text(text: str, ctx, *, weight: str, size_px: int, max_width_px: int, **kwargs):
    """Render display text with CJK fallback if needed."""
    if contains_cjk(text) and ctx.fonts.has_cjk_font():
        return supersample_render_mixed(
            text=text,
            latin_font=ctx.fonts.display(weight=weight, size_px=size_px),
            cjk_font=ctx.fonts.cjk(bold=(weight == "bold"), size_px=size_px),
            target_size_px=size_px,
            max_width_px=max_width_px,
            **kwargs,
        )
    return supersample_render(
        text=text,
        font=ctx.fonts.display(weight=weight, size_px=size_px),
        target_size_px=size_px,
        max_width_px=max_width_px,
        **kwargs,
    )


@register("header")
def render_header(block, ctx) -> Image.Image:
    target_h = 56
    title = _render_display_text(
        block.text, ctx, weight="bold", size_px=28, max_width_px=LIVE_WIDTH_PX - 24,
    )
    if block.style == "inverse_band":
        canvas = Image.new("1", (LIVE_WIDTH_PX, target_h), 0)  # black band
        # Render title in white: invert title image then paste
        inv = title.point(lambda v: 255 if v == 0 else 0).convert("1")
        x = (LIVE_WIDTH_PX - inv.width) // 2 if block.align == "center" else \
            (LIVE_WIDTH_PX - inv.width) if block.align == "right" else 12
        canvas.paste(inv, (x, max(0, (target_h - inv.height) // 2)))
        return canvas
    canvas = Image.new("1", (LIVE_WIDTH_PX, target_h), 1)
    x = (LIVE_WIDTH_PX - title.width) // 2 if block.align == "center" else \
        (LIVE_WIDTH_PX - title.width) if block.align == "right" else 0
    canvas.paste(title, (x, max(0, (target_h - title.height) // 2)))
    return canvas


@register("section_title")
def render_section_title(block, ctx) -> Image.Image:
    target_h = 36
    img = _render_display_text(
        block.text, ctx, weight="medium", size_px=22, max_width_px=LIVE_WIDTH_PX,
    )
    canvas = Image.new("1", (LIVE_WIDTH_PX, target_h + 4), 1)
    x = 0 if block.align == "left" else \
        (LIVE_WIDTH_PX - img.width) // 2 if block.align == "center" else \
        (LIVE_WIDTH_PX - img.width)
    canvas.paste(img, (x, 0))
    if block.style == "underline":
        d = ImageDraw.Draw(canvas)
        d.line([(0, target_h + 1), (LIVE_WIDTH_PX - 1, target_h + 1)], fill=0, width=2)
    return canvas


@register("paragraph")
def render_paragraph(block, ctx) -> Image.Image:
    font = ctx.fonts.body()
    avg_glyph_px = 8  # Spleen 8x16 body, monospace
    # For CJK, characters are typically twice as wide
    has_cjk = contains_cjk(block.text)
    cjk_chars_per_line = max(20, LIVE_WIDTH_PX // 16) if has_cjk else 0
    chars_per_line = max(20, LIVE_WIDTH_PX // avg_glyph_px)

    # Use simpler wrapping for mixed text - estimate effective width
    if has_cjk:
        # Rough estimate: CJK chars are ~2x width of Latin
        effective_width = cjk_chars_per_line
    else:
        effective_width = chars_per_line

    wrapped = textwrap.wrap(block.text, width=effective_width) or [block.text]
    line_h = 18
    canvas = Image.new("1", (LIVE_WIDTH_PX, line_h * len(wrapped) + 4), 1)

    use_cjk_render = has_cjk and ctx.fonts.has_cjk_font()
    y = 0
    for line in wrapped:
        if use_cjk_render:
            line_img = render_body_text_mixed(
                text=line,
                body_font=font,
                cjk_font=ctx.fonts.cjk(size_px=16),
            )
            line_w = line_img.width
            x = 0 if block.align == "left" else \
                (LIVE_WIDTH_PX - line_w) // 2 if block.align == "center" else \
                max(0, LIVE_WIDTH_PX - line_w)
            canvas.paste(line_img, (x, y))
        else:
            d = ImageDraw.Draw(canvas)
            try:
                bbox = font.getbbox(line)
                line_w = bbox[2] - bbox[0]
            except Exception:
                line_w = len(line) * avg_glyph_px
            x = 0 if block.align == "left" else \
                (LIVE_WIDTH_PX - line_w) // 2 if block.align == "center" else \
                (LIVE_WIDTH_PX - line_w)
            d.text((x, y), line, fill=0, font=font)
        y += line_h
    return canvas


@register("footer")
def render_footer(block, ctx) -> Image.Image:
    img = _render_display_text(
        block.text, ctx, weight="medium", size_px=14, max_width_px=LIVE_WIDTH_PX,
    )
    canvas = Image.new("1", (LIVE_WIDTH_PX, img.height + 8), 1)
    canvas.paste(img, ((LIVE_WIDTH_PX - img.width) // 2, 4))
    return canvas


@register("large_text")
def render_large_text(block, ctx) -> Image.Image:
    sizes = {"xl": 48, "xxl": 80, "xxxl": 128}
    target = sizes[block.size]
    img = _render_display_text(
        block.text, ctx, weight="bold", size_px=target, max_width_px=LIVE_WIDTH_PX,
    )
    canvas = Image.new("1", (LIVE_WIDTH_PX, img.height + 8), 1)
    if block.align == "left":
        x = 0
    elif block.align == "right":
        x = LIVE_WIDTH_PX - img.width
    else:
        x = (LIVE_WIDTH_PX - img.width) // 2
    canvas.paste(img, (x, 4))
    return canvas


@register("pull_quote")
def render_pull_quote(block, ctx) -> Image.Image:
    bar_w = 4
    indent = 16
    text_w = LIVE_WIDTH_PX - bar_w - indent
    quote_img = _render_display_text(
        block.text, ctx, weight="medium", size_px=20, max_width_px=text_w,
    )
    parts = [quote_img]
    if block.attribution:
        attr_img = _render_display_text(
            f"— {block.attribution}", ctx, weight="medium", size_px=12, max_width_px=text_w,
        )
        parts.append(attr_img)
    pad = 6
    h = sum(p.height for p in parts) + pad * (len(parts) + 1)
    canvas = Image.new("1", (LIVE_WIDTH_PX, h), 1)
    d = ImageDraw.Draw(canvas)
    d.rectangle([0, 0, bar_w - 1, h - 1], fill=0)
    y = pad
    for p in parts:
        canvas.paste(p, (bar_w + indent, y))
        y += p.height + pad
    return canvas


@register("drop_cap")
def render_drop_cap(block, ctx) -> Image.Image:
    # 56 px caps printed thin under the default 2×-Atkinson pipeline because
    # error diffusion thins large solid regions. Render at 4× supersample
    # and ordered (Bayer 8x8) dither: ordered keeps large solid regions
    # saturated, and the higher supersample carries richer luminance into
    # each output pixel.
    cap_size = 56
    cap_img = _render_display_text(
        block.first_letter, ctx, weight="bold", size_px=cap_size,
        max_width_px=cap_size + 8, factor=4, dither="ordered",
    )
    cap_w = cap_img.width
    cap_h = cap_img.height
    body_font = ctx.fonts.body()
    line_h = 18
    indent = cap_w + 6
    avg_glyph_px = 8  # Spleen 8x16 body, monospace
    full_chars = max(20, LIVE_WIDTH_PX // avg_glyph_px)
    indented_chars = max(20, (LIVE_WIDTH_PX - indent) // avg_glyph_px)

    # Greedy two-phase wrap: first wrap with the indented width until we've
    # covered cap_h, then continue wrapping at full width.
    words = block.rest.split()
    lines: list[str] = []
    current = ""
    chars_per_line = indented_chars

    def push_line():
        nonlocal current
        if current:
            lines.append(current)
            current = ""

    used_h = 0
    for w in words:
        candidate = (current + " " + w).strip()
        if len(candidate) <= chars_per_line:
            current = candidate
            continue
        push_line()
        used_h += line_h
        if used_h >= cap_h:
            chars_per_line = full_chars
        current = w
    push_line()

    h = max(cap_h, len(lines) * line_h) + 4
    canvas = Image.new("1", (LIVE_WIDTH_PX, h), 1)
    canvas.paste(cap_img, (0, 0))

    use_cjk_render = contains_cjk(block.rest) and ctx.fonts.has_cjk_font()
    y = 0
    for line in lines:
        x = indent if (y < cap_h) else 0
        if use_cjk_render:
            line_img = render_body_text_mixed(
                text=line,
                body_font=body_font,
                cjk_font=ctx.fonts.cjk(size_px=16),
            )
            canvas.paste(line_img, (x, y))
        else:
            d = ImageDraw.Draw(canvas)
            d.text((x, y), line, fill=0, font=body_font)
        y += line_h
    return canvas


def _render_code_text(text: str, ctx, *, size_px: int, max_width_px: int):
    """Render code text with CJK fallback if needed."""
    if contains_cjk(text) and ctx.fonts.has_cjk_font():
        return supersample_render_mixed(
            text=text,
            latin_font=ctx.fonts.code(size_px=size_px),
            cjk_font=ctx.fonts.cjk(size_px=size_px),
            target_size_px=size_px,
            max_width_px=max_width_px,
        )
    return supersample_render(
        text=text,
        font=ctx.fonts.code(size_px=size_px),
        target_size_px=size_px,
        max_width_px=max_width_px,
    )


@register("code")
def render_code(block, ctx) -> Image.Image:
    # Direct 1× JetBrains Mono draws into a 1-bit canvas without any
    # smoothing — at 14 px most glyphs lose their stroke continuity on the
    # thermal head. Supersample each line at 2× and Atkinson-dither so
    # hinted shapes survive.
    target_px = 14
    line_h = 18
    lines = block.text.split("\n")
    rendered = [
        _render_code_text(line if line else " ", ctx, size_px=target_px, max_width_px=LIVE_WIDTH_PX)
        for line in lines
    ]
    h = line_h * len(rendered) + 4
    canvas = Image.new("1", (LIVE_WIDTH_PX, h), 1)
    for i, img in enumerate(rendered):
        canvas.paste(img, (0, i * line_h))
    return canvas


@register("rich_text")
def render_rich_text(block, ctx) -> Image.Image:
    # Per-line max-height so "lg" runs (28 px) and underlined runs don't
    # spill into the next line. Line gap stays small (4 px) to keep receipts
    # tight; the line baselines are bottom-aligned within each line so mixed
    # sizes share a footing instead of floating mid-line.
    line_gap = 4
    fragments_per_line: list[list[Image.Image]] = [[]]
    line_widths: list[int] = [0]
    line_heights: list[int] = [0]
    for run in block.runs:
        weight = "bold" if run.bold else "medium"
        size_target = {"sm": 12, "md": 18, "lg": 28}.get(run.size, 18)
        frag = _render_display_text(
            run.text, ctx, weight=weight, size_px=size_target, max_width_px=LIVE_WIDTH_PX,
        )
        # Order: italic shear first (synthetic-slant of glyph shapes) →
        # underline rule (axis-aligned, attached below the slanted glyphs) →
        # inverse (pixel-invert applies to text + rule together).
        if run.italic:
            frag = apply_italic(frag)
        if run.underline:
            frag = apply_underline(frag)
        if run.inverse:
            frag = frag.point(lambda v: 255 if v == 0 else 0).convert("1")
        if line_widths[-1] + frag.width > LIVE_WIDTH_PX and fragments_per_line[-1]:
            fragments_per_line.append([])
            line_widths.append(0)
            line_heights.append(0)
        fragments_per_line[-1].append(frag)
        line_widths[-1] += frag.width
        line_heights[-1] = max(line_heights[-1], frag.height)
    total_h = sum(line_heights) + line_gap * len(fragments_per_line) + 4
    canvas = Image.new("1", (LIVE_WIDTH_PX, total_h), 1)
    y = 0
    for li, line_frags in enumerate(fragments_per_line):
        x = 0
        if block.align == "center":
            x = (LIVE_WIDTH_PX - line_widths[li]) // 2
        elif block.align == "right":
            x = LIVE_WIDTH_PX - line_widths[li]
        line_h = line_heights[li]
        for frag in line_frags:
            # Bottom-align so mixed-size runs share a baseline.
            y_off = line_h - frag.height
            canvas.paste(frag, (x, y + y_off))
            x += frag.width
        y += line_h + line_gap
    return canvas
