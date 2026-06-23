from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
import pytest

from printer_mcp.client import PrintServiceClient
from printer_mcp.config import McpConfig
from printer_mcp.schema_cache import SchemaCache

if TYPE_CHECKING:
    from printer_mcp.hub_client import HubClient


@pytest.fixture
def cfg() -> McpConfig:
    return McpConfig(
        print_service_url="http://printer.test",
        sender="mcp-test",
        timeout_s=2.0,
        schema_boot_retry_s=0.05,
    )


def make_client(cfg: McpConfig, transport: httpx.MockTransport) -> PrintServiceClient:
    http = httpx.AsyncClient(
        transport=transport,
        base_url=cfg.print_service_url,
        timeout=cfg.timeout_s,
        headers={"X-Sender": cfg.sender},
    )
    return PrintServiceClient(cfg, http=http)


@pytest.fixture
def make_client_factory(cfg):
    def factory(handler) -> PrintServiceClient:
        return make_client(cfg, httpx.MockTransport(handler))
    return factory


@pytest.fixture
def sample_schema_payload() -> dict:
    return {
        "blocks": {
            "type": "object",
            "title": "Document",
            "properties": {
                "document_type": {"type": "string"},
                "options": {"type": "object"},
                "blocks": {
                    "type": "array",
                    "items": {"$ref": "#/$defs/AnyBlock"},
                },
            },
            "required": ["blocks"],
            "$defs": {
                "AnyBlock": {
                    "oneOf": [
                        {"$ref": "#/$defs/Header"},
                        {"$ref": "#/$defs/Paragraph"},
                    ]
                },
                "Header": {
                    "type": "object",
                    "properties": {
                        "type": {"const": "header"},
                        "text": {"type": "string"},
                    },
                    "required": ["type", "text"],
                },
                "Paragraph": {
                    "type": "object",
                    "properties": {
                        "type": {"const": "paragraph"},
                        "text": {"type": "string"},
                    },
                    "required": ["type", "text"],
                },
            },
        },
        "renderer_version": "1.4.2",
        "block_types": ["header", "paragraph"],
        "changelog_url": "https://example/SCHEMA_CHANGELOG.md",
    }


@pytest.fixture
def cache_with_schema(make_client_factory, sample_schema_payload) -> SchemaCache:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/schema":
            return httpx.Response(200, json=sample_schema_payload)
        return httpx.Response(404)

    client = make_client_factory(handler)
    cache = SchemaCache(client)
    return cache


def make_hub_client(transport: httpx.MockTransport, *, token: str = "tok-test") -> HubClient:
    """Build a HubClient wired to a MockTransport (the hermetic mock hub)."""
    from printer_mcp.config import McpConfig
    from printer_mcp.hub_client import HubClient

    cfg = McpConfig(hub_url="http://hub.test", hub_api_token=token)
    http = httpx.AsyncClient(
        transport=transport,
        base_url=cfg.hub_url,
        timeout=cfg.timeout_s,
        headers={"Authorization": f"Bearer {cfg.hub_api_token}"},
    )
    return HubClient(cfg, http=http)


@pytest.fixture
def make_hub_client_factory():
    def factory(handler, *, token: str = "tok-test") -> HubClient:
        return make_hub_client(httpx.MockTransport(handler), token=token)
    return factory


def _default_hub_handler(request: httpx.Request) -> httpx.Response:
    # A mock hub that 404s everything; individual tests pass their own.
    return httpx.Response(404, json={"detail": "no hub route"})


def build_with_handler(cfg, handler, *, hub_handler=None):
    """Build an MCP server wired to a MockTransport for the Pi client and a
    (separate) MockTransport for the hub client. Returns
    (server, cache, client, hub_client)."""
    from printer_mcp.client import PrintServiceClient
    from printer_mcp.hub_client import HubClient
    from printer_mcp.schema_cache import SchemaCache
    from printer_mcp.server import build_server

    pi_http = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url=cfg.print_service_url,
        timeout=cfg.timeout_s,
        headers={"X-Sender": cfg.sender},
    )
    client = PrintServiceClient(cfg, http=pi_http)
    cache = SchemaCache(client)

    hub_http = httpx.AsyncClient(
        transport=httpx.MockTransport(hub_handler or _default_hub_handler),
        base_url=cfg.hub_url,
        timeout=cfg.timeout_s,
        headers={"Authorization": f"Bearer {cfg.hub_api_token}"},
    )
    hub_client = HubClient(cfg, http=hub_http)

    server = build_server(cfg, client, cache, hub_client)
    return server, cache, client, hub_client


def list_tools(server) -> list:
    """Invoke the registered list_tools handler regardless of the mcp
    version's decorator name (handlers are keyed by request type)."""
    handlers = (
        getattr(server, "request_handlers", None)
        or getattr(server, "_request_handlers", None)
    )
    if handlers is None:
        raise AssertionError("could not find request handlers on server")
    from mcp import types as mcp_types

    handler = handlers.get(mcp_types.ListToolsRequest)
    if handler is None:
        for k, v in handlers.items():
            if "ListTools" in str(k):
                handler = v
                break
    assert handler is not None, f"list_tools handler missing; keys={list(handlers.keys())}"
    import asyncio

    request = mcp_types.ListToolsRequest(method="tools/list")
    result = asyncio.run(handler(request))
    return result.root.tools


def call_tool(server, name: str, args: dict) -> list:
    handlers = (
        getattr(server, "request_handlers", None)
        or getattr(server, "_request_handlers", None)
    )
    from mcp import types as mcp_types

    handler = handlers.get(mcp_types.CallToolRequest)
    if handler is None:
        for k, v in handlers.items():
            if "CallTool" in str(k):
                handler = v
                break
    assert handler is not None
    import asyncio

    request = mcp_types.CallToolRequest(
        method="tools/call",
        params=mcp_types.CallToolRequestParams(name=name, arguments=args),
    )
    result = asyncio.run(handler(request))
    return result.root.content
