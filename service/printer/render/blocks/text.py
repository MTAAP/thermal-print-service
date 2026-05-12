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


def _place_horizontally(img_w: int, align: str, *, margin: int = 0) -> int:
    if align == "center":
        return (LIVE_WIDTH_PX - img_w) // 2
    if align == "right":
        return LIVE_WIDTH_PX - img_w - margin
    return margin


@register("header")
def render_header(block, ctx) -> Image.Image:
    band_h = 56
    bottom_pad = 12
    header_font = ctx.fonts.display(weight="bold", size_px=28)
    title = supersample_render(
        text=block.text, font=header_font,
        fallback_font=_cjk_fallback(ctx, bold=True),
        target_size_px=28, max_width_px=LIVE_WIDTH_PX - 24,
    )
    subtitle_img = None
    if block.subtitle:
        subtitle_img = supersample_render(
            text=block.subtitle,
            font=ctx.fonts.display(weight="medium", size_px=16),
            fallback_font=_cjk_fallback(ctx, bold=False),
            target_size_px=16, max_width_px=LIVE_WIDTH_PX - 24,
        )
    if block.style == "inverse_band":
        return _render_header_inverse_band(
            title=title, subtitle_img=subtitle_img,
            align=block.align, band_h=band_h, bottom_pad=bottom_pad,
        )
    if block.style == "ornamental":
        return _render_header_ornamental(
            title=title, subtitle_img=subtitle_img,
            align=block.align, ctx=ctx, bottom_pad=bottom_pad,
        )
    return _render_header_minimal(
        title=title, subtitle_img=subtitle_img, align=block.align,
        bottom_pad=bottom_pad,
    )


