"""Normalisation and validation for guest-supplied text.

Every value here arrives from an anonymous stranger by way of a language model
that is on the stranger's side, so nothing the model "decides" is a control.
These functions are the control: they run before a document is composed, and
they are the only reason a stranger cannot turn one tool call into a metre of
paper."""

from __future__ import annotations

import re
import unicodedata

# Names a model reaches for when the guest never actually said who they are.
# Rejecting them is what turns "required parameter" into "the guest was asked".
_PLACEHOLDER_NAMES = frozenset({
    "a friend", "anon", "anonymous", "friend", "guest", "me", "n/a", "na",
    "none", "not given", "nobody", "s.o.", "someone", "stranger", "unknown",
    "unnamed", "user", "visitor",
})

_LETTER_RE = re.compile(r"[^\W\d_]", re.UNICODE)
_HORIZONTAL_WS_RE = re.compile(r"[^\S\n]+")
_BLANK_RUN_RE = re.compile(r"\n{3,}")


class RejectedText(ValueError):
    """Guest input a person would have to fix. The message is shown to the guest
    through the model, so it says what to do, not what went wrong internally."""


def _strip_invisibles(raw: str) -> str:
    # NFKC first so full-width and compatibility forms cannot smuggle a longer
    # string past a length cap that is measured after normalisation anyway.
    text = unicodedata.normalize("NFKC", raw)
    # Keep newline and tab; drop every other control and format character.
    # Cf covers zero-width joiners and bidi overrides, which render as nothing
    # on paper but count against the caps and can reorder the visible text.
    return "".join(
        ch for ch in text
        if ch in "\n\t" or unicodedata.category(ch) not in ("Cc", "Cf")
    )


def clean_name(raw: str, *, max_chars: int) -> str:
    """Return the guest's name, or raise RejectedText telling them to give one."""
    name = _HORIZONTAL_WS_RE.sub(" ", _strip_invisibles(raw).replace("\n", " ")).strip()
    if len(name) < 2 or not _LETTER_RE.search(name):
        raise RejectedText(
            "That is not a usable name. Ask the guest what they are called "
            "and pass what they answer."
        )
    if name.casefold() in _PLACEHOLDER_NAMES:
        raise RejectedText(
            f"'{name}' is a placeholder, not a name. Ask the guest for the name "
            "they want on the paper. Do not invent one."
        )
    if len(name) > max_chars:
        raise RejectedText(f"Names are limited to {max_chars} characters.")
    return name


def clean_message(raw: str, *, max_chars: int, max_lines: int) -> str:
    """Return the message body, collapsed so its printed length matches its text.

    Blank lines are the cheap paper attack: the block schema accepts thousands
    of characters, and a message that is mostly newlines costs the sender
    nothing while feeding paper for as long as the roll lasts. Runs of blank
    lines collapse to one, and the line count is capped independently of the
    character count."""
    text = _strip_invisibles(raw)
    text = _HORIZONTAL_WS_RE.sub(" ", text)
    text = _BLANK_RUN_RE.sub("\n\n", text)
    text = "\n".join(line.rstrip() for line in text.split("\n")).strip()
    if not text:
        raise RejectedText("The message is empty. Ask the guest what they want to say.")
    if len(text) > max_chars:
        raise RejectedText(
            f"That message is {len(text)} characters and the limit is {max_chars}. "
            "Ask the guest to shorten it."
        )
    lines = text.split("\n")
    if len(lines) > max_lines:
        raise RejectedText(
            f"That message is {len(lines)} lines and the limit is {max_lines}. "
            "Ask the guest to shorten it."
        )
    return text
