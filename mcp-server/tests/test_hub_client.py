from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from printer_mcp.errors import PrintServiceError


def _run(coro):
    return asyncio.run(coro)


def test_send_returns_results_on_202_partial(make_hub_client_factory):
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content.decode())
        return httpx.Response(202, json={"results": [
            {"to": "alice", "status": "queued", "job_id": "j_a"},
            {"to": "carol", "status": "not_friend"},
        ]})

    client = make_hub_client_factory(handler)
    out = _run(client.send(to=["alice", "carol"],
                           document={"blocks": [{"type": "paragraph"}]},
                           idempotency_key="k1"))
    assert seen["auth"] == "Bearer tok-test"
    # idempotency_key rides in the JSON body, NOT a header (differs from the Pi).
    assert seen["body"]["idempotency_key"] == "k1"
    assert seen["body"]["to"] == ["alice", "carol"]
    assert out["results"][0]["status"] == "queued"
    assert out["results"][1]["status"] == "not_friend"


def test_send_returns_results_on_400_all_failed(make_hub_client_factory):
    """When every recipient fails the hub returns 400, but the body still
    carries per-recipient results (incl. incompatible.detail). The client
    must surface that body for self-correction, NOT raise."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"results": [
            {"to": "bob", "status": "incompatible",
             "detail": {"field": ["blocks", 0, "type"],
                        "valid_values": ["paragraph", "header"]}},
        ]})

    client = make_hub_client_factory(handler)
    out = _run(client.send(to=["bob"], document={"blocks": [{"type": "drop_cap"}]},
                           idempotency_key=None))
    assert out["results"][0]["status"] == "incompatible"
    assert out["results"][0]["detail"]["valid_values"] == ["paragraph", "header"]


def test_send_raises_on_auth_failure(make_hub_client_factory):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"detail": "bad token"})

    client = make_hub_client_factory(handler)
    with pytest.raises(PrintServiceError) as ei:
        _run(client.send(to=["bob"], document={"blocks": []}, idempotency_key=None))
    assert ei.value.status == 403


def test_send_raises_on_5xx(make_hub_client_factory):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, text="bad gateway")

    client = make_hub_client_factory(handler)
    with pytest.raises(PrintServiceError) as ei:
        _run(client.send(to=["bob"], document={"blocks": []}, idempotency_key=None))
    assert ei.value.status == 502


def test_send_transport_failure_is_status_zero(make_hub_client_factory):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("DNS failed", request=request)

    client = make_hub_client_factory(handler)
    with pytest.raises(PrintServiceError) as ei:
        _run(client.send(to=["bob"], document={"blocks": []}, idempotency_key=None))
    assert ei.value.status == 0
    assert "could not reach hub" in ei.value.message


def test_list_friends_returns_array(make_hub_client_factory):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/friends"
        return httpx.Response(200, json=[
            {"handle": "alice", "display_name": "Alice",
             "renderer_version": "1.4.2", "online": True},
        ])

    client = make_hub_client_factory(handler)
    out = _run(client.list_friends())
    assert out[0]["handle"] == "alice"
    assert out[0]["renderer_version"] == "1.4.2"


def test_get_friend_schema_returns_triple(make_hub_client_factory):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/friends/alice/schema"
        return httpx.Response(200, json={
            "renderer_version": "1.4.2",
            "blocks_schema": {"type": "object"},
            "block_types": ["header", "paragraph"],
        })

    client = make_hub_client_factory(handler)
    out = _run(client.get_friend_schema("alice"))
    assert out["renderer_version"] == "1.4.2"
    assert out["block_types"] == ["header", "paragraph"]
