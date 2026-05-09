from __future__ import annotations

import httpx
import pytest

from printer_mcp.client import PrintServiceClient
from printer_mcp.config import McpConfig
from printer_mcp.schema_cache import SchemaCache


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