def _render_header_inverse_band(*, title, subtitle_img, align, band_h, bottom_pad):
    """White-on-black title band. Subtitle (if any) sits below the band in a
    smaller medium weight."""
    sub_band_h = (subtitle_img.height + 8) if subtitle_img is not None else 0
    canvas = Image.new("1", (LIVE_WIDTH_PX, band_h + sub_band_h + bottom_pad), 1)
    ImageDraw.Draw(canvas).rectangle(
        [0, 0, LIVE_WIDTH_PX - 1, band_h - 1], fill=0,
    )
    inv = title.point(lambda v: 255 if v == 0 else 0).convert("1")
    if align == "center":
        x = (LIVE_WIDTH_PX - inv.width) // 2
    elif align == "right":
        x = LIVE_WIDTH_PX - inv.width - 12
    else:
        x = 12
    canvas.paste(inv, (x, max(0, (band_h - inv.height) // 2)))
    if subtitle_img is not None:
        sx = (LIVE_WIDTH_PX - subtitle_img.width) // 2
        canvas.paste(subtitle_img, (sx, band_h + 4))
    return canvas


def _render_header_ornamental(*, title, subtitle_img, align, ctx, bottom_pad):
    """Title flanked by ◆ glyphs at display weight. The composition is
    centered regardless of ``align`` — ornamental decoration implies symmetry.
    Subtitle (if any) renders below the title row.
    """
    top_pad = 8
    ornament_glyph = "◆"
    orn_size_px = 20
    ornament_font = ctx.fonts.display(weight="bold", size_px=orn_size_px)
    orn = supersample_render(
        text=ornament_glyph,
        font=ornament_font,
        fallback_font=None,
        target_size_px=orn_size_px, max_width_px=LIVE_WIDTH_PX,
    )
    gap = 12
    row_w = title.width + (orn.width + gap) * 2
    sub_h = subtitle_img.height + 6 if subtitle_img is not None else 0
    row_h = max(title.height, orn.height)
    canvas_h = top_pad + row_h + sub_h + bottom_pad
    canvas = Image.new("1", (LIVE_WIDTH_PX, canvas_h), 1)
    if row_w <= LIVE_WIDTH_PX:
        start_x = (LIVE_WIDTH_PX - row_w) // 2
        canvas.paste(orn, (start_x, top_pad + row_h - orn.height))
        canvas.paste(title, (start_x + orn.width + gap, top_pad + row_h - title.height))
        canvas.paste(
            orn,
            (start_x + orn.width + gap + title.width + gap, top_pad + row_h - orn.height),
        )
    else:
        # Title too wide for inline ornaments — fall back to centered title only.
        canvas.paste(title, (_place_horizontally(title.width, align), top_pad))
    if subtitle_img is not None:
        sx = (LIVE_WIDTH_PX - subtitle_img.width) // 2
        sy = top_pad + row_h + 6
        canvas.paste(subtitle_img, (sx, sy))
    return canvas


def _render_header_minimal(*, title, subtitle_img, align, bottom_pad):
    """Title above a hairline rule, no inverse band. Reads as understated
    heading. Subtitle (if any) sits below the rule.
    """
    top_pad = 4
    rule_gap = 4
    rule_h = 1
    sub_h = subtitle_img.height + 6 if subtitle_img is not None else 0
    canvas_h = top_pad + title.height + rule_gap + rule_h + sub_h + bottom_pad
    canvas = Image.new("1", (LIVE_WIDTH_PX, canvas_h), 1)
    canvas.paste(title, (_place_horizontally(title.width, align), top_pad))
    rule_y = top_pad + title.height + rule_gap
    ImageDraw.Draw(canvas).line(
        [(0, rule_y), (LIVE_WIDTH_PX - 1, rule_y)], fill=0, width=rule_h,
    )
    if subtitle_img is not None:
        sx = _place_horizontally(subtitle_img.width, align)
        sy = rule_y + rule_h + 6
        canvas.paste(subtitle_img, (sx, sy))
    return canvas


@register("section_title")
def render_section_title(block, ctx) -> Image.Image:
    target_h = 36
    top_pad = 4
    bottom_pad = 17
    title_font = ctx.fonts.display(weight="medium", size_px=22)
    img = supersample_render(
        text=block.text, font=title_font,
        fallback_font=_cjk_fallback(ctx, bold=False),
        target_size_px=22, max_width_px=LIVE_WIDTH_PX,
    )
    if block.style == "inverse":
        return _render_section_title_inverse(
            img=img, align=block.align, top_pad=top_pad, bottom_pad=bottom_pad,
        )
    if block.style == "rule_above":
        return _render_section_title_rule_above(
            img=img, align=block.align, target_h=target_h,
            top_pad=top_pad, bottom_pad=bottom_pad,
        )
    # Default: underline.
    canvas_h = top_pad + target_h + bottom_pad
    canvas = Image.new("1", (LIVE_WIDTH_PX, canvas_h), 1)
    x = 0 if block.align == "left" else \
        (LIVE_WIDTH_PX - img.width) // 2 if block.align == "center" else \
        (LIVE_WIDTH_PX - img.width)
    y_text = top_pad + max(0, (target_h - img.height) // 2)
    canvas.paste(img, (x, y_text))
    d = ImageDraw.Draw(canvas)
    rule_y = top_pad + target_h + 1
    d.line([(0, rule_y), (LIVE_WIDTH_PX - 1, rule_y)], fill=0, width=2)
    return canvas


def _render_section_title_inverse(*, img, align, top_pad, bottom_pad):
    """White-on-black band sized to fit the title plus padding. Quieter than
    header.inverse_band — narrower band height and smaller text."""
    band_h = max(36, img.height + 12)
    canvas = Image.new("1", (LIVE_WIDTH_PX, top_pad + band_h + bottom_pad), 1)
    ImageDraw.Draw(canvas).rectangle(
        [0, top_pad, LIVE_WIDTH_PX - 1, top_pad + band_h - 1], fill=0,
    )
    inv = img.point(lambda v: 255 if v == 0 else 0).convert("1")
    if align == "center":
        x = (LIVE_WIDTH_PX - inv.width) // 2
    elif align == "right":
        x = LIVE_WIDTH_PX - inv.width - 12
    else:
        x = 12
    canvas.paste(inv, (x, top_pad + (band_h - inv.height) // 2))
    return canvas


def _render_section_title_rule_above(*, img, align, target_h, top_pad, bottom_pad):
    """Hairline rule then the title — 'chapter break' treatment."""
    rule_h = 1
    rule_gap = 8
    canvas_h = top_pad + rule_h + rule_gap + target_h + bottom_pad
    canvas = Image.new("1", (LIVE_WIDTH_PX, canvas_h), 1)
    rule_y = top_pad
    ImageDraw.Draw(canvas).line(
        [(0, rule_y), (LIVE_WIDTH_PX - 1, rule_y)], fill=0, width=rule_h,
    )
    if align == "center":
        x = (LIVE_WIDTH_PX - img.width) // 2
    elif align == "right":
        x = LIVE_WIDTH_PX - img.width
    else:
        x = 0
    y_text = top_pad + rule_h + rule_gap + max(0, (target_h - img.height) // 2)
    canvas.paste(img, (x, y_text))
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
    top_pad = 8
    bottom_pad = 4
    total_h = line_step * len(line_imgs) + top_pad + bottom_pad
    canvas = Image.new("1", (LIVE_WIDTH_PX, total_h), 1)
    for i, img in enumerate(line_imgs):
        canvas.paste(img, ((LIVE_WIDTH_PX - img.width) // 2, top_pad + i * line_step))
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
        # 14 px (was 12) — 12 was below the thermal-safe stroke threshold,
        # same precedent as the footer 14→16 bump.
        attr_img = supersample_render(
            text=f"— {block.attribution}",
            font=ctx.fonts.display(weight="medium", size_px=14),
            fallback_font=_cjk_fallback(ctx, bold=False),
            target_size_px=14, max_width_px=text_w,
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
    # Size enum: sm 14, md 16 (default, thermal-safe), lg 18. Previous fixed
    # 14 was below the thermal-safe stroke threshold for code.
    sizes = {"sm": 14, "md": 16, "lg": 18}
    target_px = sizes.get(block.size, 16)
    line_h = target_px + 4
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
    line_gap = 4
    fragments_per_line: list[list[Image.Image]] = [[]]
    line_widths: list[int] = [0]
    line_heights: list[int] = [0]
    for run in block.runs:
        weight = "bold" if run.bold else "medium"
        # sm bumped 12 → 14: 12 px Plex Medium reads as fragile on thermal,
        # same precedent as the footer 14→16 bump.
        size_target = {"sm": 14, "md": 18, "lg": 28}.get(run.size, 18)
        frag = supersample_render(
            text=run.text,
            font=ctx.fonts.display(weight=weight, size_px=size_target),
            fallback_font=_cjk_fallback(ctx, bold=run.bold),
            target_size_px=size_target,
            max_width_px=LIVE_WIDTH_PX,
        )
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
            y_off = line_h - frag.height
            canvas.paste(frag, (x, y + y_off))
            x += frag.width
        y += line_h + line_gap
    return canvas
