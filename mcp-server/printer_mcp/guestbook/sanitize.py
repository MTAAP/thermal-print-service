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


def looks_like_art(raw: str) -> bool:
    """Decide whether text must keep its own layout, without asking the model.

    The `preformatted` flag exists, but a flag the model has to remember is not
    a mechanism: it set the flag for "an ASCII art sign" and forgot it for "an
    ASCII poop emoji", and the forgotten case rendered as a paragraph, which
    reflows every line onto one. So the shape of the text decides, and the flag
    only ever adds to that.

    Two signals, either of which is enough, and both need more than one line:

      - a run of two or more spaces inside a line, which prose does not have but
        every aligned drawing does
      - a high share of punctuation, which is what a drawing is made of and what
        a sentence is not

    A genuine multi-line note ("Hi Tim,\n\nHope you are well") trips neither and
    stays prose, which is what should happen: rendering it as monospace art
    would be its own kind of wrong."""
    text = raw.strip()
    if "\n" not in text:
        return False
    lines = [ln for ln in text.split("\n") if ln.strip()]
    if len(lines) < 2:
        return False
    if any(re.search(r"\S {2,}\S", ln) for ln in lines):
        return True
    visible = [ch for ch in text if not ch.isspace()]
    if not visible:
        return False
    punctuation = sum(1 for ch in visible if not ch.isalnum())
    return punctuation / len(visible) > 0.25


def clean_art(raw: str, *, max_chars: int, max_lines: int, max_cols: int) -> str:
    """Return preformatted text with its spacing intact.

    The opposite of clean_message: here the runs of spaces ARE the content, so
    collapsing them destroys the thing being sent. Only invisible characters go,
    and the caps become the paper budget instead.

    Width is a hard limit rather than a soft one because the renderer draws each
    line from x=0 with no wrapping, so anything past the column budget is
    silently clipped off the right edge. Refusing is what lets the model redraw
    it narrower; clipping just produces mangled art nobody asked for."""
    text = _strip_invisibles(raw).replace("\t", "    ")
    text = "\n".join(line.rstrip() for line in text.split("\n")).strip("\n")
    if not text.strip():
        raise RejectedText("The drawing is empty. Ask the guest what they want to send.")
    lines = text.split("\n")
    if len(lines) > max_lines:
        raise RejectedText(
            f"That drawing is {len(lines)} lines and the limit is {max_lines}. "
            "Ask for a smaller version, or redraw it shorter."
        )
    widest = max(len(line) for line in lines)
    if widest > max_cols:
        raise RejectedText(
            f"That drawing is {widest} characters wide and the printer fits {max_cols}. "
            f"Anything wider gets cut off at the edge, so redraw it within {max_cols} "
            "columns and send it again."
        )
    if len(text) > max_chars:
        raise RejectedText(
            f"That drawing is {len(text)} characters and the limit is {max_chars}. "
            "Redraw it smaller."
        )
    return text


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
