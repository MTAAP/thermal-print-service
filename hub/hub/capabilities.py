from __future__ import annotations

from typing import Any

import jsonschema
from sqlalchemy.ext.asyncio import AsyncSession

from hub.models import Capability, Printer


class CapabilityError(Exception):
    """Hub-side schema rejection; mirrors the Pi's valid_values shape where it can."""

    def __init__(self, detail: dict[str, Any]) -> None:
        super().__init__(detail.get("message", "incompatible"))
        self.detail = detail


async def upsert_capability(
    session: AsyncSession, *, printer_id: str, renderer_version: str,
    blocks_schema: dict, block_types: list[str],
) -> None:
    cap = await session.get(Capability, renderer_version)
    if cap is None:
        session.add(Capability(renderer_version=renderer_version,
                               blocks_schema=blocks_schema, block_types=block_types))
    else:
        cap.blocks_schema = blocks_schema
        cap.block_types = block_types
    printer = await session.get(Printer, printer_id)
    if printer is not None:
        printer.renderer_version = renderer_version
    await session.commit()


async def schema_for_recipient(session: AsyncSession, recipient_id: str) -> dict | None:
    p = await session.get(Printer, recipient_id)
    if p is None or p.renderer_version is None:
        return None
    cap = await session.get(Capability, p.renderer_version)
    return cap.blocks_schema if cap else None


async def capability_for_recipient(
    session: AsyncSession, recipient_id: str
) -> tuple[str | None, dict | None, list]:
    """(renderer_version, blocks_schema, block_types). Nulls when the printer
    exists but has not reported capabilities yet."""
    p = await session.get(Printer, recipient_id)
    if p is None or p.renderer_version is None:
        return None, None, []
    cap = await session.get(Capability, p.renderer_version)
    if cap is None:
        return p.renderer_version, None, []
    return p.renderer_version, cap.blocks_schema, cap.block_types


def validate_document(blocks_schema: dict, document: dict) -> None:
    """Approximation of the Pi's Pydantic validation (§6.2). The Pi validator
    stays authoritative; this catches the common, cheap cases at send time."""
    validator = jsonschema.Draft202012Validator(blocks_schema)
    error = next(iter(validator.iter_errors(document)), None)
    if error is None:
        return
    # Best-effort schema-derived detail. The Pi's exact migration_hint is only
    # available on a downstream 400 (§7.3), never here.
    valid_values = None
    if error.validator == "enum":
        valid_values = list(error.validator_value)
    raise CapabilityError({
        "message": error.message,
        "field": list(error.absolute_path),
        "valid_values": valid_values,
    })
