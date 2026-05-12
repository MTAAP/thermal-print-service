from __future__ import annotations

from PIL import Image, ImageDraw

from printer.constants import LIVE_WIDTH_PX
from printer.render.blocks import register
from printer.render.typography import (
    BODY_LINE_H,
    render_body_line,
    render_prose_line,
    wrap_body_text,
    wrap_prose_text,
)


def _wrap_prose(text: str, *, fonts, width_px: int) -> list[str]:
    return wrap_prose_text(text, fonts=fonts, max_width_px=width_px)


@register("checklist")
def render_checklist(block, ctx) -> Image.Image:
    box_size = 16
    text_x = 2 + box_size + 8
    text_w = LIVE_WIDTH_PX - text_x
    wrapped = [_wrap_prose(item, fonts=ctx.fonts, width_px=text_w) for item in block.items]
    total_lines = sum(len(lines) for lines in wrapped)
    h = BODY_LINE_H * total_lines + 4
    canvas = Image.new("1", (LIVE_WIDTH_PX, h), 1)
    d = ImageDraw.Draw(canvas)
    y = 0
    for lines in wrapped:
        d.rectangle([2, y + 4, 2 + box_size, y + 4 + box_size], outline=0, width=1)
        for li, line in enumerate(lines):
            line_img = render_prose_line(line, fonts=ctx.fonts, max_width_px=text_w)
            canvas.paste(line_img, (text_x, y + li * BODY_LINE_H))
        y += BODY_LINE_H * len(lines)
    return canvas


@register("kv")
def render_kv(block, ctx) -> Image.Image:
    """Keys in proportional prose, values in monospace.

    Keys read as labels — proportional Plex Sans Medium gives them
    'literary' weight. Values are data (versions, paths, hashes) and
    stay in JetBrains Mono Bold for column alignment and predictable
    glyph width.
    """
    key_col_w = 200
    key_text_w = key_col_w - 8
    value_text_w = LIVE_WIDTH_PX - key_col_w
    pair_renders: list[tuple[list[str], list[str]]] = []
    for p in block.pairs:
        key_lines = wrap_prose_text(
            p.key, fonts=ctx.fonts, max_width_px=key_text_w,
        )
        value_lines = wrap_body_text(
            p.value, fonts=ctx.fonts, max_width_px=value_text_w,
        )
        pair_renders.append((key_lines, value_lines))
    total_lines = sum(max(len(k), len(v)) for k, v in pair_renders)
    h = BODY_LINE_H * total_lines + 4
    canvas = Image.new("1", (LIVE_WIDTH_PX, h), 1)
    y = 0
    for key_lines, value_lines in pair_renders:
        rows = max(len(key_lines), len(value_lines))
        for li in range(rows):
            row_y = y + li * BODY_LINE_H
            if li < len(key_lines):
                key_img = render_prose_line(
                    key_lines[li], fonts=ctx.fonts, max_width_px=key_text_w,
                )
                canvas.paste(key_img, (0, row_y))
            if li < len(value_lines):
                val_img = render_body_line(
                    value_lines[li], fonts=ctx.fonts, max_width_px=value_text_w,
                )
                canvas.paste(val_img, (key_col_w, row_y))
        y += BODY_LINE_H * rows
    return canvas


@register("bullets")
def render_bullets(block, ctx) -> Image.Image:
    marker_x = 4
    text_x = marker_x + 24
    text_w = LIVE_WIDTH_PX - text_x
    wrapped = [_wrap_prose(item, fonts=ctx.fonts, width_px=text_w) for item in block.items]
    total_lines = sum(len(lines) for lines in wrapped)
    h = BODY_LINE_H * total_lines + 4
    canvas = Image.new("1", (LIVE_WIDTH_PX, h), 1)
    y = 0
    for lines in wrapped:
        # Marker stays in the mono body face so the glyph weight reads
        # cleanly against the proportional prose item text.
        marker_img = render_body_line(
            block.marker, fonts=ctx.fonts, max_width_px=text_x - marker_x,
        )
        canvas.paste(marker_img, (marker_x, y))
        for li, line in enumerate(lines):
            line_img = render_prose_line(line, fonts=ctx.fonts, max_width_px=text_w)
            canvas.paste(line_img, (text_x, y + li * BODY_LINE_H))
        y += BODY_LINE_H * len(lines)
    return canvas


