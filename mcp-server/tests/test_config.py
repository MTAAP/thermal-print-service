from __future__ import annotations

from printer_mcp.config import McpConfig


def test_config_defaults_to_tailnet_https_url():
    """The MCP server runs on the user's Mac, which may be off the home
    Wi-Fi at any given moment. Default URL must resolve from any
    Tailscale-connected location, not just the local LAN."""
    cfg = McpConfig.from_env(env={})
    assert cfg.print_service_url == "https://printer.your-tailnet.ts.net"
    assert cfg.sender == "mcp"


def test_config_overrides_from_env():
    cfg = McpConfig.from_env(env={
        "PRINT_SERVICE_URL": "http://localhost:8000/",
        "PRINT_SENDER": "claude-desktop",
        "PRINT_TIMEOUT_S": "5.5",
        "PRINT_SCHEMA_BOOT_RETRY_S": "10",
    })
    # Trailing slash should be stripped so the client base_url + relative
    # path concatenation doesn't produce //double slashes.
    assert cfg.print_service_url == "http://localhost:8000"
    assert cfg.sender == "claude-desktop"
    assert cfg.timeout_s == 5.5
    assert cfg.schema_boot_retry_s == 10.0


def test_config_hub_defaults_fail_loudly_when_unset():
    """HUB_URL defaults to a guaranteed-unresolvable host so a
    misconfigured friend-send fails with a clear DNS error rather than
    silently hitting the wrong endpoint (matches the PRINT_SERVICE_URL
    convention, spec §9.5). HUB_API_TOKEN defaults empty so a tool call
    can surface 'token not set' instead of sending an unauthenticated
    request."""
    cfg = McpConfig.from_env(env={})
    assert cfg.hub_url == "https://printer-pals-hub.invalid"
    assert cfg.hub_api_token == ""


def test_config_hub_overrides_from_env():
    cfg = McpConfig.from_env(env={
        "HUB_URL": "http://hub.test/",
        "HUB_API_TOKEN": "tok-abc",
    })
    # Trailing slash stripped so base_url + relative path never doubles.
    assert cfg.hub_url == "http://hub.test"
    assert cfg.hub_api_token == "tok-abc"
