import pytest

from printer.schema.document import Document


def _doc_with(block: dict) -> Document:
    return Document.model_validate({"blocks": [block]})


def test_epigraph_minimal():
    _doc_with({"type": "epigraph", "text": "Whereof one cannot speak."})


def test_epigraph_with_attribution():
    _doc_with({
        "type": "epigraph",
        "text": "Whereof one cannot speak, thereof one must be silent.",
        "attribution": "Wittgenstein",
    })


def test_epigraph_rejects_empty_text():
    with pytest.raises(Exception):
        _doc_with({"type": "epigraph", "text": ""})


def test_epigraph_rejects_align():
    """epigraph has intrinsic placement; align is not in the allow-list."""
    with pytest.raises(Exception):
        _doc_with({"type": "epigraph", "text": "x", "align": "center"})


def test_byline_minimal():
    _doc_with({"type": "byline", "text": "by Tim Kraus"})


def test_byline_rejects_long_text():
    with pytest.raises(Exception):
        _doc_with({"type": "byline", "text": "x" * 101})


def test_dateline_minimal():
    _doc_with({"type": "dateline", "location": "Anytown", "date": "May 12"})


def test_dateline_requires_both_fields():
    with pytest.raises(Exception):
        _doc_with({"type": "dateline", "location": "Anytown"})
    with pytest.raises(Exception):
        _doc_with({"type": "dateline", "date": "May 12"})


def test_salutation_minimal():
    _doc_with({"type": "salutation", "text": "Dear Sam,"})


def test_signature_minimal():
    _doc_with({"type": "signature", "name": "Tim"})


def test_signature_with_closing():
    _doc_with({"type": "signature", "name": "Tim", "closing": "Yours,"})


def test_signature_requires_name():
    with pytest.raises(Exception):
        _doc_with({"type": "signature", "closing": "Yours,"})


def test_colophon_minimal():
    _doc_with({"type": "colophon", "text": "Set in IBM Plex Sans Medium."})


def test_colophon_rejects_long_text():
    with pytest.raises(Exception):
        _doc_with({"type": "colophon", "text": "x" * 501})


def test_address_minimal():
    _doc_with({"type": "address", "lines": ["Tim Kraus", "123 Main St"]})


def test_address_rejects_empty_list():
    with pytest.raises(Exception):
        _doc_with({"type": "address", "lines": []})


def test_address_rejects_too_many_lines():
    with pytest.raises(Exception):
        _doc_with({"type": "address", "lines": ["x"] * 9})


def test_all_literary_types_in_block_type_names():
    from printer.schema.blocks import block_type_names
    names = block_type_names()
    for t in ("epigraph", "byline", "dateline", "salutation",
              "signature", "colophon", "address"):
        assert t in names, f"{t!r} missing from block_type_names()"


def test_each_literary_type_renders_via_pipeline(fonts):
    """Smoke test: every new block parses and routes through the pipeline.
    The render-side may produce a placeholder canvas (renderers land in a
    follow-up commit) but the document must validate and render to *some*
    non-zero canvas through the existing fallback path."""
    from printer.render.renderer import render_document
    payloads = [
        {"type": "epigraph", "text": "x"},
        {"type": "byline", "text": "by x"},
        {"type": "dateline", "location": "x", "date": "y"},
        {"type": "salutation", "text": "Hi,"},
        {"type": "signature", "name": "x"},
        {"type": "colophon", "text": "x"},
        {"type": "address", "lines": ["a", "b"]},
    ]
    for p in payloads:
        doc = _doc_with(p)
        img = render_document(doc, fonts=fonts)
        assert img.width == 576
        assert img.height > 0
