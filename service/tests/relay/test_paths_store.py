from pathlib import Path

from printer.relay.config import RelayConfig
from printer.relay.paths import RelayPaths
from printer.relay.store import AllowList, CredsStore, InviteStore, JobMap


def test_relay_package_imports():
    import printer.relay

    assert hasattr(printer.relay, "__all__")


def test_config_defaults_and_env_override():
    cfg = RelayConfig.from_env({})
    # The default hub URL must fail loudly (matches the MCP convention, spec 9.5).
    assert cfg.hub_url == "https://hub.invalid"
    assert cfg.relay_state_dir == Path("/var/lib/printer/relay")
    assert cfg.local_service_url == "http://127.0.0.1:8000"
    assert cfg.long_poll_wait_s == 25.0
    assert cfg.per_friend_rate_per_hour == 12
    assert cfg.reconnect_backoff_max_s == 30.0

    cfg2 = RelayConfig.from_env({
        "HUB_URL": "https://hub.example.test",
        "PRINTER_RELAY_STATE_DIR": "/tmp/relay",
        "PRINTER_HOST": "127.0.0.1",
        "PRINTER_PORT": "9001",
        "PRINTER_RELAY_LONG_POLL_WAIT_S": "10",
        "PRINTER_RELAY_RATE_PER_HOUR": "3",
    })
    assert cfg2.hub_url == "https://hub.example.test"
    assert cfg2.relay_state_dir == Path("/tmp/relay")
    assert cfg2.local_service_url == "http://127.0.0.1:9001"
    assert cfg2.long_poll_wait_s == 10.0
    assert cfg2.per_friend_rate_per_hour == 3


def test_relay_paths_layout(tmp_path):
    paths = RelayPaths(tmp_path)
    paths.ensure()
    assert paths.creds_path == tmp_path / "creds.json"
    assert paths.allowlist_path == tmp_path / "allowlist.json"
    assert paths.invites_path == tmp_path / "invites.json"
    assert paths.jobmap_path == tmp_path / "jobmap.jsonl"
    assert tmp_path.is_dir()


def test_creds_store_atomic_roundtrip(tmp_path):
    paths = RelayPaths(tmp_path)
    paths.ensure()
    creds = CredsStore(paths.creds_path)
    assert creds.load() is None
    creds.save({
        "printer_id": "prn_1", "handle": "tim", "hub_url": "https://hub.example.test",
        "device_token": "dev-tok", "api_token": "api-tok",
    })
    again = CredsStore(paths.creds_path)
    assert again.load()["handle"] == "tim"
    assert again.load()["device_token"] == "dev-tok"


def test_allowlist_add_remove_contains(tmp_path):
    paths = RelayPaths(tmp_path)
    paths.ensure()
    al = AllowList(paths.allowlist_path)
    assert al.contains("alice") is False
    al.add("alice", display_name="Alice", renderer_version=None)
    assert al.contains("alice") is True
    assert al.handles() == ["alice"]
    # idempotent add updates metadata, never duplicates
    al.add("alice", display_name="Alice A.", renderer_version="1.0.0")
    assert al.handles() == ["alice"]
    assert al.metadata("alice")["display_name"] == "Alice A."
    al.remove("alice")
    assert al.contains("alice") is False


def test_invite_store_records_and_matches(tmp_path):
    paths = RelayPaths(tmp_path)
    paths.ensure()
    inv = InviteStore(paths.invites_path)
    # We record the hub's stable invite_id (NOT the plaintext code); the code is
    # only shown to the user to share out-of-band.
    inv.record("inv_abc123")
    assert inv.has("inv_abc123") is True
    assert inv.has("inv_other") is False


def test_jobmap_append_and_replay_last_wins(tmp_path):
    paths = RelayPaths(tmp_path)
    paths.ensure()
    jm = JobMap(paths.jobmap_path)
    jm.put("hub_job_a", local_job_id="job_local_a", last_status="delivered")
    jm.put("hub_job_a", local_job_id="job_local_a", last_status="printed")
    jm.put("hub_job_b", local_job_id="job_local_b", last_status="delivered")
    # A fresh instance replays the JSONL; last line per id wins.
    reloaded = JobMap(paths.jobmap_path)
    assert reloaded.get("hub_job_a") == {"local_job_id": "job_local_a", "last_status": "printed"}
    assert reloaded.get("hub_job_b") == {"local_job_id": "job_local_b", "last_status": "delivered"}
    # Unfinished = not yet in a terminal status.
    unfinished = reloaded.unfinished(terminal={"printed", "failed"})
    assert "hub_job_a" not in unfinished and "hub_job_b" in unfinished


def test_jobmap_tolerates_corrupt_lines(tmp_path):
    # A power cut mid-append can leave a torn trailing line; a malformed line must
    # be skipped, not crash startup -- otherwise every delivered job is stranded.
    path = tmp_path / "jobmap.jsonl"
    jm = JobMap(path)
    jm.put("good1", local_job_id="loc1", last_status="printed")
    jm.put("good2", local_job_id="loc2", last_status="delivered")
    # Append a non-JSON torn line and a JSON line missing a required key.
    with open(path, "a") as f:
        f.write('{"hub_job_id": "torn", "local_job_id": "lo')  # truncated, no newline
        f.write("\n")
        f.write('{"hub_job_id": "missing_fields"}\n')  # valid JSON, missing keys
    reloaded = JobMap(path)
    # Both well-formed entries survive; the bad lines are dropped.
    assert reloaded.get("good1") == {"local_job_id": "loc1", "last_status": "printed"}
    assert reloaded.get("good2") == {"local_job_id": "loc2", "last_status": "delivered"}
    assert reloaded.get("torn") is None
    assert reloaded.get("missing_fields") is None
