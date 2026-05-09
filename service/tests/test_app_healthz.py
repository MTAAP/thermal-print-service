import pytest
from httpx import ASGITransport, AsyncClient

from printer.app import create_app


@pytest.mark.asyncio
async def test_healthz_shape(fake_deps):
    app = create_app(fake_deps)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    for k in ("printer_connected", "paper_present", "cover_closed",
              "clock_synchronized", "queue_depth", "last_print_at", "uptime_s"):
        assert k in body
