from __future__ import annotations

import asyncio
import json

import httpx

from tests.test_server_tools import _build_with_handler, _call_tool, _list_tools


def test_get_design_guidelines_appears_in_tool_list(cfg, sample_schema_payload):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/schema":
            return httpx.Response(200, json=sample_schema_payload)
        return httpx.Response(404)

    server, cache, _ = _build_with_handler(cfg, handler)
    asyncio.run(cache.boot(retry_budget_s=0.5))

    tools = _list_tools(server)
    names = {t.name for t in tools}
    assert "get_design_guidelines" in names

    tool = next(t for t in tools if t.name == "get_design_guidelines")
    # No-arg tool: empty properties, no extras.
    assert tool.inputSchema["properties"] == {}
    assert tool.inputSchema["additionalProperties"] is False


def test_call_get_design_guidelines_returns_static_payload(cfg, sample_schema_payload):
    """The tool returns the static rulebook with no Pi round-trip — the
    handler below intentionally has no design-related route. Geometry
    constants are imported from printer_core, so this test also pins the
    cross-package contract between mcp-server and printer-core."""
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/schema":
            return httpx.Response(200, json=sample_schema_payload)
        return httpx.Response(404)

    server, cache, _ = _build_with_handler(cfg, handler)
    asyncio.run(cache.boot(retry_budget_s=0.5))

    content = _call_tool(server, "get_design_guidelines", {})
    assert len(content) == 1
    payload = json.loads(content[0].text)

    assert payload["ok"] is True
    result = payload["result"]
    assert result["live_width_px"] == 528
    assert result["print_head_px"] == 576
    assert result["dpmm"] == 8.0
    assert result["max_length_mm_default"] == 2000
    assert "rules_markdown" in result
    assert "IBM Plex Sans" in result["fonts_available"]
    # Spleen was dropped in tasks 1.2 / 2.1 / 4.1; lockstep guard.
    assert "Spleen" not in result["fonts_available"]
    assert "scroll" in result["starter_templates"]
