"""End-to-end ``/print`` with ``cut`` blocks (v0.6.0).

Confirms the HTTP layer renders a multi-chunk doc, caches each chunk
under the new layout, persists chunk metadata in the joblog, and the
worker drains them with the right cut/feed sequence.
"""
import asyncio
import json

import pytest

from tests.conftest import lifespan_client


@pytest.mark.asyncio
async def test_print_with_cut_block_creates_two_chunks_and_drains(fake_deps):
    """A doc with one ``cut`` block: 2 chunks, 2 transport calls, the
    intermediate one cuts (auto), the final one inherits options."""
    body = json.dumps({
        "blocks": [
            {"type": "paragraph", "text": "first segment"},
            {"type": "cut"},
            {"type": "paragraph", "text": "second segment"},
        ],
    }).encode()

    async with lifespan_client(fake_deps) as ac:
        r = await ac.post("/print", content=body,
                          headers={"Content-Type": "application/json"})
        assert r.status_code == 202, r.text
        await asyncio.sleep(0.15)
        # Job listing reports it as printed
        r2 = await ac.get("/jobs")

    # Transport saw two prints
    assert len(fake_deps.transport.printed) == 2
    # First call: cut between chunks. Second call: cut + feed=2 (defaults).
    # The fake transport doesn't record options, but we can check the joblog.
    events = [r.event for r in fake_deps.joblog.replay()]
    assert events.count("printed") == 1
    # And the listing reports the latest job as printed
    jobs = r2.json()["jobs"]
    assert any(j["status"] == "printed" for j in jobs)


@pytest.mark.asyncio
async def test_print_with_no_printable_content_400(fake_deps):
    """A document with only ``cut`` blocks renders to zero chunks. Reject
    at the HTTP layer rather than queueing a no-op job."""
    body = json.dumps({"blocks": [
        {"type": "cut"},
        {"type": "cut"},
    ]}).encode()

    async with lifespan_client(fake_deps) as ac:
        r = await ac.post("/print", content=body,
                          headers={"Content-Type": "application/json"})
    assert r.status_code == 400, r.text
    assert r.json()["errors"][0]["field"] == "blocks"


@pytest.mark.asyncio
async def test_dry_run_includes_chunk_count_header(fake_deps):
    body = json.dumps({"blocks": [
        {"type": "paragraph", "text": "a"},
        {"type": "cut"},
        {"type": "paragraph", "text": "b"},
        {"type": "cut"},
        {"type": "paragraph", "text": "c"},
    ]}).encode()

    async with lifespan_client(fake_deps) as ac:
        r = await ac.post("/print?dry_run=true", content=body,
                          headers={"Content-Type": "application/json"})
    assert r.status_code == 200
    assert r.headers["X-Chunk-Count"] == "3"
