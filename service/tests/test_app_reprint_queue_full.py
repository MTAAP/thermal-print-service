"""Codex P1: ``/jobs/{id}/reprint`` must respect ``max_queue_depth`` like
``/print`` and ``/print/raw``. Pre-fix, repeated reprints could grow the
queue without bound, bypassing the cap that ``/print`` enforces."""
import dataclasses

import pytest
from httpx import ASGITransport, AsyncClient

from printer.app import create_app
from printer.queue.joblog import JobRecord


@pytest.mark.asyncio
async def test_reprint_returns_503_when_queue_at_max_depth(fake_deps):
    fake_deps.config = dataclasses.replace(fake_deps.config, max_queue_depth=1)

    app = create_app(fake_deps)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        # Append a pending job AFTER the worker has started so it stays
        # un-drained: the worker only replays the log at ``start()`` and
        # doesn't watch the file, so this record remains in
        # ``pending_after_replay()`` for the whole test. With
        # max_queue_depth=1 and 1 pending, the next submission must 503.
        fake_deps.joblog.append(JobRecord.accepted(
            job_id="phantom", sender=None, document_type="t",
            idempotency_key=None, payload_hash="x", kind="raw",
            estimated_paper_mm=10, renderer_version="0.5.2",
        ))
        # Reprint hits the depth check before any PNG-cache lookup or JSON
        # re-render, so the target id doesn't need to exist for this check.
        rep = await ac.post("/jobs/whatever/reprint")
    assert rep.status_code == 503
    assert rep.json() == {"reason": "queue_full"}
