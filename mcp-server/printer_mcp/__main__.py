from __future__ import annotations

import asyncio
import logging
import sys

from mcp.server.stdio import stdio_server

from printer_mcp.client import PrintServiceClient
from printer_mcp.config import McpConfig
from printer_mcp.schema_cache import SchemaCache
from printer_mcp.server import build_server


async def _run() -> None:
    cfg = McpConfig.from_env()
    client = PrintServiceClient(cfg)
    cache = SchemaCache(client)

    # Best-effort boot fetch. If the Pi is unreachable we still start the
    # server so Claude Desktop's "MCP server failed to launch" UX never
    # fires just because the printer is asleep.
    await cache.boot(retry_budget_s=cfg.schema_boot_retry_s)

    server = build_server(cfg, client, cache)
    try:
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())
    finally:
        await client.aclose()


def main() -> int:
    # MCP servers communicate over stdio — log to stderr (NOT stdout) so
    # we don't corrupt the JSON-RPC stream Claude is parsing.
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    try:
        asyncio.run(_run())
        return 0
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
