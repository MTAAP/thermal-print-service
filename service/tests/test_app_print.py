import json

import pytest
from httpx import ASGITransport, AsyncClient

from printer.app import create_app


@pytest.mark.asyncio
async def test_print_happy(fake_deps):
    app = create_app(fake_deps)
    body = json.dumps({"document_type": "test",
                       "blocks": [{"type": "paragraph", "text": "hello"}]}).encode()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.post("/print", content=body,
                          headers={"Content-Type": "application/json"})
    assert r.status_code == 202
    j = r.json()
    assert "id" in j
    assert j["renderer_version"]
    assert j["duplicate"] is False
    assert j["estimated_paper_mm"] > 0


@pytest.mark.asyncio
async def test_print_invalid_block_type_returns_structured_400(fake_deps):
    app = create_app(fake_deps)
    body = json.dumps({"blocks": [{"type": "marquee", "text": "x"}]}).encode()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.post("/print", content=body,
                          headers={"Content-Type": "application/json"})
    assert r.status_code == 400
    err = r.json()["errors"][0]
    assert err["block_index"] == 0
    # valid_values lists the legitimate block types; "marquee" must NOT be in it
    assert err["valid_values"] is not None
    assert "marquee" not in err["valid_values"]


@pytest.mark.asyncio
async def test_print_max_length_mm_enforced(fake_deps):
    app = create_app(fake_deps)
    # Tiny max_length_mm forces failure on a multi-block doc.
    body = json.dumps({
        "options": {"max_length_mm": 10},
        "blocks": [
            {"type": "header", "text": "x"},
            {"type": "paragraph", "text": "y"},
            {"type": "qr", "data": "https://example"},
        ],
    }).encode()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.post("/print", content=body,
                          headers={"Content-Type": "application/json"})
    assert r.status_code == 400
    assert "max_length_mm" in r.json()["errors"][0]["field"]
