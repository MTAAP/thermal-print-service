from __future__ import annotations

import textwrap

from PIL import Image, ImageDraw

from printer.constants import LIVE_WIDTH_PX
from printer.render.blocks import register

# Spleen 12x24 body grid: 12 px wide glyphs, 24 px native cell, 26 px line
# step (24 + 2 px lead). All list blocks share these constants so item
# wrap widths and inter-item spacing stay aligned across the renderer.
_BODY_GLYPH_PX = 12
_BODY_LINE_H = 26


def _wrap_item(text: str, *, width_px: int) -> list[str]:
    chars = max(8, width_px // _BODY_GLYPH_PX)
    return textwrap.wrap(text, width=chars) or [text]


@register("checklist")
def render_checklist(block, ctx) -> Image.Image:
    font = ctx.fonts.body()
    box_size = 16
    text_x = 2 + box_size + 8
    text_w = LIVE_WIDTH_PX - text_x
    wrapped = [_wrap_item(item, width_px=text_w) for item in block.items]
    total_lines = sum(len(lines) for lines in wrapped)
    h = _BODY_LINE_H * total_lines + 4
    canvas = Image.new("1", (LIVE_WIDTH_PX, h), 1)
    d = ImageDraw.Draw(canvas)
    y = 0
    for lines in wrapped:
        d.rectangle([2, y + 4, 2 + box_size, y + 4 + box_size], outline=0, width=1)
        for li, line in enumerate(lines):
            d.text((text_x, y + li * _BODY_LINE_H), line, fill=0, font=font)
        y += _BODY_LINE_H * len(lines)
    return canvas


@register("kv")
def render_kv(block, ctx) -> Image.Image:
    body = ctx.fonts.body()
    # JetBrains Mono at 18 px sits visually between the 12 px body grid and
    # display sizes, keeping the value column legible next to the larger
    # 24 px body keys without dwarfing them.
    code = ctx.fonts.code(size_px=18)
    key_col_w = 200
    key_text_w = key_col_w - 8  # gutter so wrapped keys don't kiss the value column
    value_text_w = LIVE_WIDTH_PX - key_col_w
    # Code font is roughly 11 px wide at size 18 — slightly narrower than
    # the 12 px body grid, so values fit a couple more chars per line.
    value_chars = max(8, value_text_w // 11)
    pair_renders: list[tuple[list[str], list[str]]] = []
    for p in block.pairs:
        key_lines = _wrap_item(p.key, width_px=key_text_w)
        value_lines = textwrap.wrap(p.value, width=value_chars) or [p.value]
        pair_renders.append((key_lines, value_lines))
    total_lines = sum(max(len(k), len(v)) for k, v in pair_renders)
    h = _BODY_LINE_H * total_lines + 4
    canvas = Image.new("1", (LIVE_WIDTH_PX, h), 1)
    d = ImageDraw.Draw(canvas)
    y = 0
    for key_lines, value_lines in pair_renders:
        rows = max(len(key_lines), len(value_lines))
        for li in range(rows):
            row_y = y + li * _BODY_LINE_H
            if li < len(key_lines):
                d.text((0, row_y), key_lines[li], fill=0, font=body)
            if li < len(value_lines):
                d.text((key_col_w, row_y), value_lines[li], fill=0, font=code)
        y += _BODY_LINE_H * rows
    return canvas


@register("bullets")
def render_bullets(block, ctx) -> Image.Image:
    font = ctx.fonts.body()
    marker_x = 4
    text_x = marker_x + 24
    text_w = LIVE_WIDTH_PX - text_x
    wrapped = [_wrap_item(item, width_px=text_w) for item in block.items]
    total_lines = sum(len(lines) for lines in wrapped)
    h = _BODY_LINE_H * total_lines + 4
    canvas = Image.new("1", (LIVE_WIDTH_PX, h), 1)
    d = ImageDraw.Draw(canvas)
    y = 0
    for lines in wrapped:
        d.text((marker_x, y), block.marker, fill=0, font=font)
        for li, line in enumerate(lines):
            d.text((text_x, y + li * _BODY_LINE_H), line, fill=0, font=font)
        y += _BODY_LINE_H * len(lines)
    return canvas


@register("numbered")
def render_numbered(block, ctx) -> Image.Image:
    font = ctx.fonts.body()
    n = len(block.items)
    longest = f"{n}."
    try:
        bbox = font.getbbox(longest)
        prefix_col_w = (bbox[2] - bbox[0]) + 8
    except Exception:
        prefix_col_w = len(longest) * _BODY_GLYPH_PX + 8
    text_w = LIVE_WIDTH_PX - prefix_col_w
    wrapped = [_wrap_item(item, width_px=text_w) for item in block.items]
    total_lines = sum(len(lines) for lines in wrapped)
    h = _BODY_LINE_H * total_lines + 4
    canvas = Image.new("1", (LIVE_WIDTH_PX, h), 1)
    d = ImageDraw.Draw(canvas)
    y = 0
    for i, lines in enumerate(wrapped):
        prefix = f"{i + 1}."
        try:
            pb = font.getbbox(prefix)
            pw = pb[2] - pb[0]
        except Exception:
            pw = len(prefix) * _BODY_GLYPH_PX
        d.text((prefix_col_w - pw - 4, y), prefix, fill=0, font=font)
        for li, line in enumerate(lines):
            d.text((prefix_col_w, y + li * _BODY_LINE_H), line, fill=0, font=font)
        y += _BODY_LINE_H * len(lines)
    return canvas


@register("table_compact")
def render_table_compact(block, ctx) -> Image.Image:
    font = ctx.fonts.body()
    line_h = 24
    rows = block.rows
    cols = len(rows[0])
    headers = block.headers

    # Compute column widths from longest cell per column.
    col_widths: list[int] = []
    for c in range(cols):
        cell_texts = [r[c] for r in rows]
        if headers is not None:
            cell_texts = cell_texts + [headers[c]]
        widest = 0
        for t in cell_texts:
            try:
                bb = font.getbbox(t)
                w = bb[2] - bb[0]
            except Exception:
                w = len(t) * _BODY_GLYPH_PX
            if w > widest:
                widest = w
        col_widths.append(widest + 12)  # 12 px gutter

    total_w = sum(col_widths)
    if total_w > LIVE_WIDTH_PX:
        # Scale down proportionally so the table still fits the live width.
        scale = LIVE_WIDTH_PX / total_w
        col_widths = [max(1, int(w * scale)) for w in col_widths]

    n_lines = len(rows) + (1 if headers else 0)
    rule_h = 6 if headers else 0
    h = line_h * n_lines + rule_h + 4
    canvas = Image.new("1", (LIVE_WIDTH_PX, h), 1)
    d = ImageDraw.Draw(canvas)

    y = 0
    if headers is not None:
        x = 0
        for c in range(cols):
            d.text((x, y), headers[c], fill=0, font=font)
            x += col_widths[c]
        y += line_h
        d.line([(0, y + 1), (LIVE_WIDTH_PX - 1, y + 1)], fill=0, width=1)
        y += rule_h
    for r in rows:
        x = 0
        for c in range(cols):
            d.text((x, y), r[c], fill=0, font=font)
            x += col_widths[c]
        y += line_h
    return canvas
