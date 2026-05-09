import time

import pytest

from printer.queue.idempotency import (
    IdempotencyCache,
    IdempotencyConflict,
    IdempotencyHit,
)


def test_record_then_lookup_returns_hit(state_dir):
    c = IdempotencyCache(state_dir / "idem.jsonl", ttl_s=3600)
    c.record(scope="cron", key="2026-05-09", payload_hash="hashA",
             job_id="01J", queued_at="2026-05-09T00:00:00Z")
    hit = c.lookup(scope="cron", key="2026-05-09", payload_hash="hashA")
    assert isinstance(hit, IdempotencyHit)
    assert hit.job_id == "01J"
    assert hit.queued_at == "2026-05-09T00:00:00Z"


def test_lookup_miss_returns_none(state_dir):
    c = IdempotencyCache(state_dir / "idem.jsonl", ttl_s=3600)
    assert c.lookup(scope="cron", key="missing", payload_hash="x") is None


def test_same_key_different_payload_raises_conflict(state_dir):
    c = IdempotencyCache(state_dir / "idem.jsonl", ttl_s=3600)
    c.record(scope="cron", key="K", payload_hash="A",
             job_id="01J", queued_at="2026-05-09T00:00:00Z")
    with pytest.raises(IdempotencyConflict):
        c.lookup(scope="cron", key="K", payload_hash="B")


def test_expired_entries_are_invisible(state_dir):
    c = IdempotencyCache(state_dir / "idem.jsonl", ttl_s=0)
    c.record(scope="cron", key="K", payload_hash="A",
             job_id="01J", queued_at="2026-05-09T00:00:00Z")
    time.sleep(0.05)
    assert c.lookup(scope="cron", key="K", payload_hash="A") is None


def test_no_sender_uses_anonymous_scope(state_dir):
    c = IdempotencyCache(state_dir / "idem.jsonl", ttl_s=3600)
    c.record(scope=None, key="K", payload_hash="A",
             job_id="01J", queued_at="2026-05-09T00:00:00Z")
    hit = c.lookup(scope=None, key="K", payload_hash="A")
    assert hit is not None
