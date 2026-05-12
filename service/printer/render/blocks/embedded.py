from __future__ import annotations

import base64
import binascii
import io

import qrcode
from PIL import Image, ImageDraw, UnidentifiedImageError

from printer.constants import LIVE_WIDTH_PX, PRINT_HEAD_WIDTH_PX
from printer.render.blocks import register
from printer.render.dither import DITHERS
from printer.render.errors import RenderInputError, RenderResourceLimitError


@register("qr")
def render_qr(block, ctx) -> Image.Image:
    from printer.render.typography import render_body_line

    sizes = {"sm": 192, "md": 320, "lg": 480}
    target = sizes.get(block.size, 320)
    qr = qrcode.QRCode(border=2, error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(block.data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white").convert("1")
    img = img.resize((target, target), Image.Resampling.NEAREST)
    caption_img = None
    if block.caption:
        caption_img = render_body_line(
            block.caption, fonts=ctx.fonts, max_width_px=LIVE_WIDTH_PX,
        )
    caption_band = (caption_img.height + 4) if caption_img is not None else 0
    canvas = Image.new("1", (LIVE_WIDTH_PX, target + 4 + caption_band), 1)
    canvas.paste(img, ((LIVE_WIDTH_PX - target) // 2, 2))
    if caption_img is not None:
        cx = (LIVE_WIDTH_PX - caption_img.width) // 2
        canvas.paste(caption_img, (cx, target + 4))
    return canvas


@register("image")
def render_image(block, ctx) -> Image.Image:
    from printer.render.typography import render_body_line

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
        img: Image.Image = Image.open(io.BytesIO(raw))
        if img.width * img.height > ctx.max_decoded_image_pixels:
            raise RenderResourceLimitError("max_decoded_image_pixels")
        img.load()
    except RenderResourceLimitError:
        raise
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
    caption_img = None
    if block.caption:
        caption_img = render_body_line(
            block.caption, fonts=ctx.fonts, max_width_px=LIVE_WIDTH_PX,
        )
    caption_band = (caption_img.height + 4) if caption_img is not None else 0
    if block.bleed:
        if caption_img is None:
            return img
        canvas = Image.new("1", (PRINT_HEAD_WIDTH_PX, img.height + caption_band), 1)
        canvas.paste(img, (0, 0))
        cx = (PRINT_HEAD_WIDTH_PX - caption_img.width) // 2
        canvas.paste(caption_img, (cx, img.height + 4))
        return canvas
    canvas = Image.new("1", (LIVE_WIDTH_PX, img.height + caption_band), 1)
    if block.align == "left":
        x = 0
    elif block.align == "right":
        x = LIVE_WIDTH_PX - img.width
    else:
        x = (LIVE_WIDTH_PX - img.width) // 2
    canvas.paste(img, (x, 0))
    if caption_img is not None:
        cx = (LIVE_WIDTH_PX - caption_img.width) // 2
        canvas.paste(caption_img, (cx, img.height + 4))
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
    # Bitmap fonts at native size print as 1-px strokes (0.125 mm on the
    # 8-dpmm head). That's at or below the head's reliable activation
    # threshold — strokes fragment and small-tier glyphs read as washed-out
    # patches on real paper. Render to a half-width canvas at native size,
    # then NEAREST-upsample 2× so each bitmap pixel becomes a 2×2 dot block:
    # strokes go from 0.125 mm to 0.25 mm (solidly above the threshold), and
    # cell sizes double for legibility.
    #
    # Effective cell sizes after upsampling:
    #   default (Spleen 8×16 × 2): 16×32 px → 2×4 mm → ~33 cols across the head
    #   small   (Spleen 5×8  × 2): 10×16 px → 1.25×2 mm → ~52 cols
    #
    # The trade-off is fewer columns vs. the prior native sizes (was ~72 /
    # ~115). Density-over-legibility was the bug; legibility wins.
    if block.font == "small":
        font = ctx.fonts.small()
        native_line_h = 8
    else:
        font = ctx.fonts.mono()
        native_line_h = 16
    lines = block.text.split("\n") or [""]
    native_w = LIVE_WIDTH_PX // 2
    native_h = native_line_h * len(lines)
    native = Image.new("1", (native_w, native_h), 1)
    d = ImageDraw.Draw(native)
    for i, line in enumerate(lines):
        d.text((0, i * native_line_h), line, fill=0, font=font)
    scaled = native.resize((native_w * 2, native_h * 2), Image.Resampling.NEAREST)
    top_pad = 2
    bottom_pad = 2
    canvas = Image.new("1", (LIVE_WIDTH_PX, scaled.height + top_pad + bottom_pad), 1)
    canvas.paste(scaled, (0, top_pad))
    return canvas
