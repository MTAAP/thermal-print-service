import pytest

from printer.schema.document import Document


def test_checklist_items_required():
    with pytest.raises(Exception):
        Document.model_validate({"blocks": [{"type": "checklist", "items": []}]})
    Document.model_validate({"blocks": [{"type": "checklist", "items": ["x"]}]})


def test_bullets_default_marker():
    doc = Document.model_validate({"blocks": [{"type": "bullets", "items": ["x"]}]})
    assert doc.blocks[0].marker == "•"


def test_kv_pair_value_can_be_empty_string():
    Document.model_validate({"blocks": [
        {"type": "kv", "pairs": [{"key": "k", "value": ""}]}
    ]})


def test_table_compact_column_count():
    # 2 columns OK
    Document.model_validate({"blocks": [
        {"type": "table_compact", "rows": [["a", "b"], ["c", "d"]]}
    ]})
    # 3 columns OK
    Document.model_validate({"blocks": [
        {"type": "table_compact", "rows": [["a", "b", "c"]]}
    ]})
    # 4 columns NOT OK
    with pytest.raises(Exception):
        Document.model_validate({"blocks": [
            {"type": "table_compact", "rows": [["a", "b", "c", "d"]]}
        ]})
    # mismatched row widths NOT OK
    with pytest.raises(Exception):
        Document.model_validate({"blocks": [
            {"type": "table_compact", "rows": [["a", "b"], ["c", "d", "e"]]}
        ]})
