from __future__ import annotations

import re
from typing import Any

from pydantic import ValidationError

from printer.schema.blocks import block_type_names

# Migration hints sourced from SCHEMA_CHANGELOG.md (kept in sync manually per spec).
MIGRATION_HINTS: dict[str, str] = {}


_BLOCK_INDEX_PREFIX = "blocks"

# pydantic v2 quotes enum values with single quotes and joins with ", "
# (e.g. "'left', 'center', 'right'"). Sometimes the final separator is " or ".
_QUOTED = re.compile(r"'([^']*)'")


def _block_index(loc: tuple[Any, ...]) -> int | None:
    if len(loc) >= 2 and loc[0] == _BLOCK_INDEX_PREFIX and isinstance(loc[1], int):
        return loc[1]
    return None


def _field_path(loc: tuple[Any, ...]) -> str:
    if not loc:
        return "<root>"
    return ".".join(str(p) for p in loc)


def _parse_quoted_list(s: str) -> list[str]:
    """Pull every single-quoted token out of a pydantic context string."""
    return _QUOTED.findall(s)


def to_structured_errors(exc: Exception) -> list[dict[str, Any]]:
    """Translate a pydantic ValidationError into the spec's 400 contract."""
    if not isinstance(exc, ValidationError):
        return [{
            "block_index": None, "field": None,
            "message": str(exc),
            "valid_values": None, "migration_hint": None,
        }]
    out: list[dict[str, Any]] = []
    for err in exc.errors():
        loc = err.get("loc", ())
        err_type = err.get("type", "")
        ctx = err.get("ctx") or {}
        block_index = _block_index(loc)

        # Discriminated-union failures (union_tag_invalid / union_tag_not_found):
        # pydantic emits loc=('blocks', N) without a trailing "type" segment.
        # The spec contract wants the structured error to point at the discriminator
        # field, so synthesize "<path>.type" and surface the expected tags.
        if err_type in ("union_tag_invalid", "union_tag_not_found"):
            field = _field_path(loc) + ".type" if loc else "type"
            expected = ctx.get("expected_tags")
            valid_values: list[str] | None = None
            if isinstance(expected, str):
                valid_values = _parse_quoted_list(expected) or None
            if not valid_values:
                valid_values = block_type_names()
        else:
            field = _field_path(loc)
            valid_values = None
            expected = ctx.get("expected")
            if isinstance(expected, str):
                parsed = _parse_quoted_list(expected)
                if parsed:
                    valid_values = parsed

        out.append({
            "block_index": block_index,
            "field": field,
            "message": err.get("msg", "invalid"),
            "valid_values": valid_values,
            "migration_hint": MIGRATION_HINTS.get(field),
        })
    return out


class StructuredValidationError(Exception):
    """Raised by app-level validators that need spec-shaped 400s outside pydantic."""
    def __init__(self, errors: list[dict[str, Any]]) -> None:
        super().__init__("validation failed")
        self.errors = errors
