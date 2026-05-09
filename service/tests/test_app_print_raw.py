import dataclasses
import io

import pytest
from httpx import ASGITransport, AsyncClient
from PIL import Image

from printer.app import create_app


def _png_bytes(width=576, height=200):
    buf = io.BytesIO()
    Image.new("1", (width, height), 1).save(buf, format="PNG")
    return buf.getvalue()


@pytest.mark.asyncio
async def test_print_raw_accepts_576_wide_png(fake_deps):
    app = create_app(fake_deps)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.post("/print/raw", content=_png_bytes(),
                          headers={"Content-Type": "image/png"})
    assert r.status_code == 202
    body = r.json()
    assert body["duplicate"] is False
    assert body["estimated_paper_mm"] > 0


@pytest.mark.asyncio
async def test_print_raw_rejects_wrong_width(fake_deps):
    app = create_app(fake_deps)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.post("/print/raw", content=_png_bytes(width=500),
                          headers={"Content-Type": "image/png"})
    assert r.status_code == 400
    assert r.json()["errors"][0]["field"] == "width"


@pytest.mark.asyncio
async def test_print_raw_rejects_non_png_content_type(fake_deps):
    app = create_app(fake_deps)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.post("/print/raw", content=_png_bytes(),
                          headers={"Content-Type": "application/octet-stream"})
    assert r.status_code == 400
    assert r.json()["errors"][0]["field"] == "Content-Type"


@pytest.mark.asyncio
async def test_print_raw_rejects_images_over_decoded_pixel_cap(fake_deps):
    fake_deps.config = dataclasses.replace(fake_deps.config, max_decoded_image_pixels=575)
    app = create_app(fake_deps)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.post("/print/raw", content=_png_bytes(width=576, height=1),
                          headers={"Content-Type": "image/png"})
    assert r.status_code == 413
    assert r.json()["reason"] == "max_decoded_image_pixels"


@pytest.mark.asyncio
async def test_print_raw_idempotency_returns_original_id(fake_deps):
    app = create_app(fake_deps)
    body = _png_bytes()
    headers = {"Content-Type": "image/png", "X-Sender": "cron",
               "X-Idempotency-Key": "K1"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r1 = await ac.post("/print/raw", content=body, headers=headers)
        r2 = await ac.post("/print/raw", content=body, headers=headers)
    assert r1.status_code == r2.status_code == 202
    assert r1.json()["id"] == r2.json()["id"]
    assert r2.json()["duplicate"] is True


@pytest.mark.asyncio
async def test_print_raw_idempotency_conflict_on_payload_drift(fake_deps):
    app = create_app(fake_deps)
    headers = {"Content-Type": "image/png", "X-Sender": "cron",
               "X-Idempotency-Key": "K2"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r1 = await ac.post("/print/raw", content=_png_bytes(height=100), headers=headers)
        r2 = await ac.post("/print/raw", content=_png_bytes(height=200), headers=headers)
    assert r1.status_code == 202
    assert r2.status_code == 409
