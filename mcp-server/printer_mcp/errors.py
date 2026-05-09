from __future__ import annotations

from typing import Any


class PrintServiceError(Exception):
    """Raised by the HTTP client when the print service refuses or fails.

    Attributes:
        status: HTTP status code (or 0 for transport-level failures).
        body: Parsed JSON body if any, else None.
        message: Plain-English summary safe to surface to the agent.
    """

    def __init__(
        self, *, status: int, message: str, body: Any | None = None
    ) -> None:
        self.status = status
        self.body = body
        self.message = message
        super().__init__(message)


def format_for_agent(exc: PrintServiceError) -> dict[str, Any]:
    """Render a print-service error as a JSON-friendly dict for MCP tool
    return values.

    Preserves the structured 400 contract (``valid_values``,
    ``migration_hint``) verbatim under ``details`` so the agent has
    enough info to self-heal — that's why the spec made the 400 shape
    contractual.
    """
    out: dict[str, Any] = {"ok": False, "status": exc.status, "error": exc.message}
    if exc.body is not None:
        out["details"] = exc.body
    return out
