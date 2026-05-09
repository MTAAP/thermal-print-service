import pytest

from printer.schema.blocks import ALIGN_ALLOWED, block_type_names
from printer.schema.document import Document


def _minimal(t: str) -> dict:
    base = {
        "header": {"text": "x"},
        "section_title": {"text": "x"},
        "paragraph": {"text": "x"},
        "rich_text": {"runs": [{"text": "a"}, {"text": "b"}]},
        "large_text": {"text": "X"},
        "code": {"text": "x"},
        "pull_quote": {"text": "x"},
        "drop_cap": {"first_letter": "A", "rest": "..."},
        "footer": {"text": "x"},
        "checklist": {"items": ["a"]},
        "bullets": {"items": ["a"]},
        "numbered": {"items": ["a"]},
        "kv": {"pairs": [{"key": "k", "value": "v"}]},
        "table_compact": {"rows": [["a", "b"]]},
        "rule": {},
        "ornament": {},
        "spacer": {"lines": 1},
        "gradient_band": {},
        "progress_bar": {"value": 0.5},
        "sparkline": {"values": [1, 2]},
        "qr": {"data": "x"},
        "barcode": {"data": "12345678"},
        "image": {"png_base64": "AA"},
        "ascii_art": {"text": "x"},
        "tear_here": {},
        "cut": {},
        "feed": {"lines": 1},
    }
    return {"type": t, **base[t]}


def test_align_only_on_allowed_types():
    for t in block_type_names():
        if t in ALIGN_ALLOWED:
            continue
        minimal = _minimal(t)
        minimal["align"] = "center"
        with pytest.raises(Exception, match="(?i)align|extra"):
            Document.model_validate({"blocks": [minimal]})
