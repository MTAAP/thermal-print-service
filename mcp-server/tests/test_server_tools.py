from __future__ import annotations

import asyncio
import base64
import json

import httpx
import pytest

from printer_mcp.config import McpConfig
from printer_mcp.server import (
    build_print_document_input_schema,
    build_print_image_input_schema,
    build_send_to_friend_input_schema,
)
from tests.conftest import build_with_handler, call_tool, list_tools


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


def test_list_tools_returns_expected_set(cfg, sample_schema_payload):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/schema":
            return httpx.Response(200, json=sample_schema_payload)
        return httpx.Response(404)

    server, cache, _, _ = build_with_handler(cfg, handler)
    asyncio.run(cache.boot(retry_budget_s=0.5))

    tools = list_tools(server)
    names = {t.name for t in tools}
    assert names == {
        "print_document",
        "print_image",
        "get_status",
        "list_recent_jobs",
        "reprint_job",
        "print_test",
        "get_design_guidelines",
        "send_to_friend",
        "list_friends",
        "get_friend_schema",
    }


def test_list_tools_print_document_uses_live_schema(cfg, sample_schema_payload):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/schema":
            return httpx.Response(200, json=sample_schema_payload)
        return httpx.Response(404)

    server, cache, _, _ = build_with_handler(cfg, handler)
    asyncio.run(cache.boot(retry_budget_s=0.5))

    tools = list_tools(server)
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

    server, cache, _, _ = build_with_handler(cfg, handler)
    asyncio.run(cache.boot(retry_budget_s=0.05))
    assert cache.snapshot.is_fallback is True

    tools = list_tools(server)
    pd = next(t for t in tools if t.name == "print_document")
    assert "fallback" in pd.inputSchema["properties"]["document"]["description"].lower()


