from __future__ import annotations

from PIL import Image, ImageDraw

from printer.constants import LIVE_WIDTH_PX
from printer.render.blocks import register


@register("checklist")
def render_checklist(block, ctx) -> Image.Image:
    font = ctx.fonts.body()
    box_size = 12
    line_h = 18
    h = line_h * len(block.items) + 4
    canvas = Image.new("1", (LIVE_WIDTH_PX, h), 1)
    d = ImageDraw.Draw(canvas)
    for i, item in enumerate(block.items):
        y = i * line_h
        d.rectangle([2, y + 3, 2 + box_size, y + 3 + box_size], outline=0, width=1)
        d.text((2 + box_size + 6, y), item, fill=0, font=font)
    return canvas


@register("kv")
def render_kv(block, ctx) -> Image.Image:
    body = ctx.fonts.body()
    code = ctx.fonts.code(size_px=12)
    line_h = 18
    h = line_h * len(block.pairs) + 4
    canvas = Image.new("1", (LIVE_WIDTH_PX, h), 1)
    d = ImageDraw.Draw(canvas)
    key_col_w = 180
    for i, p in enumerate(block.pairs):
        y = i * line_h
        d.text((0, y), p.key, fill=0, font=body)
        d.text((key_col_w, y), p.value, fill=0, font=code)
    return canvas


@register("bullets")
def render_bullets(block, ctx) -> Image.Image:
    font = ctx.fonts.body()
    line_h = 18
    h = line_h * len(block.items) + 4
    canvas = Image.new("1", (LIVE_WIDTH_PX, h), 1)
    d = ImageDraw.Draw(canvas)
    for i, item in enumerate(block.items):
        y = i * line_h
        d.text((4, y), block.marker, fill=0, font=font)
        d.text((4 + 18, y), item, fill=0, font=font)
    return canvas


@register("numbered")
def render_numbered(block, ctx) -> Image.Image:
    font = ctx.fonts.body()
    line_h = 18
    n = len(block.items)
    # Column width sized to the widest prefix (e.g. "100." for n>=100, "10." for n>=10)
    longest = f"{n}."
    try:
        bbox = font.getbbox(longest)
        prefix_col_w = (bbox[2] - bbox[0]) + 6
    except Exception:
        prefix_col_w = 28
    h = line_h * n + 4
    canvas = Image.new("1", (LIVE_WIDTH_PX, h), 1)
    d = ImageDraw.Draw(canvas)
    for i, item in enumerate(block.items):
        y = i * line_h
        prefix = f"{i + 1}."
        try:
            pb = font.getbbox(prefix)
            pw = pb[2] - pb[0]
        except Exception:
            pw = len(prefix) * 6
        # Right-align the prefix within prefix_col_w
        d.text((prefix_col_w - pw - 4, y), prefix, fill=0, font=font)
        d.text((prefix_col_w, y), item, fill=0, font=font)
    return canvas


@register("table_compact")
def render_table_compact(block, ctx) -> Image.Image:
    font = ctx.fonts.body()
    line_h = 16
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
                w = len(t) * 6
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
