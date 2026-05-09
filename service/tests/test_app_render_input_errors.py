"""Codex P2: schema-valid input that fails at render time because of bad
USER content (malformed PNG bytes inside an ``image`` block, invalid
characters for an EAN13 ``barcode``) must return a structured 400, not a
generic 500. Pre-fix, ``render_document`` raised a generic ``Exception``
which the app wrapped into a 500 — misclassifying client errors as
server faults and inviting blind retries."""
import base64
import dataclasses
import io
import json

import pytest
from httpx import ASGITransport, AsyncClient
from PIL import Image

from printer.app import create_app


@pytest.mark.asyncio
async def test_image_block_malformed_png_returns_400(fake_deps):
    # Schema-valid (non-empty base64), but the decoded bytes are not an
    # image — Pillow will raise UnidentifiedImageError.
    bad_png = base64.b64encode(b"this is definitely not a PNG").decode()
    body = json.dumps({
        "blocks": [
            {"type": "paragraph", "text": "ok"},
            {"type": "image", "png_base64": bad_png, "width_px": 200,
             "align": "center", "bleed": False, "dither": "atkinson"},
        ],
    }).encode()
    app = create_app(fake_deps)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.post("/print", content=body,
                          headers={"Content-Type": "application/json"})
    assert r.status_code == 400, r.text
    err = r.json()["errors"][0]
    # block_index pinpoints the bad block (index 1, after the paragraph)
    assert err["block_index"] == 1
    assert err["field"] == "png_base64"
    assert "image" in err["message"].lower() or "png" in err["message"].lower()


@pytest.mark.asyncio
async def test_barcode_block_invalid_data_returns_400(fake_deps):
    # EAN13 requires 12 numeric digits; alphabetic data must fail at the
    # render boundary (schema doesn't constrain content per format).
    body = json.dumps({
        "blocks": [
            {"type": "barcode", "format": "EAN13", "data": "NOTAVALIDEAN"},
        ],
    }).encode()
    app = create_app(fake_deps)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.post("/print", content=body,
                          headers={"Content-Type": "application/json"})
    assert r.status_code == 400, r.text
    err = r.json()["errors"][0]
    assert err["block_index"] == 0
    assert err["field"] == "data"


@pytest.mark.asyncio
async def test_image_block_valid_png_still_renders(fake_deps):
    """Regression guard: the new exception handling must not break the
    happy path. A real PNG must still render and 202."""
    buf = io.BytesIO()
    Image.new("1", (200, 50), 1).save(buf, format="PNG")
    good_png = base64.b64encode(buf.getvalue()).decode()
    body = json.dumps({
        "blocks": [
            {"type": "image", "png_base64": good_png, "width_px": 200,
             "align": "center", "bleed": False, "dither": "atkinson"},
        ],
    }).encode()
    app = create_app(fake_deps)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.post("/print", content=body,
                          headers={"Content-Type": "application/json"})
    assert r.status_code == 202, r.text


@pytest.mark.asyncio
async def test_image_block_rejects_images_over_decoded_pixel_cap(fake_deps):
    fake_deps.config = dataclasses.replace(fake_deps.config, max_decoded_image_pixels=50)
    buf = io.BytesIO()
    Image.new("1", (51, 1), 1).save(buf, format="PNG")
    good_png = base64.b64encode(buf.getvalue()).decode()
    body = json.dumps({
        "blocks": [
            {"type": "image", "png_base64": good_png, "width_px": 51,
             "align": "center", "bleed": False, "dither": "atkinson"},
        ],
    }).encode()
    app = create_app(fake_deps)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.post("/print", content=body,
                          headers={"Content-Type": "application/json"})
    assert r.status_code == 413
    assert r.json()["reason"] == "max_decoded_image_pixels"
