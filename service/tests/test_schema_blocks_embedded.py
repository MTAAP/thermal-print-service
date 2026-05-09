import pytest

from printer.schema.document import Document


def test_qr_minimal():
    Document.model_validate({"blocks": [{"type": "qr", "data": "https://x"}]})


def test_image_default_dither_is_atkinson():
    doc = Document.model_validate({"blocks": [{"type": "image", "png_base64": "AA"}]})
    assert doc.blocks[0].dither == "atkinson"
    assert doc.blocks[0].width_px == 528
    assert doc.blocks[0].bleed is False


def test_image_bleed_with_align_rejected():
    # align defaults to "left" so plain bleed=true is OK
    Document.model_validate({"blocks": [
        {"type": "image", "png_base64": "AA", "bleed": True}
    ]})
    # bleed=true + non-default align is rejected
    with pytest.raises(Exception):
        Document.model_validate({"blocks": [
            {"type": "image", "png_base64": "AA", "bleed": True, "align": "center"}
        ]})


def test_image_width_px_range():
    Document.model_validate({"blocks": [
        {"type": "image", "png_base64": "AA", "width_px": 1}
    ]})
    Document.model_validate({"blocks": [
        {"type": "image", "png_base64": "AA", "width_px": 528}
    ]})
    with pytest.raises(Exception):
        Document.model_validate({"blocks": [
            {"type": "image", "png_base64": "AA", "width_px": 600}
        ]})


def test_barcode_format_enum():
    Document.model_validate({"blocks": [{"type": "barcode", "data": "12345678", "format": "EAN8"}]})
    with pytest.raises(Exception):
        Document.model_validate({"blocks": [{"type": "barcode", "data": "x", "format": "QRCODE"}]})
