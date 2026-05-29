from __future__ import annotations

import asyncio
import base64
import json
from typing import Any

import httpx
import pytest

from printer_mcp.config import McpConfig
from printer_mcp.schema_cache import SchemaCache
from printer_mcp.server import (
    build_print_document_input_schema,
    build_print_image_input_schema,
    build_server,
)


def test_print_document_input_schema_hoists_defs():
    """Pydantic-generated Document schemas have $defs at the schema root.
    When we embed the schema as the ``document`` property of the wrapper,
    the $defs must be hoisted to the wrapper root so $ref resolution
    keeps working.
    """
    doc_schema = {
        "type": "object",
        "properties": {"blocks": {"type": "array", "items": {"$ref": "#/$defs/B"}}},
        "$defs": {"B": {"type": "object"}},
    }
    wrapped = build_print_document_input_schema(doc_schema)
    assert wrapped["properties"]["document"]["properties"]["blocks"]["items"]["$ref"] == "#/$defs/B"
    assert "$defs" in wrapped
    assert "B" in wrapped["$defs"]
    # The embedded copy must NOT keep its own $defs (would double-define).
    assert "$defs" not in wrapped["properties"]["document"]


def test_print_document_input_schema_includes_idempotency_key():
    wrapped = build_print_document_input_schema({"type": "object"})
    assert "idempotency_key" in wrapped["properties"]
    assert wrapped["required"] == ["document"]


def test_print_image_input_schema_requires_png_base64():
    s = build_print_image_input_schema()
    assert s["required"] == ["png_base64"]
    assert "576" in s["properties"]["png_base64"]["description"]


def _build_with_handler(cfg: McpConfig, handler):
    """Build a server wired to a MockTransport. Returns (server, cache, client)."""
    from printer_mcp.client import PrintServiceClient

    http = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url=cfg.print_service_url,
        timeout=cfg.timeout_s,
        headers={"X-Sender": cfg.sender},
    )
    client = PrintServiceClient(cfg, http=http)
    cache = SchemaCache(client)
    server = build_server(cfg, client, cache)
    return server, cache, client


def _list_tools(server) -> list:
    """Invoke the registered list_tools handler regardless of the
    decorator name used by the installed mcp version. Try the public
    handler attribute first, fall back to introspection.
    """
    # mcp 1.x stores handlers on _request_handlers keyed by method name.
    handlers = (
        getattr(server, "request_handlers", None)
        or getattr(server, "_request_handlers", None)
    )
    if handlers is None:
        raise AssertionError("could not find request handlers on server")

    # Find by method-name key OR by class lookup.
    from mcp import types as mcp_types

    handler = handlers.get(mcp_types.ListToolsRequest)
    if handler is None:
        # Fall back to scanning by handler attr name.
        for k, v in handlers.items():
            if "ListTools" in str(k):
                handler = v
                break
    assert handler is not None, f"list_tools handler missing; keys={list(handlers.keys())}"

    request = mcp_types.ListToolsRequest(method="tools/list")
    result = asyncio.run(handler(request))
    return result.root.tools


def _call_tool(server, name: str, args: dict[str, Any]) -> list:
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

    request = mcp_types.CallToolRequest(
        method="tools/call",
        params=mcp_types.CallToolRequestParams(name=name, arguments=args),
    )
    result = asyncio.run(handler(request))
    return result.root.content


def test_list_tools_returns_expected_set(cfg, sample_schema_payload):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/schema":
            return httpx.Response(200, json=sample_schema_payload)
        return httpx.Response(404)

    server, cache, _ = _build_with_handler(cfg, handler)
    asyncio.run(cache.boot(retry_budget_s=0.5))

    tools = _list_tools(server)
    names = {t.name for t in tools}
    assert names == {
        "print_document",
        "print_image",
        "get_status",
        "list_recent_jobs",
        "reprint_job",
        "print_test",
        "get_design_guidelines",
    }


