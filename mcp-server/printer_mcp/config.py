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
    # Cap on the decoded byte length of a ``print_image`` payload.
    # The Pi has its own ``max_request_bytes`` cap (default 8 MB) but
    # the MCP server decodes the base64 in-process first — without a
    # cap here, a multi-hundred-MB agent-supplied string lands as RSS
    # before the service cap fires. Match the Pi default by default.
    max_print_image_bytes: int = 8 * 1024 * 1024
    # Printer Pals hub. The default host is a guaranteed-unresolvable
    # `.invalid` name (RFC 6761) so a friend-send fails loudly with a DNS
    # error when HUB_URL is unset — same loud-fail discipline as
    # PRINT_SERVICE_URL above. HUB_API_TOKEN is the per-person API/MCP
    # token (spec §9.1); it stays empty by default so a friend-tool call
    # can return a crisp "HUB_API_TOKEN not set" instead of issuing an
    # unauthenticated request.
    hub_url: str = "https://printer-pals-hub.invalid"
    hub_api_token: str = ""

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
            max_print_image_bytes=int(
                e.get("PRINT_MAX_IMAGE_BYTES", cls.max_print_image_bytes)
            ),
            hub_url=e.get("HUB_URL", cls.hub_url).rstrip("/"),
            hub_api_token=e.get("HUB_API_TOKEN", cls.hub_api_token),
        )
