from __future__ import annotations

import httpx
import pytest

from printer_mcp.errors import PrintServiceError


def test_client_sets_sender_header(make_client_factory):
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["sender"] = request.headers.get("x-sender")
        return httpx.Response(200, json={"queue_depth": 0})

    client = make_client_factory(handler)

    async def run():
        await client.get_status()

    import asyncio

    asyncio.run(run())
    assert seen["sender"] == "mcp-test"


def test_client_post_print_includes_idempotency_header(make_client_factory):
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["idem"] = request.headers.get("x-idempotency-key")
        seen["body"] = request.content
        return httpx.Response(202, json={"id": "01J", "duplicate": False})

    client = make_client_factory(handler)

    async def run():
        return await client.post_print({"blocks": []}, idempotency_key="abc-123")

    import asyncio

    out = asyncio.run(run())
    assert seen["idem"] == "abc-123"
    assert out["id"] == "01J"


def test_client_post_print_raw_uses_image_png_content_type(make_client_factory):
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["ct"] = request.headers.get("content-type")
        seen["len"] = len(request.content)
        return httpx.Response(202, json={"id": "01J"})

    client = make_client_factory(handler)

    async def run():
        return await client.post_print_raw(b"\x89PNGXYZ")

    import asyncio

    asyncio.run(run())
    assert seen["ct"] == "image/png"
    assert seen["len"] == 7


def test_client_4xx_preserves_structured_error_body(make_client_factory):
    body = {
        "errors": [
            {
                "block_index": 3,
                "field": "align",
                "message": "unknown value 'justified'",
                "valid_values": ["left", "center", "right"],
                "migration_hint": None,
            }
        ]
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json=body)

    client = make_client_factory(handler)

    async def run():
        await client.post_print({"blocks": []})

    import asyncio

    with pytest.raises(PrintServiceError) as exc_info:
        asyncio.run(run())

    assert exc_info.value.status == 400
    assert exc_info.value.body == body
    # Spec contract: agent must see migration_hint + valid_values verbatim.
    assert "unknown value" in exc_info.value.message


def test_client_503_queue_full_summarizes_reason(make_client_factory):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"reason": "queue_full"})

    client = make_client_factory(handler)

    async def run():
        await client.post_print({"blocks": []})

    import asyncio

    with pytest.raises(PrintServiceError) as exc_info:
        asyncio.run(run())

    assert exc_info.value.status == 503
    assert "queue_full" in exc_info.value.message


def test_client_transport_failure_raises_print_service_error_with_status_zero(cfg):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("DNS failed", request=request)

    import asyncio

    from tests.conftest import make_client

    client = make_client(cfg, httpx.MockTransport(handler))

    async def run():
        await client.get_status()

    with pytest.raises(PrintServiceError) as exc_info:
        asyncio.run(run())

    assert exc_info.value.status == 0
    assert "could not reach print service" in exc_info.value.message


def test_decode_png_base64_rejects_garbage():
    from printer_mcp.client import PrintServiceClient

    with pytest.raises(PrintServiceError) as exc_info:
        PrintServiceClient.decode_png_base64("not-base64!!!")
    assert exc_info.value.status == 400
    assert "valid base64" in exc_info.value.message


def test_decode_png_base64_round_trips():
    import base64

    from printer_mcp.client import PrintServiceClient

    raw = b"\x89PNG\r\n\x1a\nXYZ"
    encoded = base64.b64encode(raw).decode("ascii")
    assert PrintServiceClient.decode_png_base64(encoded) == raw
