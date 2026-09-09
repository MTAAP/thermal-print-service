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
