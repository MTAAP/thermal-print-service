from printer.relay.ratelimit import PerFriendRateLimiter


def test_allows_up_to_limit_then_denies(tmp_path):
    rl = PerFriendRateLimiter(tmp_path / "rate.json", per_hour=2)
    base = "2026-06-03T10:00:00+00:00"
    assert rl.check_and_record("alice", base) is True
    assert rl.check_and_record("alice", "2026-06-03T10:10:00+00:00") is True
    # third within the hour -> denied
    assert rl.check_and_record("alice", "2026-06-03T10:20:00+00:00") is False


def test_window_slides_by_sent_at_not_wall_clock(tmp_path):
    rl = PerFriendRateLimiter(tmp_path / "rate.json", per_hour=1)
    assert rl.check_and_record("alice", "2026-06-03T10:00:00+00:00") is True
    assert rl.check_and_record("alice", "2026-06-03T10:30:00+00:00") is False
    # > 1h later by sent_at: the old timestamp falls out of the window.
    assert rl.check_and_record("alice", "2026-06-03T11:30:00+00:00") is True


def test_per_friend_isolated(tmp_path):
    rl = PerFriendRateLimiter(tmp_path / "rate.json", per_hour=1)
    assert rl.check_and_record("alice", "2026-06-03T10:00:00+00:00") is True
    assert rl.check_and_record("bob", "2026-06-03T10:00:00+00:00") is True  # separate bucket
    assert rl.check_and_record("alice", "2026-06-03T10:05:00+00:00") is False


def test_counts_persist_across_restart(tmp_path):
    path = tmp_path / "rate.json"
    rl = PerFriendRateLimiter(path, per_hour=1)
    assert rl.check_and_record("alice", "2026-06-03T10:00:00+00:00") is True
    # a fresh instance must still see the recorded timestamp
    rl2 = PerFriendRateLimiter(path, per_hour=1)
    assert rl2.check_and_record("alice", "2026-06-03T10:30:00+00:00") is False
