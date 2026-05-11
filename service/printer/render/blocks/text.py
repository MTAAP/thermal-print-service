from __future__ import annotations

from PIL import Image, ImageDraw

from printer.constants import LIVE_WIDTH_PX
from printer.render.blocks import register
from printer.render.typography import (
    BODY_LINE_H,
    apply_italic,
    apply_underline,
    iter_atoms,
    render_body_line,
    supersample_render,
    wrap_body_text,
    wrap_text,
)


def _cjk_fallback(ctx, *, bold: bool):
    """Noto Sans SC handle to pass as ``fallback_font``, or ``None`` when the
    CJK font isn't bundled (so callers stay on the fast path)."""
    if not ctx.fonts.has_cjk_font():
        return None
    return ctx.fonts.cjk(bold=bold)


@register("header")
def render_header(block, ctx) -> Image.Image:
    # ``band_h`` is the visual band, ``bottom_pad`` is white margin below it
    # so the next block doesn't crash into the band edge. Pre-v0.8 the
    # inverse_band returned a canvas exactly ``band_h`` tall, entirely
    # black, and a following paragraph would start its first text row flush
    # against the band's lower border.
    # bbox-tight centering: the rendered text image height is cap-to-baseline
    # for cap-only words and cap-to-descender for words with descenders, so
    # ``(band_h - img.height) // 2`` keeps the visual mass of the glyphs
    # near the band's optical center for both. Cap-height-based centering
    # was tried in v3 and made descender words sit 2 px lower because the
    # cap-line was pinned regardless of descender, biasing the baseline
    # toward the bottom.
    band_h = 56
    bottom_pad = 10
    header_font = ctx.fonts.display(weight="bold", size_px=28)
    title = supersample_render(
        text=block.text, font=header_font,
        fallback_font=_cjk_fallback(ctx, bold=True),
        target_size_px=28, max_width_px=LIVE_WIDTH_PX - 24,
    )
    if block.style == "inverse_band":
        canvas = Image.new("1", (LIVE_WIDTH_PX, band_h + bottom_pad), 1)  # white pad
        ImageDraw.Draw(canvas).rectangle(
            [0, 0, LIVE_WIDTH_PX - 1, band_h - 1], fill=0,
        )
        # Render title in white: invert title image then paste over the band.
        inv = title.point(lambda v: 255 if v == 0 else 0).convert("1")
        x = (LIVE_WIDTH_PX - inv.width) // 2 if block.align == "center" else \
            (LIVE_WIDTH_PX - inv.width) if block.align == "right" else 12
        canvas.paste(inv, (x, max(0, (band_h - inv.height) // 2)))
        return canvas
    canvas = Image.new("1", (LIVE_WIDTH_PX, band_h + bottom_pad), 1)
    x = (LIVE_WIDTH_PX - title.width) // 2 if block.align == "center" else \
        (LIVE_WIDTH_PX - title.width) if block.align == "right" else 0
    canvas.paste(title, (x, max(0, (band_h - title.height) // 2)))
    return canvas


@register("section_title")
def render_section_title(block, ctx) -> Image.Image:
    # Pre-v0.8 the canvas was ``target_h + 4`` with the text pasted at
    # ``y=0``, so the cap-line crashed into whatever block sat above (often
    # a ``rule``) and ~20 px of slack hung between the text baseline and
    # the underline. Pad the top, vertically center the text inside the
    # band, and drop the rule at the bottom — symmetric breathing room.
    target_h = 36
    top_pad = 4
    # Padding below the underline so a paragraph that follows the section
    # divider doesn't sit flush against the rule. Body-content blocks
    # (paragraph, lists) intentionally start at y=0 to stack tightly within
    # reading flow — that means the *divider* needs to own the gap.
    bottom_pad = 14
    title_font = ctx.fonts.display(weight="medium", size_px=22)
    img = supersample_render(
        text=block.text, font=title_font,
        fallback_font=_cjk_fallback(ctx, bold=False),
        target_size_px=22, max_width_px=LIVE_WIDTH_PX,
    )
    canvas_h = top_pad + target_h + bottom_pad
    canvas = Image.new("1", (LIVE_WIDTH_PX, canvas_h), 1)
    x = 0 if block.align == "left" else \
        (LIVE_WIDTH_PX - img.width) // 2 if block.align == "center" else \
        (LIVE_WIDTH_PX - img.width)
    # bbox-tight centering keeps visual mass at the band's optical center —
    # cap-height-only centering shifted descender text 2 px lower in v3.
    y_text = top_pad + max(0, (target_h - img.height) // 2)
    canvas.paste(img, (x, y_text))
    if block.style == "underline":
        d = ImageDraw.Draw(canvas)
        rule_y = top_pad + target_h + 1
        d.line([(0, rule_y), (LIVE_WIDTH_PX - 1, rule_y)], fill=0, width=2)
    return canvas


@register("paragraph")
def render_paragraph(block, ctx) -> Image.Image:
    wrapped = wrap_body_text(block.text, fonts=ctx.fonts, max_width_px=LIVE_WIDTH_PX)
    canvas = Image.new("1", (LIVE_WIDTH_PX, BODY_LINE_H * len(wrapped) + 4), 1)
    y = 0
    for line in wrapped:
        line_img = render_body_line(line, fonts=ctx.fonts, max_width_px=LIVE_WIDTH_PX)
        if block.align == "center":
            x = (LIVE_WIDTH_PX - line_img.width) // 2
        elif block.align == "right":
            x = LIVE_WIDTH_PX - line_img.width
        else:
            x = 0
        canvas.paste(line_img, (x, y))
        y += BODY_LINE_H
    return canvas


@register("footer")
def render_footer(block, ctx) -> Image.Image:
    # Plex Sans Bold 16 reads cleanly on the thermal head — Medium 14 (the
    # pre-v0.8 size) was visibly fragile and long footer text was being
    # Lanczos-shrunk to fit width, making "Sources: ..." style runs nearly
    # illegible. Wrapping at the Plex Bold 16 metric keeps each line at the
    # target stroke instead of compressing the whole block.
    size_px = 16
    font = ctx.fonts.display(weight="bold", size_px=size_px)
    fallback = _cjk_fallback(ctx, bold=True)
    lines = wrap_text(
        block.text,
        primary_font=font,
        fallback_font=fallback,
        max_width_px=LIVE_WIDTH_PX,
    )
    line_imgs = [
        supersample_render(
            text=line, font=font, fallback_font=fallback,
            target_size_px=size_px, max_width_px=LIVE_WIDTH_PX,
        )
        for line in lines
    ]
    line_step = max((img.height for img in line_imgs), default=size_px) + 2
    total_h = line_step * len(line_imgs) + 8
    canvas = Image.new("1", (LIVE_WIDTH_PX, total_h), 1)
    for i, img in enumerate(line_imgs):
        canvas.paste(img, ((LIVE_WIDTH_PX - img.width) // 2, 4 + i * line_step))
    return canvas


@register("large_text")
def render_large_text(block, ctx) -> Image.Image:
    sizes = {"xl": 48, "xxl": 80, "xxxl": 128}
    target = sizes[block.size]
    img = supersample_render(
        text=block.text,
        font=ctx.fonts.display(weight="bold", size_px=target),
        fallback_font=_cjk_fallback(ctx, bold=True),
        target_size_px=target, max_width_px=LIVE_WIDTH_PX,
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
    quote_img = supersample_render(
        text=block.text,
        font=ctx.fonts.display(weight="medium", size_px=20),
        fallback_font=_cjk_fallback(ctx, bold=False),
        target_size_px=20, max_width_px=text_w,
    )
    parts = [quote_img]
    if block.attribution:
        attr_img = supersample_render(
            text=f"— {block.attribution}",
            font=ctx.fonts.display(weight="medium", size_px=12),
            fallback_font=_cjk_fallback(ctx, bold=False),
            target_size_px=12, max_width_px=text_w,
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
    # Caps printed thin under the default 2×-Atkinson pipeline because
    # error diffusion thins large solid regions. Render at 4× supersample
    # and ordered (Bayer 8x8) dither: ordered keeps large solid regions
    # saturated, and the higher supersample carries richer luminance into
    # each output pixel. Cap is sized to roughly three lines of body.
    cap_size = 72
    cap_img = supersample_render(
        text=block.first_letter,
        font=ctx.fonts.display(weight="bold", size_px=cap_size),
        fallback_font=_cjk_fallback(ctx, bold=True),
        target_size_px=cap_size, max_width_px=cap_size + 8,
        factor=4, dither="ordered",
    )
    cap_w = cap_img.width
    cap_h = cap_img.height
    indent = cap_w + 6

    # Greedy two-phase wrap by per-line width: indented lines until we clear
    # cap_h, then full width. Atom-aware so CJK/non-Latin runs break per
    # codepoint and Latin words break at whitespace, with widths measured
    # against the actual body fonts (JB Mono Bold + Noto SC fallback).
    lines: list[str] = []
    current: list[str] = []
    current_w = 0
    has_text = False
    line_index = 0

    def max_w_for(idx: int) -> int:
        return LIVE_WIDTH_PX - indent if idx * BODY_LINE_H < cap_h else LIVE_WIDTH_PX

    for atom in iter_atoms(block.rest, fonts=ctx.fonts):
        if atom.isspace():
            if has_text:
                current.append(atom)
                current_w += ctx.fonts.body_atom_width(atom)
            continue
        aw = ctx.fonts.body_atom_width(atom)
        if has_text and current_w + aw > max_w_for(line_index):
            line = "".join(current).rstrip()
            if line:
                lines.append(line)
                line_index += 1
            current = [atom]
            current_w = aw
            has_text = True
        else:
            current.append(atom)
            current_w += aw
            has_text = True
    if current:
        line = "".join(current).rstrip()
        if line:
            lines.append(line)

    h = max(cap_h, len(lines) * BODY_LINE_H) + 4
    canvas = Image.new("1", (LIVE_WIDTH_PX, h), 1)
    canvas.paste(cap_img, (0, 0))
    y = 0
    for line in lines:
        x = indent if (y < cap_h) else 0
        line_img = render_body_line(
            line, fonts=ctx.fonts, max_width_px=LIVE_WIDTH_PX - x,
        )
        canvas.paste(line_img, (x, y))
        y += BODY_LINE_H
    return canvas


@register("code")
def render_code(block, ctx) -> Image.Image:
    # Direct 1× JetBrains Mono draws into a 1-bit canvas without any
    # smoothing — at 14 px most glyphs lose their stroke continuity on the
    # thermal head. Supersample each line at 2× and Atkinson-dither so
    # hinted shapes survive.
    target_px = 14
    line_h = 18
    lines = block.text.split("\n")
    cjk_fb = _cjk_fallback(ctx, bold=False)
    rendered = [
        supersample_render(
            text=line if line else " ",
            font=ctx.fonts.code(size_px=target_px),
            fallback_font=cjk_fb,
            target_size_px=target_px, max_width_px=LIVE_WIDTH_PX,
        )
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
        frag = supersample_render(
            text=run.text,
            font=ctx.fonts.display(weight=weight, size_px=size_target),
            fallback_font=_cjk_fallback(ctx, bold=run.bold),
            target_size_px=size_target,
            max_width_px=LIVE_WIDTH_PX,
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
