import pytest

from printer.schema.document import Document


def test_paragraph_minimal():
    Document.model_validate({"blocks": [{"type": "paragraph", "text": "hi"}]})


def test_rich_text_accepts_single_run():
    Document.model_validate({"blocks": [
        {"type": "rich_text", "runs": [{"text": "single italic", "italic": True}]}
    ]})
    Document.model_validate({"blocks": [
        {"type": "rich_text",
         "runs": [{"text": "a", "bold": True}, {"text": "b"}]}
    ]})
    with pytest.raises(Exception):
        Document.model_validate({"blocks": [
            {"type": "rich_text", "runs": []}
        ]})


def test_drop_cap_first_letter_one_to_three_chars():
    Document.model_validate({"blocks": [
        {"type": "drop_cap", "first_letter": "T", "rest": "..."}
    ]})
    Document.model_validate({"blocks": [
        {"type": "drop_cap", "first_letter": "The", "rest": "..."}
    ]})
    with pytest.raises(Exception):
        Document.model_validate({"blocks": [
            {"type": "drop_cap", "first_letter": "Four", "rest": "..."}
        ]})


def test_align_allowed_on_header_rejected_on_spacer():
    Document.model_validate({"blocks": [{"type": "header", "text": "x", "align": "center"}]})
    with pytest.raises(Exception):
        Document.model_validate({"blocks": [{"type": "spacer", "lines": 1, "align": "center"}]})


def test_large_text_size_required_enum():
    Document.model_validate({"blocks": [{"type": "large_text", "text": "X", "size": "xxxl"}]})
    with pytest.raises(Exception):
        Document.model_validate({"blocks": [{"type": "large_text", "text": "X", "size": "huge"}]})
