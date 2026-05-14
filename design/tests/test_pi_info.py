import json

from tprint_design.pi_info import effective_max_length_mm, refresh_cache


def test_explicit_flag_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("PRINT_SERVICE_URL", "http://invalid")
    assert effective_max_length_mm(flag_value=1234, cache_dir=tmp_path) == 1234


def test_falls_back_to_bundled_default(tmp_path, monkeypatch):
    monkeypatch.delenv("PRINT_SERVICE_URL", raising=False)
    assert effective_max_length_mm(flag_value=None, cache_dir=tmp_path) == 2000


def test_uses_cache_if_present_and_fresh(tmp_path, monkeypatch):
    monkeypatch.delenv("PRINT_SERVICE_URL", raising=False)
    cache = tmp_path / "pi-info.json"
    cache.write_text(json.dumps({"max_length_mm_default": 3000, "ts": 9_999_999_999}))
    assert effective_max_length_mm(flag_value=None, cache_dir=tmp_path) == 3000


def test_ignores_stale_cache(tmp_path, monkeypatch):
    monkeypatch.delenv("PRINT_SERVICE_URL", raising=False)
    cache = tmp_path / "pi-info.json"
    cache.write_text(json.dumps({"max_length_mm_default": 3000, "ts": 0}))
    assert effective_max_length_mm(flag_value=None, cache_dir=tmp_path) == 2000


def test_refresh_cache_writes_payload(tmp_path):
    refresh_cache(cache_dir=tmp_path, payload={"max_length_mm_default": 4000})
    data = json.loads((tmp_path / "pi-info.json").read_text())
    assert data["max_length_mm_default"] == 4000
    assert "ts" in data
