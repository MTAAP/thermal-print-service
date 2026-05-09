import asyncio
import io

import pytest
from httpx import ASGITransport, AsyncClient
from PIL import Image

from printer.app import create_app
from tests.conftest import lifespan_client


@pytest.mark.asyncio
async def test_metrics_exposes_expected_counters(fake_deps):
    app = create_app(fake_deps)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.get("/metrics")
    assert r.status_code == 200
    text = r.text
    for metric in (
        "printer_queue_depth",
        "printer_uptime_seconds",
        "printer_paper_mm_total",
        "printer_jobs_printed_total",
        "printer_jobs_failed_total",
        "printer_clock_synchronized",
    ):
        assert metric in text, f"missing metric {metric}"
    # First line is HELP comment per Prometheus convention
    assert text.startswith("# HELP")


@pytest.mark.asyncio
async def test_metrics_increments_after_print(fake_deps):
    buf = io.BytesIO()
    Image.new("1", (576, 100), 1).save(buf, format="PNG")
    png_body = buf.getvalue()

    async with lifespan_client(fake_deps) as ac:
        r0 = await ac.get("/metrics")
        await ac.post("/print/raw", content=png_body,
                      headers={"Content-Type": "image/png"})
        # Yield to the worker so it can drain.
        await asyncio.sleep(0.1)
        r1 = await ac.get("/metrics")

    def _value(text: str, name: str) -> int:
        for line in text.splitlines():
            if line.startswith(name + " "):
                return int(line.split()[1])
        raise AssertionError(f"metric {name} not found")
    assert _value(r1.text, "printer_paper_mm_total") > _value(r0.text, "printer_paper_mm_total")
