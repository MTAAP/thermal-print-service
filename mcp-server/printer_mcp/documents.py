"""Document composition shared by the stdio server and the guestbook server."""

from __future__ import annotations

from typing import Any


def compose_text_document(title: str, text: str) -> dict[str, Any]:
    # Common-core only (header + paragraph): these block types are stable across
    # EVERY renderer version (hub spec 6.2), so a plain-text message needs no
    # get_friend_schema round-trip -- any friend's printer accepts it. Mirrors
    # the hub web console's compose document exactly (header iff a title, then a
    # paragraph; field name is `text`, not `content`).
    blocks: list[dict[str, Any]] = []
    if title.strip():
        blocks.append({"type": "header", "text": title.strip()})
    blocks.append({"type": "paragraph", "text": text})
    return {"blocks": blocks}


def compose_art_document(title: str, intro: str, art: str) -> dict[str, Any]:
    """A document whose payload is preformatted, so it needs a block that keeps
    newlines and spacing.

    `paragraph` reflows its text to the paper width, which is right for prose and
    fatal for a drawing: the line breaks that make the picture are exactly what
    reflowing throws away. `ascii_art` preserves both, and its `small` font gives
    52 columns against the default font's 33 -- the wider budget matters more
    than the larger glyph when the whole point is a shape."""
    blocks: list[dict[str, Any]] = []
    if title.strip():
        blocks.append({"type": "header", "text": title.strip()})
    if intro.strip():
        blocks.append({"type": "paragraph", "text": intro})
    blocks.append({"type": "ascii_art", "text": art, "font": "small"})
    return {"blocks": blocks}
