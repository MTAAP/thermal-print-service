from printer.schema.document import Document
from printer.schema.errors import to_structured_errors


def test_unknown_type_includes_block_index():
    try:
        Document.model_validate({"blocks": [
            {"type": "paragraph", "text": "ok"},
            {"type": "marquee", "text": "x"},
        ]})
    except Exception as exc:
        errs = to_structured_errors(exc)
        idx_seen = {e["block_index"] for e in errs if e.get("block_index") is not None}
        assert 1 in idx_seen


def test_align_invalid_value_emits_valid_values():
    try:
        Document.model_validate({"blocks": [
            {"type": "header", "text": "x", "align": "justified"}
        ]})
    except Exception as exc:
        errs = to_structured_errors(exc)
        # At least one error mentions align with valid_values populated
        align_errs = [e for e in errs if "align" in (e.get("field") or "")]
        assert align_errs
        assert align_errs[0]["valid_values"]
