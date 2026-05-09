from printer.render.renderer import render_document
from printer.schema.document import Document


def test_minimal_briefing_renders(fonts):
    doc = Document.model_validate({
        "document_type": "briefing",
        "blocks": [
            {"type": "header", "text": "Friday, May 9", "style": "minimal"},
            {"type": "paragraph", "text": "06:30 . Anytown . 14C", "align": "center"},
            {"type": "rule", "style": "dashed"},
            {"type": "section_title", "text": "TODAY"},
            {"type": "checklist", "items": ["Draft Q3 report", "Reply to support ticket"]},
            {"type": "qr", "data": "https://example.com/agenda", "caption": "agenda"},
            {"type": "footer", "text": "have a good one"},
        ],
    })
    img = render_document(doc, fonts=fonts)
    assert img.mode == "1"
    assert img.width == 576
    assert img.height > 200


def test_unimplemented_block_type_falls_back_to_placeholder(fonts):
    # large_text has no renderer in Phase 3 — placeholder substituted.
    doc = Document.model_validate({"blocks": [
        {"type": "large_text", "text": "WELCOME"},
    ]})
    img = render_document(doc, fonts=fonts)
    assert img.height > 0  # placeholder produces a non-zero canvas
