import pytest

from printer.schema.document import Document


def test_rule_styles():
    for s in ("solid", "dashed", "dotted", "double", "wave"):
        Document.model_validate({"blocks": [{"type": "rule", "style": s}]})


def test_spacer_lines_range():
    Document.model_validate({"blocks": [{"type": "spacer", "lines": 1}]})
    Document.model_validate({"blocks": [{"type": "spacer", "lines": 10}]})
    with pytest.raises(Exception):
        Document.model_validate({"blocks": [{"type": "spacer", "lines": 11}]})
    with pytest.raises(Exception):
        Document.model_validate({"blocks": [{"type": "spacer", "lines": 0}]})


def test_progress_bar_value_range():
    Document.model_validate({"blocks": [{"type": "progress_bar", "value": 0.0}]})
    Document.model_validate({"blocks": [{"type": "progress_bar", "value": 1.0}]})
    with pytest.raises(Exception):
        Document.model_validate({"blocks": [{"type": "progress_bar", "value": 1.5}]})


def test_sparkline_minimum_two_values():
    with pytest.raises(Exception):
        Document.model_validate({"blocks": [{"type": "sparkline", "values": [1.0]}]})
    Document.model_validate({"blocks": [{"type": "sparkline", "values": [1.0, 2.0]}]})
