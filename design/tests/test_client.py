import io

import httpx
import pytest

from tprint_design.client import (
    PrintClientError,
    derive_idempotency_key,
    post_print_raw,
    post_print_raw_with_retry,
)


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


def test_derive_idempotency_key_is_stable_for_same_bytes():
    a = _png_bytes()
    assert derive_idempotency_key(a) == derive_idempotency_key(a)
    # Stable shape: 16 hex chars
    k = derive_idempotency_key(a)
    assert len(k) == 16
    assert all(c in "0123456789abcdef" for c in k)


def test_derive_idempotency_key_differs_for_different_bytes():
    from PIL import Image
    other = io.BytesIO()
    Image.new("1", (576, 200), 1).save(other, format="PNG")
    assert derive_idempotency_key(_png_bytes()) != derive_idempotency_key(other.getvalue())


def test_post_print_raw_with_retry_recovers_after_transient_failures():
    """First two attempts raise a transport error; third succeeds."""
    attempt = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempt["n"] += 1
        if attempt["n"] < 3:
            raise httpx.ConnectError("simulated transient")
        return httpx.Response(202, json={
            "id": "ok", "queued_at": "2026-01-01T00:00:00Z",
            "estimated_paper_mm": 10, "renderer_version": "1.0",
            "duplicate": False,
        })

    sleeps: list[float] = []
    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport, base_url="http://pi.test") as client:
        result = post_print_raw_with_retry(
            client, _png_bytes(),
            idempotency_key="key",
            dry_run=False,
            attempts=3,
            backoff_base_s=1.0,
            sleep=sleeps.append,
        )
    assert result["id"] == "ok"
    assert attempt["n"] == 3
    # Exponential backoff: sleep(1), sleep(4). No sleep before first attempt
    # or after the final successful one.
    assert sleeps == [1.0, 4.0]


def test_post_print_raw_with_retry_raises_after_exhausted_attempts():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("always down")

    sleeps: list[float] = []
    transport = httpx.MockTransport(handler)
    with (
        httpx.Client(transport=transport, base_url="http://pi.test") as client,
        pytest.raises(httpx.HTTPError),
    ):
        post_print_raw_with_retry(
            client, _png_bytes(),
            idempotency_key="key",
            dry_run=False,
            attempts=3,
            backoff_base_s=1.0,
            sleep=sleeps.append,
        )
    # Two backoffs between three attempts; no sleep after the final fail.
    assert sleeps == [1.0, 4.0]


def test_post_print_raw_with_retry_does_not_retry_on_4xx():
    """Structured rejections from the service are decisive — no retry."""
    attempt = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempt["n"] += 1
        return httpx.Response(413, json={"reason": "max_request_bytes"})

    sleeps: list[float] = []
    transport = httpx.MockTransport(handler)
    with (
        httpx.Client(transport=transport, base_url="http://pi.test") as client,
        pytest.raises(PrintClientError),
    ):
        post_print_raw_with_retry(
            client, _png_bytes(),
            idempotency_key="key",
            dry_run=False,
            attempts=3,
            sleep=sleeps.append,
        )
    assert attempt["n"] == 1
    assert sleeps == []
