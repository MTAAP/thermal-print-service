from __future__ import annotations

import asyncio

import httpx

from printer_mcp.errors import PrintServiceError
from printer_mcp.schema_cache import SchemaCache


def test_snapshot_returns_fallback_before_boot(cache_with_schema):
    snap = cache_with_schema.snapshot
    assert snap.is_fallback is True
    assert snap.renderer_version == "unknown"
    assert snap.block_types == []


def test_boot_populates_snapshot_from_schema_endpoint(cache_with_schema):
    asyncio.run(cache_with_schema.boot(retry_budget_s=0.5))
    snap = cache_with_schema.snapshot
    assert snap.is_fallback is False
    assert snap.renderer_version == "1.4.2"
    assert "header" in snap.block_types
    assert snap.document_schema["title"] == "Document"


def test_boot_returns_fallback_on_persistent_error(make_client_factory):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"detail": "boom"})

    client = make_client_factory(handler)
    cache = SchemaCache(client)

    snap = asyncio.run(cache.boot(retry_budget_s=0.05))
    assert snap.is_fallback is True
    assert "fallback" in snap.document_schema["description"].lower()


def test_boot_succeeds_on_retry(make_client_factory, sample_schema_payload):
    """If the Pi is a couple of seconds behind us starting up, the second
    or third attempt within the boot retry window should succeed.
    """
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 2:
            raise httpx.ConnectError("not ready", request=request)
        return httpx.Response(200, json=sample_schema_payload)

    client = make_client_factory(handler)
    cache = SchemaCache(client)

    snap = asyncio.run(cache.boot(retry_budget_s=2.0))
    assert snap.is_fallback is False
    assert calls["n"] >= 2


def test_refresh_propagates_errors(make_client_factory):
    """Unlike boot(), refresh() is a single shot that re-raises so the
    caller can surface the error to the agent."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"reason": "asleep"})

    client = make_client_factory(handler)
    cache = SchemaCache(client)

    import pytest

    with pytest.raises(PrintServiceError):
        asyncio.run(cache.refresh())
