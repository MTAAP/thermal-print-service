import io

import httpx
import pytest

from tprint_design.client import PrintClientError, post_print_raw


def _png_bytes() -> bytes:
    from PIL import Image
    img = Image.new("1", (576, 100), 1)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_post_print_raw_sends_image_png_content_type():
    sent: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        sent["content_type"] = request.headers.get("content-type")
        sent["body_len"] = len(request.content)
        return httpx.Response(202, json={
            "id": "abc", "queued_at": "2026-01-01T00:00:00Z",
            "estimated_paper_mm": 12, "renderer_version": "1.0", "duplicate": False,
        })

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport, base_url="http://pi.test") as client:
        result = post_print_raw(client, _png_bytes(), idempotency_key=None,
                                dry_run=False)
    assert sent["content_type"] == "image/png"
    assert sent["body_len"] > 0
    assert result["id"] == "abc"


def test_post_print_raw_passes_dry_run_query():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(200, content=b"\x89PNG", headers={
            "Content-Type": "image/png",
            "X-Estimated-Paper-Mm": "12",
            "X-Renderer-Version": "1.0",
        })

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport, base_url="http://pi.test") as client:
        post_print_raw(client, _png_bytes(), idempotency_key=None, dry_run=True)
    assert "dry_run=true" in seen["url"]


def test_post_print_raw_raises_on_4xx():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(413, json={"reason": "max_request_bytes"})

    transport = httpx.MockTransport(handler)
    with (
        httpx.Client(transport=transport, base_url="http://pi.test") as client,
        pytest.raises(PrintClientError) as exc,
    ):
        post_print_raw(client, _png_bytes(), idempotency_key=None,
                       dry_run=False)
    assert "413" in str(exc.value)
    assert "max_request_bytes" in str(exc.value)
