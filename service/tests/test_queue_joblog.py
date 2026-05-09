import json

from printer.queue.joblog import JobLog, JobRecord


def test_append_and_replay_roundtrip(state_dir):
    log = JobLog(state_dir / "log.jsonl")
    a = JobRecord.accepted(
        job_id="01J9X-FOO",
        sender="cron",
        document_type="briefing",
        idempotency_key="2026-05-09",
        payload_hash="deadbeef",
        kind="document",
        estimated_paper_mm=187,
        renderer_version="0.1.0",
    )
    log.append(a)
    log.append(JobRecord.printed(job_id="01J9X-FOO", paper_used_mm=189))

    replayed = list(log.replay())
    assert len(replayed) == 2
    assert replayed[0].event == "accepted"
    assert replayed[1].event == "printed"


def test_replay_skips_corrupt_lines(state_dir):
    p = state_dir / "log.jsonl"
    p.write_text(
        json.dumps({"event": "accepted", "job_id": "OK", "ts": "2026-05-09T00:00:00Z",
                    "sender": "cron", "document_type": "briefing",
                    "idempotency_key": None, "payload_hash": "x", "kind": "document",
                    "estimated_paper_mm": 1, "renderer_version": "0.1.0"}) + "\n"
        + "GARBAGE NOT JSON\n"
        + json.dumps({"event": "printed", "job_id": "OK",
                      "ts": "2026-05-09T00:00:01Z",
                      "paper_used_mm": 1}) + "\n"
    )
    log = JobLog(p)
    replayed = list(log.replay())
    assert [r.event for r in replayed] == ["accepted", "printed"]


def test_pending_set_after_replay(state_dir):
    log = JobLog(state_dir / "log.jsonl")
    log.append(JobRecord.accepted(job_id="A", sender=None, document_type="t",
                                  idempotency_key=None, payload_hash="x", kind="document",
                                  estimated_paper_mm=1, renderer_version="0.1.0"))
    log.append(JobRecord.accepted(job_id="B", sender=None, document_type="t",
                                  idempotency_key=None, payload_hash="x", kind="document",
                                  estimated_paper_mm=1, renderer_version="0.1.0"))
    log.append(JobRecord.printed(job_id="A", paper_used_mm=10))

    pending = log.pending_after_replay()
    assert [j.job_id for j in pending] == ["B"]


def _accepted(jid: str, ts: str) -> JobRecord:
    """Build an ``accepted`` record with a chosen ts so prune ordering is
    deterministic. The factory ``JobRecord.accepted`` stamps ``_now()``
    which makes ordering tests racy."""
    return JobRecord(
        event="accepted", job_id=jid, ts=ts,
        sender=None, document_type="t",
        idempotency_key=None, payload_hash="x", kind="document",
        estimated_paper_mm=1, renderer_version="0.6.0",
        auto_cut=True, feed_lines_after=2, expires_at=None,
        chunk_count=1, trailing_cut=False,
    )


def _printed(jid: str, ts: str) -> JobRecord:
    return JobRecord(event="printed", job_id=jid, ts=ts, paper_used_mm=10)


def test_prune_under_limits_is_noop(state_dir):
    """Codex P2 (#8): JobLog rotation. Under both limits → no rewrite,
    same byte content."""
    p = state_dir / "log.jsonl"
    log = JobLog(p)
    log.append(_accepted("A", "2026-01-01T00:00:00Z"))
    log.append(_printed("A", "2026-01-01T00:00:01Z"))
    before = p.read_bytes()

    log.prune(max_records=100, max_bytes=10_000_000)

    assert p.read_bytes() == before


def test_prune_drops_oldest_terminal_jobs_over_record_limit(state_dir):
    """Over the record cap, drop oldest *terminal* jobs first. Order is
    by the timestamp of the job's most recent event."""
    p = state_dir / "log.jsonl"
    log = JobLog(p)
    # Three terminal jobs, oldest finished first; one pending.
    log.append(_accepted("A", "2026-01-01T00:00:00Z"))
    log.append(_printed("A", "2026-01-01T00:00:01Z"))
    log.append(_accepted("B", "2026-01-02T00:00:00Z"))
    log.append(_printed("B", "2026-01-02T00:00:01Z"))
    log.append(_accepted("C", "2026-01-03T00:00:00Z"))
    log.append(_printed("C", "2026-01-03T00:00:01Z"))
    log.append(_accepted("PEND", "2026-01-04T00:00:00Z"))

    # 7 records → cap to 5 means drop the oldest terminal job (A's two).
    log.prune(max_records=5, max_bytes=10_000_000)

    remaining = [(r.event, r.job_id) for r in log.replay()]
    assert ("accepted", "A") not in remaining
    assert ("printed", "A") not in remaining
    # B, C, and PEND survive.
    assert [jid for ev, jid in remaining] == ["B", "B", "C", "C", "PEND"]


def test_prune_drops_oldest_terminal_jobs_over_byte_limit(state_dir):
    """Byte limit is a fallback for record-based pruning (e.g. one job has
    many retry events). Should still drop oldest terminal jobs first."""
    p = state_dir / "log.jsonl"
    log = JobLog(p)
    log.append(_accepted("OLD", "2026-01-01T00:00:00Z"))
    log.append(_printed("OLD", "2026-01-01T00:00:01Z"))
    log.append(_accepted("NEW", "2026-02-01T00:00:00Z"))
    log.append(_printed("NEW", "2026-02-01T00:00:01Z"))
    size = p.stat().st_size

    # Force a byte budget that fits only the NEW pair.
    log.prune(max_records=10, max_bytes=size // 2 + 5)

    remaining = [r.job_id for r in log.replay()]
    assert "OLD" not in remaining
    assert remaining == ["NEW", "NEW"]


def test_prune_never_drops_pending_jobs(state_dir):
    """Pending jobs MUST survive any prune — replay re-enqueues them.
    Even when the log is well over budget and dropping all terminal jobs
    isn't enough, pending records stay so the worker can drain them."""
    p = state_dir / "log.jsonl"
    log = JobLog(p)
    log.append(_accepted("PEND-1", "2026-01-01T00:00:00Z"))
    log.append(_accepted("PEND-2", "2026-01-02T00:00:00Z"))
    log.append(_accepted("DONE", "2026-01-03T00:00:00Z"))
    log.append(_printed("DONE", "2026-01-03T00:00:01Z"))

    # Cap is impossibly tight: even after dropping DONE we'd be over.
    log.prune(max_records=1, max_bytes=10)

    remaining = [r.job_id for r in log.replay()]
    # DONE is dropped; PEND-1 and PEND-2 always stay.
    assert "DONE" not in remaining
    assert "PEND-1" in remaining and "PEND-2" in remaining
