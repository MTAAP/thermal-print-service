import dataclasses

import pytest
from httpx import ASGITransport, AsyncClient

from printer.app import create_app
from printer.queue.joblog import JobRecord


@pytest.mark.asyncio
async def test_post_test_returns_202(fake_deps):
    app = create_app(fake_deps)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.post("/test")
    assert r.status_code in (200, 202)
    assert "id" in r.json()


@pytest.mark.asyncio
async def test_post_test_returns_503_when_queue_at_max_depth(fake_deps):
    """Codex P1 (#7): ``/test`` enqueues a job, so it must enforce
    ``max_queue_depth`` like ``/print``, ``/print/raw``, and
    ``/jobs/{id}/reprint``. Pre-fix repeated /test calls grew pending
    work without bound, bypassing the cap.
    """
    fake_deps.config = dataclasses.replace(fake_deps.config, max_queue_depth=1)

    app = create_app(fake_deps)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        # One pending phantom job, then /test must 503.
        fake_deps.joblog.append(JobRecord.accepted(
            job_id="phantom", sender=None, document_type="t",
            idempotency_key=None, payload_hash="x", kind="raw",
            estimated_paper_mm=10, renderer_version="0.6.0",
        ))
        r = await ac.post("/test")
    assert r.status_code == 503
    assert r.json() == {"reason": "queue_full"}