def test_call_get_status_returns_pi_health_payload(cfg, sample_schema_payload):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/schema":
            return httpx.Response(200, json=sample_schema_payload)
        if request.url.path == "/healthz":
            return httpx.Response(200, json={"queue_depth": 0, "uptime_s": 12})
        return httpx.Response(404)

    server, cache, _, _ = build_with_handler(cfg, handler)
    asyncio.run(cache.boot(retry_budget_s=0.5))

    content = call_tool(server, "get_status", {})
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

    server, cache, _, _ = build_with_handler(cfg, handler)
    asyncio.run(cache.boot(retry_budget_s=0.5))

    content = call_tool(
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

    server, cache, _, _ = build_with_handler(cfg, handler)
    asyncio.run(cache.boot(retry_budget_s=0.5))

    content = call_tool(server, "print_document", {"document": {"blocks": []}})
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

    server, cache, _, _ = build_with_handler(cfg, handler)
    asyncio.run(cache.boot(retry_budget_s=0.5))

    encoded = base64.b64encode(raw_png).decode("ascii")
    content = call_tool(server, "print_image", {"png_base64": encoded})
    payload = json.loads(content[0].text)
    assert payload["ok"] is True
    assert seen["body"] == raw_png
    assert seen["ct"] == "image/png"


def test_call_print_image_rejects_invalid_base64(cfg, sample_schema_payload):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/schema":
            return httpx.Response(200, json=sample_schema_payload)
        return httpx.Response(404)

    server, cache, _, _ = build_with_handler(cfg, handler)
    asyncio.run(cache.boot(retry_budget_s=0.5))

    content = call_tool(server, "print_image", {"png_base64": "not!!base64"})
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

    server, cache, _, _ = build_with_handler(cfg, handler)
    asyncio.run(cache.boot(retry_budget_s=0.5))

    content = call_tool(server, "reprint_job", {"id": "01J", "force_json": True})
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

    server, cache, _, _ = build_with_handler(cfg, handler)
    asyncio.run(cache.boot(retry_budget_s=0.5))

    call_tool(server, "list_recent_jobs", {"limit": 5})
    assert seen["limit"] == "5"


def test_call_unknown_tool_returns_404_error(cfg, sample_schema_payload):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/schema":
            return httpx.Response(200, json=sample_schema_payload)
        return httpx.Response(404)

    server, cache, _, _ = build_with_handler(cfg, handler)
    asyncio.run(cache.boot(retry_budget_s=0.5))

    content = call_tool(server, "definitely_not_a_tool", {})
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

    server, cache, _, _ = build_with_handler(cfg, handler)
    asyncio.run(cache.boot(retry_budget_s=0.5))

    content = call_tool(server, "print_document", bad_args)
    text = content[0].text.lower()
    assert "error" in text or "invalid" in text or "required" in text
    assert expected_text_substring in text


def test_send_to_friend_input_schema_is_generic_object():
    s = build_send_to_friend_input_schema()
    assert s["required"] == ["to", "document"]
    assert s["properties"]["document"]["type"] == "object"
    # Generic on purpose -- the hub validates per recipient at send time.
    assert s["properties"]["document"]["additionalProperties"] is True


def test_send_to_friend_happy_path_returns_per_recipient_queued(cfg, sample_schema_payload):
    cfg = McpConfig(print_service_url=cfg.print_service_url, sender=cfg.sender,
                    timeout_s=cfg.timeout_s, hub_url="http://hub.test",
                    hub_api_token="tok-test")

    def pi(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/schema":
            return httpx.Response(200, json=sample_schema_payload)
        return httpx.Response(404)

    def hub(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/send"
        return httpx.Response(202, json={"results": [
            {"to": "alice", "status": "queued", "job_id": "j_a"},
        ]})

    server, cache, _, _ = build_with_handler(cfg, pi, hub_handler=hub)
    asyncio.run(cache.boot(retry_budget_s=0.5))

    content = call_tool(server, "send_to_friend",
                        {"to": ["alice"], "document": {"blocks": []}})
    payload = json.loads(content[0].text)
    assert payload["ok"] is True
    assert payload["result"]["results"][0]["status"] == "queued"
    assert payload["result"]["results"][0]["job_id"] == "j_a"


def test_send_to_friend_incompatible_round_trip_surfaces_detail(cfg, sample_schema_payload):
    """A doc the recipient's schema rejects comes back as incompatible with
    detail (offending field + valid_values) so the agent can self-correct."""
    cfg = McpConfig(print_service_url=cfg.print_service_url, sender=cfg.sender,
                    timeout_s=cfg.timeout_s, hub_url="http://hub.test",
                    hub_api_token="tok-test")

    def pi(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/schema":
            return httpx.Response(200, json=sample_schema_payload)
        return httpx.Response(404)

    def hub(request: httpx.Request) -> httpx.Response:
        # All recipients failed -> hub returns 400, body still carries results.
        return httpx.Response(400, json={"results": [
            {"to": "bob", "status": "incompatible",
             "detail": {"field": ["blocks", 0, "type"],
                        "valid_values": ["paragraph", "header"]}},
        ]})

    server, cache, _, _ = build_with_handler(cfg, pi, hub_handler=hub)
    asyncio.run(cache.boot(retry_budget_s=0.5))

    content = call_tool(server, "send_to_friend",
                        {"to": ["bob"], "document": {"blocks": [{"type": "drop_cap"}]}})
    payload = json.loads(content[0].text)
    # The hub call did not raise; results surface as a normal tool result.
    assert payload["ok"] is True
    r = payload["result"]["results"][0]
    assert r["status"] == "incompatible"
    assert r["detail"]["valid_values"] == ["paragraph", "header"]


def test_send_to_friend_multi_recipient_partial_results(cfg, sample_schema_payload):
    cfg = McpConfig(print_service_url=cfg.print_service_url, sender=cfg.sender,
                    timeout_s=cfg.timeout_s, hub_url="http://hub.test",
                    hub_api_token="tok-test")

    def pi(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/schema":
            return httpx.Response(200, json=sample_schema_payload)
        return httpx.Response(404)

    def hub(request: httpx.Request) -> httpx.Response:
        return httpx.Response(202, json={"results": [
            {"to": "alice", "status": "queued", "job_id": "j_a"},
            {"to": "bob", "status": "incompatible", "detail": {"field": ["x"]}},
            {"to": "ghost", "status": "recipient_unknown"},
        ]})

    server, cache, _, _ = build_with_handler(cfg, pi, hub_handler=hub)
    asyncio.run(cache.boot(retry_budget_s=0.5))

    content = call_tool(server, "send_to_friend",
                        {"to": ["alice", "bob", "ghost"], "document": {"blocks": []}})
    payload = json.loads(content[0].text)
    by = {r["to"]: r["status"] for r in payload["result"]["results"]}
    assert by == {"alice": "queued", "bob": "incompatible", "ghost": "recipient_unknown"}


def test_list_friends_returns_handles_and_renderer_version(cfg, sample_schema_payload):
    cfg = McpConfig(print_service_url=cfg.print_service_url, sender=cfg.sender,
                    timeout_s=cfg.timeout_s, hub_url="http://hub.test",
                    hub_api_token="tok-test")

    def pi(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/schema":
            return httpx.Response(200, json=sample_schema_payload)
        return httpx.Response(404)

    def hub(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/friends"
        return httpx.Response(200, json=[
            {"handle": "alice", "display_name": "Alice",
             "renderer_version": "1.4.2", "online": True},
        ])

    server, cache, _, _ = build_with_handler(cfg, pi, hub_handler=hub)
    asyncio.run(cache.boot(retry_budget_s=0.5))

    content = call_tool(server, "list_friends", {})
    payload = json.loads(content[0].text)
    assert payload["ok"] is True
    assert payload["result"][0]["handle"] == "alice"
    assert payload["result"][0]["renderer_version"] == "1.4.2"


def test_get_friend_schema_returns_block_catalog(cfg, sample_schema_payload):
    cfg = McpConfig(print_service_url=cfg.print_service_url, sender=cfg.sender,
                    timeout_s=cfg.timeout_s, hub_url="http://hub.test",
                    hub_api_token="tok-test")

    def pi(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/schema":
            return httpx.Response(200, json=sample_schema_payload)
        return httpx.Response(404)

    def hub(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/friends/alice/schema"
        return httpx.Response(200, json={
            "renderer_version": "1.4.2",
            "blocks_schema": {"type": "object"},
            "block_types": ["header", "paragraph"],
        })

    server, cache, _, _ = build_with_handler(cfg, pi, hub_handler=hub)
    asyncio.run(cache.boot(retry_budget_s=0.5))

    content = call_tool(server, "get_friend_schema", {"handle": "alice"})
    payload = json.loads(content[0].text)
    assert payload["ok"] is True
    assert payload["result"]["block_types"] == ["header", "paragraph"]


def test_friend_tool_without_token_fails_loudly_but_tool_still_lists(cfg):
    """HUB_API_TOKEN unset: the tool LISTS (always-list, like print_document
    in fallback), but a CALL returns a crisp error instead of an
    unauthenticated request."""
    cfg = McpConfig(print_service_url=cfg.print_service_url, sender=cfg.sender,
                    timeout_s=cfg.timeout_s, hub_url="http://hub.test",
                    hub_api_token="")

    def pi(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"reason": "asleep"})

    server, cache, _, _ = build_with_handler(cfg, pi)
    asyncio.run(cache.boot(retry_budget_s=0.05))

    names = {t.name for t in list_tools(server)}
    assert "send_to_friend" in names  # always-listed

    content = call_tool(server, "list_friends", {})
    payload = json.loads(content[0].text)
    assert payload["ok"] is False
    assert payload["status"] == 400
    assert "HUB_API_TOKEN" in payload["error"]
