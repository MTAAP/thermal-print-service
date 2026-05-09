from printer.render.renderer import render_document
from printer.schema.document import Document


def test_tear_here_renders_with_label(fonts):
    doc = Document.model_validate({"blocks": [
        {"type": "tear_here", "label": "for Sam"}
    ]})
    img = render_document(doc, fonts=fonts)
    assert img.height > 0


def test_feed_height_scales(fonts):
    doc1 = Document.model_validate({"blocks": [{"type": "feed", "lines": 1}]})
    doc5 = Document.model_validate({"blocks": [{"type": "feed", "lines": 5}]})
    img1 = render_document(doc1, fonts=fonts)
    img5 = render_document(doc5, fonts=fonts)
    assert img5.height == 5 * img1.height


def test_cut_renders_zero_height_marker(fonts):
    doc = Document.model_validate({"blocks": [{"type": "cut"}]})
    img = render_document(doc, fonts=fonts)
    # Cut renders a 1-px marker — non-zero but minimal
    assert img.height >= 1
