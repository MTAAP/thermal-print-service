from __future__ import annotations

import base64
import binascii
import io

import qrcode
from PIL import Image, ImageDraw, UnidentifiedImageError

from printer.constants import LIVE_WIDTH_PX, PRINT_HEAD_WIDTH_PX
from printer.render.blocks import register
from printer.render.dither import DITHERS
from printer.render.errors import RenderInputError


@register("qr")
def render_qr(block, ctx) -> Image.Image:
    sizes = {"sm": 192, "md": 320, "lg": 480}
    target = sizes.get(block.size, 320)
    qr = qrcode.QRCode(border=2, error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(block.data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white").convert("1")
    img = img.resize((target, target), Image.Resampling.NEAREST)
    canvas = Image.new("1", (LIVE_WIDTH_PX, target + 4), 1)
    canvas.paste(img, ((LIVE_WIDTH_PX - target) // 2, 2))
    return canvas


@register("image")
def render_image(block, ctx) -> Image.Image:
    try:
        # Default mode (no ``validate=True``) tolerates embedded whitespace
        # and newlines, matching how most clients (curl heredocs, JSON
        # encoders that line-wrap, RFC 4648 §3.1 style) emit base64.
        raw = base64.b64decode(block.png_base64)
    except (binascii.Error, ValueError) as exc:
        raise RenderInputError(
            f"image.png_base64 is not valid base64: {exc}", field="png_base64",
        ) from exc
    try:
        img = Image.open(io.BytesIO(raw))
        img.load()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise RenderInputError(
            f"image.png_base64 did not decode as a readable image: {exc}",
            field="png_base64",
        ) from exc
    target_w = PRINT_HEAD_WIDTH_PX if block.bleed else block.width_px
    if img.width != target_w:
        scale = target_w / img.width
        img = img.resize((target_w, int(img.height * scale)), Image.Resampling.LANCZOS)
    img = DITHERS[block.dither](img)
    if block.bleed:
        return img
    canvas = Image.new("1", (LIVE_WIDTH_PX, img.height), 1)
    if block.align == "left":
        x = 0
    elif block.align == "right":
        x = LIVE_WIDTH_PX - img.width
    else:
        x = (LIVE_WIDTH_PX - img.width) // 2
    canvas.paste(img, (x, 0))
    return canvas


@register("barcode")
def render_barcode(block, ctx) -> Image.Image:
    # Function-local import: python-barcode has heavy import-time side effects;
    # keep it out of the module scope so unrelated renderers don't pay for it.
    import io as _io

    from barcode import EAN8, EAN13, UPCA, Code128
    from barcode.writer import ImageWriter

    classes = {
        "CODE128": Code128,
        "EAN13": EAN13,
        "EAN8": EAN8,
        "UPCA": UPCA,
    }
    cls = classes[block.format]
    buf = _io.BytesIO()
    try:
        bc = cls(block.data, writer=ImageWriter())
        bc.write(buf, options={
            "module_width": 0.4,
            "module_height": 12.0,
            "quiet_zone": 4,
            "write_text": True,
            "font_size": 10,
        })
    except Exception as exc:
        # python-barcode raises various format-specific errors
        # (IllegalCharacterError, NumberOfDigitsError, BarcodeError) — all are
        # signals that the user's ``data`` doesn't satisfy the format's rules.
        # Surface as RenderInputError so the HTTP layer returns 400 instead
        # of 500.
        raise RenderInputError(
            f"barcode.data is not valid for format {block.format}: {exc}",
            field="data",
        ) from exc
    buf.seek(0)
    img = Image.open(buf).convert("L")
    # Threshold to 1-bit (no dither — barcodes need crisp edges).
    img = img.point(lambda v: 0 if v < 128 else 255).convert("1")
    # Resize to live width preserving aspect.
    target_w = LIVE_WIDTH_PX
    if img.width != target_w:
        scale = target_w / img.width
        img = img.resize(
            (target_w, max(1, int(img.height * scale))),
            Image.Resampling.NEAREST,
        )
    return img


@register("ascii_art")
def render_ascii_art(block, ctx) -> Image.Image:
    # ``default`` uses Spleen 8x16 (~72 cols at glyph width 8); ``small``
    # uses Spleen 5x8 (~115 cols at glyph width 5) for dense compositions.
    # ascii_art keeps the tighter mono grid even though body() is now
    # Spleen 12x24 — char-grid art is sized for fixed column counts and
    # 12 px glyphs would reflow most pieces past the live width.
    if block.font == "small":
        font = ctx.fonts.small()
        line_h = 9
    else:
        font = ctx.fonts.mono()
        line_h = 18
    lines = block.text.split("\n") or [""]
    h = line_h * len(lines) + 4
    canvas = Image.new("1", (LIVE_WIDTH_PX, h), 1)
    d = ImageDraw.Draw(canvas)
    for i, line in enumerate(lines):
        d.text((0, i * line_h), line, fill=0, font=font)
    return canvas
