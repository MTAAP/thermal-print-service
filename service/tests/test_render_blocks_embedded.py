import base64
import io

from PIL import Image

from printer.render.renderer import render_document
from printer.schema.document import Document


def test_qr_renders_centered(fonts):
    doc = Document.model_validate({"blocks": [
        {"type": "qr", "data": "https://example.com", "size": "md"}
    ]})
    img = render_document(doc, fonts=fonts)
    assert img.width == 576
    assert img.height > 200


def _png_b64(w: int, h: int) -> str:
    buf = io.BytesIO()
    Image.new("1", (w, h), 1).save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def test_image_at_default_width(fonts):
    doc = Document.model_validate({"blocks": [
        {"type": "image", "png_base64": _png_b64(528, 100)},
    ]})
    img = render_document(doc, fonts=fonts)
    assert img.width == 576
    assert img.height >= 100


def test_image_with_bleed_uses_full_head(fonts):
    doc = Document.model_validate({"blocks": [
        {"type": "image", "png_base64": _png_b64(576, 100), "bleed": True},
    ]})
    img = render_document(doc, fonts=fonts)
    assert img.width == 576


def test_barcode_code128_renders(fonts):
    doc = Document.model_validate({"blocks": [
        {"type": "barcode", "data": "ABC-123-XYZ", "format": "CODE128"}
    ]})
    img = render_document(doc, fonts=fonts)
    assert img.width == 576
    assert img.height > 0


def test_barcode_ean13_renders(fonts):
    # EAN13 needs exactly 12 digits (the 13th is the check digit added by the lib)
    doc = Document.model_validate({"blocks": [
        {"type": "barcode", "data": "123456789012", "format": "EAN13"}
    ]})
    img = render_document(doc, fonts=fonts)
    assert img.width == 576


def test_ascii_art_default_renders(fonts):
    art = "  /\\_/\\\n ( o.o )\n  > ^ <"
    doc = Document.model_validate({"blocks": [
        {"type": "ascii_art", "text": art}
    ]})
    img = render_document(doc, fonts=fonts)
    assert img.width == 576
    # Three lines × 14 px = 42 px + padding
    assert img.height >= 42


def test_ascii_art_small_uses_smaller_font(fonts):
    """``font: "small"`` switches from Spleen 8x16 to Spleen 5x8, so a
    multi-line composition is shorter (smaller line height) AND the rendered
    glyphs occupy a different raster than the default font."""
    art = "line1\nline2\nline3"
    big = render_document(Document.model_validate({"blocks": [
        {"type": "ascii_art", "text": art, "font": "default"}
    ]}), fonts=fonts)
    small = render_document(Document.model_validate({"blocks": [
        {"type": "ascii_art", "text": art, "font": "small"}
    ]}), fonts=fonts)
    assert small.height < big.height
    # Different fonts produce different raster output. Identical bytes would
    # mean ``font: "small"`` regressed to reusing the default face.
    assert small.tobytes() != big.tobytes()


def test_ascii_art_small_fits_wide_composition(fonts):
    """Spleen 5x8 should accommodate denser horizontal compositions than
    the default Spleen 8x16 face. A ~100-column line should not clip the
    canvas at 576 px."""
    wide = "x" * 100
    img = render_document(Document.model_validate({"blocks": [
        {"type": "ascii_art", "text": wide, "font": "small"}
    ]}), fonts=fonts)
    assert img.width == 576
    # 100 chars at 5 px = 500 px — within 576. Some pixels must be black.
    assert img.histogram()[0] > 0


def test_qr_with_caption_renders_taller_than_without(fonts):
    from printer.render.blocks import renderer_for
    from printer.render.renderer import RenderContext
    from printer.schema.blocks import QrBlock

    ctx = RenderContext(fonts=fonts, max_decoded_image_pixels=10_000_000)
    fn = renderer_for("qr")
    plain = fn(QrBlock(type="qr", data="x"), ctx)
    captioned = fn(QrBlock(type="qr", data="x", caption="agenda"), ctx)
    assert captioned.height > plain.height


def test_image_with_caption_renders_taller_than_without(fonts):
    from base64 import b64encode
    from io import BytesIO

    from PIL import Image as PILImage

    from printer.render.blocks import renderer_for
    from printer.render.renderer import RenderContext
    from printer.schema.blocks import ImageBlock

    ctx = RenderContext(fonts=fonts, max_decoded_image_pixels=10_000_000)
    fn = renderer_for("image")
    buf = BytesIO()
    PILImage.new("1", (528, 100), 1).save(buf, format="PNG")
    png_b64 = b64encode(buf.getvalue()).decode("ascii")
    plain = fn(ImageBlock(type="image", png_base64=png_b64), ctx)
    captioned = fn(ImageBlock(type="image", png_base64=png_b64, caption="hello"), ctx)
    assert captioned.height > plain.height
