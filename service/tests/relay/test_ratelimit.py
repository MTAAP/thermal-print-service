from printer.relay.ratelimit import PerFriendRateLimiter


def _accept(rl, handle, jid, sent_at):
    """allow() the job and, when allowed, commit its slot -- the real per-job flow
    for a job that goes on to be ACCEPTED locally."""
    ok = rl.allow(handle, jid, sent_at)
    if ok:
        rl.record_accepted(handle, jid, sent_at)
    return ok


def test_allows_up_to_limit_then_denies(tmp_path):
    rl = PerFriendRateLimiter(tmp_path / "rate.json", per_hour=2)
    assert _accept(rl, "alice", "j1", "2026-06-03T10:00:00+00:00") is True
    assert _accept(rl, "alice", "j2", "2026-06-03T10:10:00+00:00") is True
    # third within the hour -> denied
    assert _accept(rl, "alice", "j3", "2026-06-03T10:20:00+00:00") is False


def test_window_slides_by_sent_at_not_wall_clock(tmp_path):
    rl = PerFriendRateLimiter(tmp_path / "rate.json", per_hour=1)
    assert _accept(rl, "alice", "j1", "2026-06-03T10:00:00+00:00") is True
    assert _accept(rl, "alice", "j2", "2026-06-03T10:30:00+00:00") is False
    # > 1h later by sent_at: the old timestamp falls out of the window.
    assert _accept(rl, "alice", "j3", "2026-06-03T11:30:00+00:00") is True


def test_per_friend_isolated(tmp_path):
    rl = PerFriendRateLimiter(tmp_path / "rate.json", per_hour=1)
    assert _accept(rl, "alice", "j1", "2026-06-03T10:00:00+00:00") is True
    assert _accept(rl, "bob", "j2", "2026-06-03T10:00:00+00:00") is True  # separate bucket
    assert _accept(rl, "alice", "j3", "2026-06-03T10:05:00+00:00") is False


def test_redelivery_same_hub_job_id_consumes_one_slot(tmp_path):
    # A QUEUE_FULL job is left leased and redelivered with the SAME hub_job_id.
    # Re-evaluating it must not consume a second slot, or an unprinted job could
    # eventually trip its own limit and be wrongly rejected_rate_limited.
    rl = PerFriendRateLimiter(tmp_path / "rate.json", per_hour=1)
    s = "2026-06-03T10:00:00+00:00"
    assert _accept(rl, "alice", "j1", s) is True
    # Same job redelivered N times: still allowed, still only one slot used (the
    # commit is idempotent on hub_job_id).
    assert _accept(rl, "alice", "j1", s) is True
    assert _accept(rl, "alice", "j1", s) is True
    # A genuinely different job within the same hour is still limited.
    assert _accept(rl, "alice", "j2", "2026-06-03T10:05:00+00:00") is False


def test_distinct_jobs_sharing_sent_at_count_separately(tmp_path):
    # The hub stamps ONE sent_at for all recipients of a /send, and two distinct
    # jobs can share a microsecond. Keying on hub_job_id (not sent_at) keeps them
    # counted separately so N distinct prints can't slip through one window slot.
    rl = PerFriendRateLimiter(tmp_path / "rate.json", per_hour=1)
    s = "2026-06-03T10:00:00+00:00"
    assert _accept(rl, "alice", "j1", s) is True
    # A DIFFERENT hub_job_id sharing the exact sent_at must NOT be free.
    assert _accept(rl, "alice", "j2", s) is False


def test_decision_without_commit_does_not_consume_a_slot(tmp_path):
    # allow() is a pure decision -- a deterministic non-accept never calls
    # record_accepted, so it must not burn a slot a misbehaving sender could use
    # to exhaust its own quota.
    rl = PerFriendRateLimiter(tmp_path / "rate.json", per_hour=1)
    # Evaluate a job but DON'T commit it (simulating a malformed/INCOMPATIBLE job).
    assert rl.allow("alice", "j-bad", "2026-06-03T10:00:00+00:00") is True
    # The slot was never consumed, so a real job still gets through.
    assert _accept(rl, "alice", "j-good", "2026-06-03T10:05:00+00:00") is True


def test_counts_persist_across_restart(tmp_path):
    path = tmp_path / "rate.json"
    rl = PerFriendRateLimiter(path, per_hour=1)
    assert _accept(rl, "alice", "j1", "2026-06-03T10:00:00+00:00") is True
    # a fresh instance must still see the recorded slot (and its hub_job_id dedup)
    rl2 = PerFriendRateLimiter(path, per_hour=1)
    assert rl2.allow("alice", "j2", "2026-06-03T10:30:00+00:00") is False
    # the same hub_job_id is still recognized as a redelivery after restart
    assert rl2.allow("alice", "j1", "2026-06-03T10:30:00+00:00") is True


def test_empty_handle_keys_are_pruned_from_disk(tmp_path):
    # Finding 6: a sender whose window has fully aged out must not leave a permanent
    # key, or rate.json grows unbounded (and is rewritten+fsynced every call).
    import json

    path = tmp_path / "rate.json"
    rl = PerFriendRateLimiter(path, per_hour=5)
    rl.record_accepted("alice", "j1", "2026-06-03T10:00:00+00:00")
    # bob records >1h later; alice's lone slot has now aged out of the window.
    rl.record_accepted("bob", "j2", "2026-06-03T12:00:00+00:00")
    on_disk = json.loads(path.read_text())
    assert "bob" in on_disk
    assert "alice" not in on_disk  # pruned: its only slot is older than the cutoff


def test_corrupt_rate_json_falls_back_to_empty(tmp_path):
    # Finding 5: a torn rate.json (power cut mid-write on a Pi Zero) must not crash
    # construction -- an empty window is self-healing.
    path = tmp_path / "rate.json"
    path.write_text("{not valid json")
    rl = PerFriendRateLimiter(path, per_hour=1)  # must not raise
    assert rl.allow("alice", "j1", "2026-06-03T10:00:00+00:00") is True