@register("numbered")
def render_numbered(block, ctx) -> Image.Image:
    n = len(block.items)
    # Measure the widest prefix actually rendered — proportional digits are
    # not uniform like the prior monospace assumption (BODY_GLYPH_PX).
    longest_prefix = f"{n}."
    sample_prefix = render_prose_line(
        longest_prefix, fonts=ctx.fonts, max_width_px=LIVE_WIDTH_PX,
    )
    prefix_col_w = sample_prefix.width + 12
    text_w = LIVE_WIDTH_PX - prefix_col_w
    wrapped = [_wrap_prose(item, fonts=ctx.fonts, width_px=text_w) for item in block.items]
    total_lines = sum(len(lines) for lines in wrapped)
    h = BODY_LINE_H * total_lines + 4
    canvas = Image.new("1", (LIVE_WIDTH_PX, h), 1)
    y = 0
    for i, lines in enumerate(wrapped):
        prefix = f"{i + 1}."
        prefix_img = render_prose_line(
            prefix, fonts=ctx.fonts, max_width_px=prefix_col_w,
        )
        canvas.paste(prefix_img, (prefix_col_w - prefix_img.width - 4, y))
        for li, line in enumerate(lines):
            line_img = render_prose_line(line, fonts=ctx.fonts, max_width_px=text_w)
            canvas.paste(line_img, (prefix_col_w, y + li * BODY_LINE_H))
        y += BODY_LINE_H * len(lines)
    return canvas


@register("table_compact")
def render_table_compact(block, ctx) -> Image.Image:
    """Cells render in the mono body face. Tables on receipts are typically
    data: numbers, version strings, ids — column alignment matters more
    than literary weight, so cells stay monospaced even though paragraph
    and lists are now proportional."""
    rows = block.rows
    cols = len(rows[0])
    headers = block.headers
    line_h = BODY_LINE_H

    all_rows: list[list[str]] = list(rows)
    if headers is not None:
        all_rows.append(list(headers))

    rendered: dict[tuple[int, int], Image.Image] = {}
    col_widths: list[int] = [0] * cols
    for r_idx, row in enumerate(all_rows):
        for c, text in enumerate(row):
            img = render_body_line(text, fonts=ctx.fonts, max_width_px=LIVE_WIDTH_PX)
            rendered[(r_idx, c)] = img
            if img.width > col_widths[c]:
                col_widths[c] = img.width
    col_widths = [w + 12 for w in col_widths]

    total_w = sum(col_widths)
    if total_w > LIVE_WIDTH_PX:
        scale = LIVE_WIDTH_PX / total_w
        col_widths = [max(1, int(w * scale)) for w in col_widths]

    n_data_rows = len(rows)
    n_lines = n_data_rows + (1 if headers else 0)
    rule_h = 6 if headers else 0
    h = line_h * n_lines + rule_h + 4
    canvas = Image.new("1", (LIVE_WIDTH_PX, h), 1)
    d = ImageDraw.Draw(canvas)

    def paste_row(row_idx: int, y_pos: int) -> None:
        x = 0
        for c in range(cols):
            img = rendered[(row_idx, c)]
            if img.width > col_widths[c] - 12:
                cell = render_body_line(
                    all_rows[row_idx][c], fonts=ctx.fonts,
                    max_width_px=col_widths[c] - 12,
                )
            else:
                cell = img
            canvas.paste(cell, (x, y_pos))
            x += col_widths[c]

    y = 0
    if headers is not None:
        paste_row(len(rows), y)
        y += line_h
        d.line([(0, y + 1), (LIVE_WIDTH_PX - 1, y + 1)], fill=0, width=1)
        y += rule_h
    for r_idx in range(n_data_rows):
        paste_row(r_idx, y)
        y += line_h
    return canvas
