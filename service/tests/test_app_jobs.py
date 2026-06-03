import io

import pytest
from httpx import ASGITransport, AsyncClient
from PIL import Image

from printer.app import create_app
from printer.queue.joblog import JobRecord


def _png_bytes():
    buf = io.BytesIO()
    Image.new("1", (576, 100), 1).save(buf, format="PNG")
    return buf.getvalue()


@pytest.mark.asyncio
async def test_jobs_lists_recent_then_reprints_from_cache(fake_deps):
    app = create_app(fake_deps)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.post("/print/raw", content=_png_bytes(),
                          headers={"Content-Type": "image/png", "X-Sender": "test"})
        job_id = r.json()["id"]
        listing = await ac.get("/jobs")
        ids = [j["id"] for j in listing.json()["jobs"]]
        assert job_id in ids
        rep = await ac.post(f"/jobs/{job_id}/reprint")
    assert rep.status_code == 202
    assert rep.json()["id"] != job_id


@pytest.mark.asyncio
async def test_get_job_by_id_returns_single_entry(fake_deps):
    app = create_app(fake_deps)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.post("/print/raw", content=_png_bytes(),
                          headers={"Content-Type": "image/png", "X-Sender": "test"})
        job_id = r.json()["id"]
        detail = await ac.get(f"/jobs/{job_id}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["id"] == job_id
    assert body["sender"] == "test"
    assert body["status"] in ("queued", "printed")
    # Same shape as the /jobs list entry — no envelope.
    assert "reprint_url" in body
    assert body["reprint_url"] == f"/jobs/{job_id}/reprint"


@pytest.mark.asyncio
async def test_get_job_reports_in_progress_retry_not_queued(fake_deps):
    # A job that the worker has attempted and is backing off to retry has an
    # `accepted` + `retry` record but no terminal record. Status must reflect
    # the latest event ("retry"), not fall back to "queued".
    app = create_app(fake_deps)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.post("/print/raw", content=_png_bytes(),
                          headers={"Content-Type": "image/png", "X-Sender": "test"})
        job_id = r.json()["id"]
        fake_deps.joblog.append(JobRecord.retry(job_id=job_id, detail="printer offline"))
        detail = await ac.get(f"/jobs/{job_id}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["status"] == "retry"
    assert body["printed_at"] is None


@pytest.mark.asyncio
async def test_get_job_by_id_returns_404_for_unknown(fake_deps):
    app = create_app(fake_deps)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.get("/jobs/no-such-job-id")
    assert r.status_code == 404
    assert r.json()["reason"] == "job_not_found"


@pytest.mark.asyncio
async def test_get_job_by_id_rejects_glob_metacharacters(fake_deps):
    """Same defense as /jobs/{id}/reprint — wildcards in job_id must
    not reach the cache layer."""
    app = create_app(fake_deps)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.get("/jobs/%2A")  # URL-decodes to "*"
    assert r.status_code == 404
    assert r.json()["reason"] == "job_not_found"
