from printer.render.renderer import render_document
from printer.schema.document import Document


def test_checklist_renders_one_box_per_item(fonts):
    doc = Document.model_validate({"blocks": [
        {"type": "checklist", "items": ["a", "b", "c"]},
    ]})
    img = render_document(doc, fonts=fonts)
    assert img.height >= 24 * 3  # at least one line per item


def test_kv_renders_two_columns(fonts):
    doc = Document.model_validate({"blocks": [
        {"type": "kv", "pairs": [{"key": "k1", "value": "v1"},
                                  {"key": "k2", "value": "v2"}]},
    ]})
    img = render_document(doc, fonts=fonts)
    assert img.height >= 24 * 2


def test_bullets_with_default_marker(fonts):
    doc = Document.model_validate({"blocks": [
        {"type": "bullets", "items": ["one", "two", "three"]},
    ]})
    img = render_document(doc, fonts=fonts)
    assert img.height >= 24 * 3


def test_bullets_em_dash_marker(fonts):
    doc = Document.model_validate({"blocks": [
        {"type": "bullets", "items": ["a", "b"], "marker": "—"},
    ]})
    img = render_document(doc, fonts=fonts)
    assert img.height >= 24 * 2


def test_numbered_renders_count_prefix(fonts):
    doc = Document.model_validate({"blocks": [
        {"type": "numbered", "items": ["alpha", "beta", "gamma"]},
    ]})
    img = render_document(doc, fonts=fonts)
    assert img.height >= 24 * 3


def test_numbered_handles_double_digit_count(fonts):
    items = [f"row {i}" for i in range(1, 13)]  # 12 items -> double-digit last 3
    doc = Document.model_validate({"blocks": [
        {"type": "numbered", "items": items},
    ]})
    img = render_document(doc, fonts=fonts)
    assert img.height >= 24 * 12


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
    assert img.height > 24 * 2


def test_bullets_wrap_long_items(fonts):
    """Long bullet items must wrap inside the live width instead of
    truncating at the canvas edge. A line at ~60 cols would have silently
    fallen off the right edge under the pre-wrap renderer."""
    long_item = (
        "Putin's Victory Day parade ran 45 minutes — the shortest in modern "
        "Russian history, with reduced columns and no flyover"
    )
    doc = Document.model_validate({"blocks": [
        {"type": "bullets", "items": [long_item, long_item]},
    ]})
    img = render_document(doc, fonts=fonts)
    # Each item should occupy at least three body lines after wrap
    assert img.height >= 24 * 3 * 2 - 4


def test_checklist_wrap_long_items(fonts):
    long_item = "Reply to the support ticket about the rolling-window export feature"
    doc = Document.model_validate({"blocks": [
        {"type": "checklist", "items": [long_item]},
    ]})
    img = render_document(doc, fonts=fonts)
    assert img.height >= 24 * 2


def test_numbered_wrap_long_items(fonts):
    long_item = "Draft Q3 report covering revenue, churn, and the rolling-window analytics rollout"
    doc = Document.model_validate({"blocks": [
        {"type": "numbered", "items": [long_item]},
    ]})
    img = render_document(doc, fonts=fonts)
    assert img.height >= 24 * 2


def test_kv_wrap_long_values(fonts):
    long_value = "/var/lib/printer/state/cache/job-2026-05-09-evening.png"
    doc = Document.model_validate({"blocks": [
        {"type": "kv", "pairs": [{"key": "cache", "value": long_value}]},
    ]})
    img = render_document(doc, fonts=fonts)
    # Value should wrap to at least two lines at the narrower body grid
    assert img.height >= 24 * 2
