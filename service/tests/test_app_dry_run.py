import json

import pytest
from httpx import ASGITransport, AsyncClient

from printer.app import create_app


@pytest.mark.asyncio
async def test_dry_run_returns_png_no_print(fake_deps):
    app = create_app(fake_deps)
    body = json.dumps({"blocks": [{"type": "paragraph", "text": "hi"}]}).encode()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.post("/print?dry_run=true", content=body,
                          headers={"Content-Type": "application/json"})
        assert r.status_code == 200
        assert r.headers["content-type"] == "image/png"
        assert r.content[:8] == b"\x89PNG\r\n\x1a\n"
        # Annotated headers
        assert "x-estimated-paper-mm" in {k.lower() for k in r.headers}
        assert r.headers["x-renderer-version"]
        # No job committed
        listing = await ac.get("/jobs")
        assert listing.json()["jobs"] == []


@pytest.mark.asyncio
async def test_dry_run_print_raw_returns_input_png_no_print(fake_deps):
    import io

    from PIL import Image
    buf = io.BytesIO()
    Image.new("1", (576, 100), 1).save(buf, format="PNG")
    body = buf.getvalue()
    app = create_app(fake_deps)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.post("/print/raw?dry_run=true", content=body,
                          headers={"Content-Type": "image/png"})
        assert r.status_code == 200
        assert r.headers["content-type"] == "image/png"
        assert r.content == body  # echoes input
        # No job committed
        listing = await ac.get("/jobs")
        assert listing.json()["jobs"] == []
