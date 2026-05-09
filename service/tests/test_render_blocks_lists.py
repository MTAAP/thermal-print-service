from printer.render.renderer import render_document
from printer.schema.document import Document


def test_checklist_renders_one_box_per_item(fonts):
    doc = Document.model_validate({"blocks": [
        {"type": "checklist", "items": ["a", "b", "c"]},
    ]})
    img = render_document(doc, fonts=fonts)
    assert img.height >= 18 * 3  # at least one line per item


def test_kv_renders_two_columns(fonts):
    doc = Document.model_validate({"blocks": [
        {"type": "kv", "pairs": [{"key": "k1", "value": "v1"},
                                  {"key": "k2", "value": "v2"}]},
    ]})
    img = render_document(doc, fonts=fonts)
    assert img.height >= 18 * 2


def test_bullets_with_default_marker(fonts):
    doc = Document.model_validate({"blocks": [
        {"type": "bullets", "items": ["one", "two", "three"]},
    ]})
    img = render_document(doc, fonts=fonts)
    assert img.height >= 18 * 3


def test_bullets_em_dash_marker(fonts):
    doc = Document.model_validate({"blocks": [
        {"type": "bullets", "items": ["a", "b"], "marker": "—"},
    ]})
    img = render_document(doc, fonts=fonts)
    assert img.height >= 18 * 2


def test_numbered_renders_count_prefix(fonts):
    doc = Document.model_validate({"blocks": [
        {"type": "numbered", "items": ["alpha", "beta", "gamma"]},
    ]})
    img = render_document(doc, fonts=fonts)
    assert img.height >= 18 * 3


def test_numbered_handles_double_digit_count(fonts):
    items = [f"row {i}" for i in range(1, 13)]  # 12 items -> double-digit last 3
    doc = Document.model_validate({"blocks": [
        {"type": "numbered", "items": items},
    ]})
    img = render_document(doc, fonts=fonts)
    assert img.height >= 18 * 12


def test_table_compact_two_columns(fonts):
    doc = Document.model_validate({"blocks": [
        {"type": "table_compact",
         "rows": [["Mo", "rain"], ["Tu", "sun"], ["We", "cloudy"]]},
    ]})
    img = render_document(doc, fonts=fonts)
    assert img.height > 0


def test_table_compact_with_headers(fonts):
    doc = Document.model_validate({"blocks": [
        {"type": "table_compact",
         "headers": ["day", "weather"],
         "rows": [["Mon", "sun"], ["Tue", "cloudy"]]},
    ]})
    img = render_document(doc, fonts=fonts)
    # Headers add a line + rule
    assert img.height > 18 * 2
