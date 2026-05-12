import pytest
from httpx import ASGITransport, AsyncClient

from printer.app import create_app


@pytest.mark.asyncio
async def test_schema_returns_renderer_version_and_block_types(fake_deps):
    app = create_app(fake_deps)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.get("/schema")
    assert r.status_code == 200
    body = r.json()
    assert body["renderer_version"]
    assert "block_types" in body
    assert "header" in body["block_types"]
    assert "qr" in body["block_types"]
    assert "ascii_art" in body["block_types"]
    # All 34 block types declared
    assert len(body["block_types"]) == 34
    # The pydantic JSON schema is included
    assert "blocks" in body
