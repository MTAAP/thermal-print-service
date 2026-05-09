import json

import pytest
from httpx import ASGITransport, AsyncClient
from PIL import Image

import printer.app as app_mod
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


@pytest.mark.asyncio
async def test_print_idempotency_duplicate_skips_render(fake_deps, monkeypatch):
    calls = {"render": 0}

    def fake_render_document_with_chunks(doc, *, fonts, **kwargs):
        calls["render"] += 1
        img = Image.new("1", (576, 8), 1)
        return img, [img], False

    monkeypatch.setattr(app_mod, "render_document_with_chunks", fake_render_document_with_chunks)

    app = create_app(fake_deps)
    body = json.dumps({"blocks": [{"type": "paragraph", "text": "hello"}]}).encode()
    headers = {
        "Content-Type": "application/json",
        "X-Sender": "cron",
        "X-Idempotency-Key": "same-payload",
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r1 = await ac.post("/print", content=body, headers=headers)
        r2 = await ac.post("/print", content=body, headers=headers)

    assert r1.status_code == r2.status_code == 202
    assert r2.json()["duplicate"] is True
    assert calls == {"render": 1}