def test_list_tools_print_document_uses_live_schema(cfg, sample_schema_payload):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/schema":
            return httpx.Response(200, json=sample_schema_payload)
        return httpx.Response(404)

    server, cache, _ = _build_with_handler(cfg, handler)
    asyncio.run(cache.boot(retry_budget_s=0.5))

    tools = _list_tools(server)
    pd = next(t for t in tools if t.name == "print_document")
    # Description should mention the renderer version + at least one block type
    # so Claude has visible cues about what's available.
    assert "1.4.2" in pd.description
    assert "header" in pd.description
    # Input schema must be the dynamic Document schema, not a fallback.
    assert pd.inputSchema["properties"]["document"]["title"] == "Document"


def test_list_tools_in_fallback_mode_attempts_refresh_then_uses_fallback_schema(cfg):
    """When the Pi is unreachable at boot, list_tools should attempt one
    more refresh (Claude only calls list_tools at boot) and on continued
    failure fall back to a permissive schema with a note.
    """
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"reason": "asleep"})

    server, cache, _ = _build_with_handler(cfg, handler)
    asyncio.run(cache.boot(retry_budget_s=0.05))
    assert cache.snapshot.is_fallback is True

    tools = _list_tools(server)
    pd = next(t for t in tools if t.name == "print_document")
    assert "fallback" in pd.inputSchema["properties"]["document"]["description"].lower()


def test_call_get_status_returns_pi_health_payload(cfg, sample_schema_payload):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/schema":
            return httpx.Response(200, json=sample_schema_payload)
        if request.url.path == "/healthz":
            return httpx.Response(200, json={"queue_depth": 0, "uptime_s": 12})
        return httpx.Response(404)

    server, cache, _ = _build_with_handler(cfg, handler)
    asyncio.run(cache.boot(retry_budget_s=0.5))

    content = _call_tool(server, "get_status", {})
    assert len(content) == 1
    payload = json.loads(content[0].text)
    assert payload["ok"] is True
    assert payload["result"]["queue_depth"] == 0


def test_call_print_document_forwards_payload_and_returns_202(cfg, sample_schema_payload):
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/schema":
            return httpx.Response(200, json=sample_schema_payload)
        if request.url.path == "/print":
            seen["body"] = json.loads(request.content.decode())
            seen["idem"] = request.headers.get("x-idempotency-key")
            return httpx.Response(
                202,
                json={"id": "01J", "duplicate": False, "estimated_paper_mm": 42},
            )
        return httpx.Response(404)

    server, cache, _ = _build_with_handler(cfg, handler)
    asyncio.run(cache.boot(retry_budget_s=0.5))

    content = _call_tool(
        server,
        "print_document",
        {"document": {"blocks": [{"type": "header", "text": "hi"}]}, "idempotency_key": "k1"},
    )
    payload = json.loads(content[0].text)
    assert payload["ok"] is True
    assert payload["result"]["id"] == "01J"
    assert seen["body"]["blocks"][0]["text"] == "hi"
    assert seen["idem"] == "k1"


def test_call_print_document_surfaces_400_with_structured_body(cfg, sample_schema_payload):
    """The spec made the 400 contract structured — agent must see
    valid_values + migration_hint verbatim under details."""
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/schema":
            return httpx.Response(200, json=sample_schema_payload)
        return httpx.Response(
            400,
            json={
                "errors": [
                    {
                        "block_index": 0,
                        "field": "type",
                        "message": "unknown block type 'spinner'",
                        "valid_values": ["header", "paragraph"],
                        "migration_hint": None,
                    }
                ]
            },
        )

    server, cache, _ = _build_with_handler(cfg, handler)
    asyncio.run(cache.boot(retry_budget_s=0.5))

    content = _call_tool(server, "print_document", {"document": {"blocks": []}})
    payload = json.loads(content[0].text)
    assert payload["ok"] is False
    assert payload["status"] == 400
    assert payload["details"]["errors"][0]["valid_values"] == ["header", "paragraph"]


