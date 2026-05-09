import pytest

from printer.schema.document import Document
from printer.schema.errors import to_structured_errors


def test_minimal_document_parses():
    doc = Document.model_validate({
        "document_type": "briefing",
        "blocks": [{"type": "header", "text": "Hi"}],
    })
    assert doc.document_type == "briefing"
    assert len(doc.blocks) == 1


def test_options_default_match_spec():
    doc = Document.model_validate({"blocks": [{"type": "spacer", "lines": 1}]})
    assert doc.options.auto_cut is True
    assert doc.options.feed_lines_after == 2
    assert doc.options.preserve_paper is False
    assert doc.options.max_length_mm == 2000
    assert doc.options.expires_at is None


def test_unknown_block_type_yields_structured_error():
    try:
        Document.model_validate({"blocks": [{"type": "marquee", "text": "x"}]})
    except Exception as exc:
        errs = to_structured_errors(exc)
        assert errs
        assert errs[0]["block_index"] == 0
        assert errs[0]["field"] == "type" or errs[0]["field"].endswith("type")
        assert "marquee" not in (errs[0]["valid_values"] or [])
        return
    pytest.fail("expected validation error")


def test_nonempty_blocks_required():
    with pytest.raises(Exception):
        Document.model_validate({"blocks": []})
