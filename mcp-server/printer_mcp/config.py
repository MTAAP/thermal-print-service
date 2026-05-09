from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class McpConfig:
    """Runtime config for the printer MCP server.

    All values come from environment variables so the server can be
    spawned by Claude Desktop / Code via a simple ``command``+``env`` JSON
    block, no config files required.
    """

    # Default is a placeholder pointing at a Tailscale Serve HTTPS shape
    # (``https://printer.your-tailnet.ts.net``). The Mac running Claude
    # Desktop / Code may be off the home Wi-Fi at any moment, and mDNS
    # short names like ``printer.local`` only resolve on the local
    # subnet — the tailnet name resolves anywhere Tailscale is up. Set
    # ``PRINT_SERVICE_URL`` to your actual tailnet hostname (e.g.
    # ``https://printer.tailXXXXXX.ts.net``); the placeholder below
    # fails DNS resolution loudly so misconfiguration is obvious.
    print_service_url: str = "https://printer.your-tailnet.ts.net"
    sender: str = "mcp"
    timeout_s: float = 30.0
    # How long to keep retrying ``GET /schema`` at boot before declaring
    # the server "degraded" (still starts so Claude Desktop doesn't error,
    # but tools that need the schema return a clear "service unreachable"
    # error until the next successful refresh).
    schema_boot_retry_s: float = 5.0

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> McpConfig:
        e = env if env is not None else os.environ
        url = e.get("PRINT_SERVICE_URL", cls.print_service_url).rstrip("/")
        return cls(
            print_service_url=url,
            sender=e.get("PRINT_SENDER", cls.sender),
            timeout_s=float(e.get("PRINT_TIMEOUT_S", cls.timeout_s)),
            schema_boot_retry_s=float(
                e.get("PRINT_SCHEMA_BOOT_RETRY_S", cls.schema_boot_retry_s)
            ),
        )
