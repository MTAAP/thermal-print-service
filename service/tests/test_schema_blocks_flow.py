import pytest

from printer.schema.document import Document


def test_tear_here_label_optional():
    Document.model_validate({"blocks": [{"type": "tear_here"}]})
    Document.model_validate({"blocks": [{"type": "tear_here", "label": "rip here"}]})


def test_cut_takes_no_fields():
    Document.model_validate({"blocks": [{"type": "cut"}]})
    with pytest.raises(Exception):
        Document.model_validate({"blocks": [{"type": "cut", "extra": "x"}]})


def test_feed_lines_required_and_ranged():
    Document.model_validate({"blocks": [{"type": "feed", "lines": 1}]})
    Document.model_validate({"blocks": [{"type": "feed", "lines": 20}]})
    with pytest.raises(Exception):
        Document.model_validate({"blocks": [{"type": "feed", "lines": 0}]})
    with pytest.raises(Exception):
        Document.model_validate({"blocks": [{"type": "feed", "lines": 21}]})
