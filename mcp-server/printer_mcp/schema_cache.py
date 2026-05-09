from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from printer_mcp.client import PrintServiceClient
from printer_mcp.errors import PrintServiceError

log = logging.getLogger(__name__)


# Fallback schema used when the Pi is unreachable at boot. Permissive
# enough that a tool call doesn't immediately fail validation, strict
# enough that obvious garbage still gets rejected — the Pi remains the
# authoritative validator either way.
_FALLBACK_DOCUMENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "description": (
        "Print document. Fallback schema — the print service was "
        "unreachable when this MCP server started. Restart the MCP "
        "server once the service is back to fetch the live schema "
        "(including all current block types)."
    ),
    "properties": {
        "document_type": {"type": "string"},
        "options": {"type": "object"},
        "blocks": {"type": "array", "items": {"type": "object"}},
    },
    "required": ["blocks"],
    "additionalProperties": True,
}


@dataclass
class SchemaSnapshot:
    document_schema: dict[str, Any]
    renderer_version: str
    block_types: list[str]
    is_fallback: bool


class SchemaCache:
    """Caches the ``/schema`` response so the MCP tool input schema can be
    derived from it without a round-trip per tool call.

    The spec (§13) is explicit: new block types become callable from any
    agentic surface as soon as the MCP server restarts. We do NOT poll
    for schema changes — restart is the deal. We DO retry on boot failure
    so a Pi that's a few seconds behind us starting doesn't put the
    server into permanent fallback mode.
    """

    def __init__(self, client: PrintServiceClient) -> None:
        self._client = client
        self._snapshot: SchemaSnapshot | None = None

    @property
    def snapshot(self) -> SchemaSnapshot:
        if self._snapshot is None:
            return SchemaSnapshot(
                document_schema=_FALLBACK_DOCUMENT_SCHEMA,
                renderer_version="unknown",
                block_types=[],
                is_fallback=True,
            )
        return self._snapshot

    async def boot(self, *, retry_budget_s: float) -> SchemaSnapshot:
        """Try to fetch ``/schema`` for up to ``retry_budget_s`` seconds.

        Backoff doubles from 200ms up to 1s. If the budget is exhausted,
        we return the fallback snapshot — the server still starts so
        Claude Desktop's "MCP server failed to launch" UX never fires
        just because the Pi is asleep.
        """
        deadline = asyncio.get_event_loop().time() + retry_budget_s
        delay = 0.2
        last_err: PrintServiceError | None = None
        while True:
            try:
                self._snapshot = _normalize(await self._client.get_schema())
                log.info(
                    "fetched schema: renderer_version=%s, %d block types",
                    self._snapshot.renderer_version,
                    len(self._snapshot.block_types),
                )
                return self._snapshot
            except PrintServiceError as exc:
                last_err = exc
                now = asyncio.get_event_loop().time()
                if now >= deadline:
                    break
                await asyncio.sleep(min(delay, max(0.05, deadline - now)))
                delay = min(delay * 2, 1.0)

        log.warning(
            "could not fetch /schema within %.1fs: %s — running in fallback mode",
            retry_budget_s,
            last_err,
        )
        return self.snapshot

    async def refresh(self) -> SchemaSnapshot:
        """One-shot schema refresh used when a tool call detects we're
        in fallback mode. No retry budget — single attempt, propagate
        the original error if it fails so the caller can surface it.
        """
        self._snapshot = _normalize(await self._client.get_schema())
        return self._snapshot


def _normalize(payload: dict[str, Any]) -> SchemaSnapshot:
    document_schema = payload.get("blocks") or _FALLBACK_DOCUMENT_SCHEMA
    if not isinstance(document_schema, dict):
        document_schema = _FALLBACK_DOCUMENT_SCHEMA
    return SchemaSnapshot(
        document_schema=document_schema,
        renderer_version=str(payload.get("renderer_version") or "unknown"),
        block_types=list(payload.get("block_types") or []),
        is_fallback=False,
    )
