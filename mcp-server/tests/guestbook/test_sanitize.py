from __future__ import annotations

import pytest

from printer_mcp.guestbook.sanitize import RejectedText, clean_message, clean_name


@pytest.mark.parametrize("raw", ["anonymous", "Guest", " a friend ", "n/a", "?", "x", ""])
def test_placeholder_and_empty_names_rejected(raw):
    with pytest.raises(RejectedText):
        clean_name(raw, max_chars=40)


@pytest.mark.parametrize("raw,expected", [
    ("  Robin  ", "Robin"), ("Robin\nBeerman", "Robin Beerman"), ("Ada L.", "Ada L."),
])
def test_real_names_survive(raw, expected):
    assert clean_name(raw, max_chars=40) == expected


def test_zero_width_padding_cannot_smuggle_a_placeholder_past_the_denylist():
    assert clean_name("Ro​bin", max_chars=40) == "Robin"
    with pytest.raises(RejectedText):
        clean_name("anon​ymous", max_chars=40)


def test_full_width_normalisation_is_measured_after_folding():
    assert clean_name("Ｒｏｂｉｎ", max_chars=40) == "Robin"


def test_blank_runs_collapse_and_trailing_space_is_dropped():
    assert clean_message("a   b\n\n\n\n\nc  \n", max_chars=100, max_lines=10) == "a b\n\nc"


def test_line_cap_is_independent_of_the_character_cap():
    many_short_lines = "\n".join("x" for _ in range(50))
    assert len(many_short_lines) < 100
    with pytest.raises(RejectedText):
        clean_message(many_short_lines, max_chars=100, max_lines=10)


def test_whitespace_only_message_is_rejected():
    with pytest.raises(RejectedText):
        clean_message("  \n\n \t ", max_chars=100, max_lines=10)