def test_call_print_image_decodes_base64_and_posts_bytes(cfg, sample_schema_payload):
    raw_png = b"\x89PNG\r\n\x1a\nABC"
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/schema":
            return httpx.Response(200, json=sample_schema_payload)
        if request.url.path == "/print/raw":
            seen["body"] = bytes(request.content)
            seen["ct"] = request.headers.get("content-type")
            return httpx.Response(202, json={"id": "01K"})
        return httpx.Response(404)

    server, cache, _ = _build_with_handler(cfg, handler)
    asyncio.run(cache.boot(retry_budget_s=0.5))

    encoded = base64.b64encode(raw_png).decode("ascii")
    content = _call_tool(server, "print_image", {"png_base64": encoded})
    payload = json.loads(content[0].text)
    assert payload["ok"] is True
    assert seen["body"] == raw_png
    assert seen["ct"] == "image/png"


def test_call_print_image_rejects_invalid_base64(cfg, sample_schema_payload):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/schema":
            return httpx.Response(200, json=sample_schema_payload)
        return httpx.Response(404)

    server, cache, _ = _build_with_handler(cfg, handler)
    asyncio.run(cache.boot(retry_budget_s=0.5))

    content = _call_tool(server, "print_image", {"png_base64": "not!!base64"})
    payload = json.loads(content[0].text)
    assert payload["ok"] is False
    assert payload["status"] == 400
    assert "base64" in payload["error"].lower()


def test_call_reprint_job_passes_force_json_query_param(cfg, sample_schema_payload):
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/schema":
            return httpx.Response(200, json=sample_schema_payload)
        if request.url.path.endswith("/reprint"):
            seen["query"] = dict(request.url.params)
            seen["path"] = request.url.path
            return httpx.Response(202, json={"id": "01J", "reprint_mode": "json_rerender"})
        return httpx.Response(404)

    server, cache, _ = _build_with_handler(cfg, handler)
    asyncio.run(cache.boot(retry_budget_s=0.5))

    content = _call_tool(server, "reprint_job", {"id": "01J", "force_json": True})
    payload = json.loads(content[0].text)
    assert payload["ok"] is True
    assert seen["path"] == "/jobs/01J/reprint"
    assert seen["query"] == {"force": "json"}


def test_call_list_recent_jobs_passes_limit(cfg, sample_schema_payload):
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/schema":
            return httpx.Response(200, json=sample_schema_payload)
        if request.url.path == "/jobs":
            seen["limit"] = request.url.params.get("limit")
            return httpx.Response(200, json=[])
        return httpx.Response(404)

    server, cache, _ = _build_with_handler(cfg, handler)
    asyncio.run(cache.boot(retry_budget_s=0.5))

    _call_tool(server, "list_recent_jobs", {"limit": 5})
    assert seen["limit"] == "5"


def test_call_unknown_tool_returns_404_error(cfg, sample_schema_payload):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/schema":
            return httpx.Response(200, json=sample_schema_payload)
        return httpx.Response(404)

    server, cache, _ = _build_with_handler(cfg, handler)
    asyncio.run(cache.boot(retry_budget_s=0.5))

    content = _call_tool(server, "definitely_not_a_tool", {})
    payload = json.loads(content[0].text)
    assert payload["ok"] is False
    assert payload["status"] == 404


@pytest.mark.parametrize(
    "bad_args, expected_text_substring",
    [
        # Missing required `document` — MCP's runtime pre-validates against
        # the tool's inputSchema and rejects before our handler runs. Plain
        # text error, not our wrapped JSON.
        ({}, "document"),
        # Wrong type for `document` — same MCP-layer rejection path.
        ({"document": "not-an-object"}, "object"),
    ],
)
def test_call_print_document_rejects_bad_argument_shape_at_mcp_layer(
    cfg, sample_schema_payload, bad_args, expected_text_substring
):
    """The MCP runtime validates tool arguments against ``inputSchema``
    before dispatching to our handler. This is precisely the property the
    spec wants — an agent cannot request a block type that isn't in the
    live schema, because the schema IS the validator. Verify the bad
    cases produce a clear error mentioning the offending field/type."""
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/schema":
            return httpx.Response(200, json=sample_schema_payload)
        return httpx.Response(404)

    server, cache, _ = _build_with_handler(cfg, handler)
    asyncio.run(cache.boot(retry_budget_s=0.5))

    content = _call_tool(server, "print_document", bad_args)
    text = content[0].text.lower()
    assert "error" in text or "invalid" in text or "required" in text
    assert expected_text_substring in text
