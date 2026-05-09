
from printer.config import ServiceConfig


def test_config_defaults_match_spec(monkeypatch, tmp_path):
    monkeypatch.setenv("PRINTER_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("PRINTER_DEVICE", "/dev/usb/lp0")
    monkeypatch.delenv("PRINTER_HOST", raising=False)
    monkeypatch.delenv("PRINTER_PORT", raising=False)

    cfg = ServiceConfig.from_env()

    assert cfg.host == "127.0.0.1"
    assert cfg.port == 8000
    assert cfg.state_dir == tmp_path
    assert cfg.device == "/dev/usb/lp0"
    # Spec §5
    assert cfg.max_queue_depth == 100
    assert cfg.max_request_bytes == 8 * 1024 * 1024  # 8 MiB hard cap
    assert cfg.max_rendered_height_px == 16_000
    assert cfg.max_raw_height_px == 16_000
    assert cfg.max_decoded_image_pixels == 10_000_000
    assert cfg.idempotency_ttl_s == 24 * 3600
    assert cfg.png_cache_max_bytes == 100 * 1024 * 1024
    assert cfg.png_cache_ttl_s == 7 * 24 * 3600
    assert cfg.json_log_max_jobs == 10_000
    assert cfg.json_log_max_bytes == 100 * 1024 * 1024
    assert cfg.retry_interval_s == 300
    assert cfg.max_retry_age_s == 24 * 3600
