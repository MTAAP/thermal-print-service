"""Chunk-split semantics for ``cut`` blocks (Phase 6).

The renderer must walk the document and produce one chunk per printable
segment between ``cut`` boundaries. ``cut`` is a delimiter, not a printable
block; it never contributes paper to a chunk. Empty segments (leading,
trailing, adjacent cuts) collapse — the printer never receives a chunk it
would print with zero content just to fire the cutter.
"""
from printer.render.renderer import render_document, render_document_chunks
from printer.schema.document import Document


def test_no_cut_produces_single_chunk(fonts):
    doc = Document.model_validate({"blocks": [
        {"type": "paragraph", "text": "hello"},
        {"type": "paragraph", "text": "world"},
    ]})
    chunks, trailing = render_document_chunks(doc, fonts=fonts)
    assert len(chunks) == 1
    assert trailing is False


def test_one_cut_produces_two_chunks(fonts):
    doc = Document.model_validate({"blocks": [
        {"type": "paragraph", "text": "first"},
        {"type": "cut"},
        {"type": "paragraph", "text": "second"},
    ]})
    chunks, trailing = render_document_chunks(doc, fonts=fonts)
    assert len(chunks) == 2
    assert trailing is False
    # Each chunk is the full head width and non-zero height
    for img in chunks:
        assert img.width == 576
        assert img.height > 0


def test_two_cuts_produce_three_chunks(fonts):
    doc = Document.model_validate({"blocks": [
        {"type": "paragraph", "text": "a"},
        {"type": "cut"},
        {"type": "paragraph", "text": "b"},
        {"type": "cut"},
        {"type": "paragraph", "text": "c"},
    ]})
    chunks, trailing = render_document_chunks(doc, fonts=fonts)
    assert len(chunks) == 3
    assert trailing is False


def test_trailing_cut_produces_one_chunk_with_marker(fonts):
    doc = Document.model_validate({"blocks": [
        {"type": "paragraph", "text": "only"},
        {"type": "cut"},
    ]})
    chunks, trailing = render_document_chunks(doc, fonts=fonts)
    assert len(chunks) == 1
    assert trailing is True


def test_leading_cut_collapses(fonts):
    doc = Document.model_validate({"blocks": [
        {"type": "cut"},
        {"type": "paragraph", "text": "after"},
    ]})
    chunks, trailing = render_document_chunks(doc, fonts=fonts)
    assert len(chunks) == 1
    assert trailing is False


def test_adjacent_cuts_collapse_to_single_boundary(fonts):
    doc = Document.model_validate({"blocks": [
        {"type": "paragraph", "text": "a"},
        {"type": "cut"},
        {"type": "cut"},
        {"type": "paragraph", "text": "b"},
    ]})
    chunks, trailing = render_document_chunks(doc, fonts=fonts)
    assert len(chunks) == 2
    assert trailing is False


def test_trailing_cuts_collapse_with_marker(fonts):
    doc = Document.model_validate({"blocks": [
        {"type": "paragraph", "text": "only"},
        {"type": "cut"},
        {"type": "cut"},
    ]})
    chunks, trailing = render_document_chunks(doc, fonts=fonts)
    assert len(chunks) == 1
    assert trailing is True


def test_only_cuts_produces_zero_chunks(fonts):
    doc = Document.model_validate({"blocks": [
        {"type": "cut"},
        {"type": "cut"},
    ]})
    chunks, trailing = render_document_chunks(doc, fonts=fonts)
    assert chunks == []
    # ``trailing`` is moot with no chunks but the flag is still True
    # because cuts were seen.
    assert trailing is True


def test_chunks_total_height_matches_render_document(fonts):
    """The chunk pipeline and the single-canvas pipeline must produce the
    same printable content (modulo the 1-px ``cut`` markers in the single
    canvas), so ``sum(chunk.height) <= render_document.height``."""
    doc = Document.model_validate({"blocks": [
        {"type": "paragraph", "text": "alpha"},
        {"type": "cut"},
        {"type": "paragraph", "text": "beta"},
    ]})
    chunks, _ = render_document_chunks(doc, fonts=fonts)
    flat = render_document(doc, fonts=fonts)
    chunk_total = sum(c.height for c in chunks)
    # Single canvas includes the 1-px cut marker; chunks omit it.
    assert flat.height == chunk_total + 1
