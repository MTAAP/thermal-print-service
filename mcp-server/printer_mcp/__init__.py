"""MCP server adapter for the Thermal Print Service.

Exposes the Pi-side HTTP API (`/print`, `/print/raw`, `/healthz`, `/jobs`,
`POST /jobs/{id}/reprint`, `POST /test`) as MCP tools so Claude Desktop,
Claude Code, and other agentic surfaces on the tailnet can drive the
printer the same way deterministic senders do.

The block-document tool's parameter schema is fetched from
`GET /schema` at boot — there is no hand-maintained schema knowledge here.
Removed block types vanish from the tool's input schema; new block types
become available after restart, per spec §13.
"""

from printer_mcp.config import McpConfig

__all__ = ["McpConfig"]
__version__ = "0.1.0"
