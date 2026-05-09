from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _env_int(name: str, default: int) -> int:
    return int(os.environ.get(name, default))


@dataclass(frozen=True)
class ServiceConfig:
    host: str
    port: int
    state_dir: Path
    device: str
    font_dir: Path

    # Caps (spec §5)
    max_queue_depth: int = 100
    max_request_bytes: int = 8 * 1024 * 1024
    max_rendered_height_px: int = 16_000
    max_raw_height_px: int = 16_000
    max_decoded_image_pixels: int = 10_000_000
    idempotency_ttl_s: int = 24 * 3600
    png_cache_max_bytes: int = 100 * 1024 * 1024
    png_cache_ttl_s: int = 7 * 24 * 3600
    json_log_max_jobs: int = 10_000
    json_log_max_bytes: int = 100 * 1024 * 1024
    retry_interval_s: int = 300
    max_retry_age_s: int = 24 * 3600

    @classmethod
    def from_env(cls) -> ServiceConfig:
        return cls(
            host=os.environ.get("PRINTER_HOST", "127.0.0.1"),
            port=_env_int("PRINTER_PORT", 8000),
            state_dir=Path(os.environ.get("PRINTER_STATE_DIR", "/var/lib/printer")),
            device=os.environ.get("PRINTER_DEVICE", "/dev/usb/lp0"),
            font_dir=Path(os.environ.get(
                "PRINTER_FONT_DIR",
                str(Path(__file__).resolve().parents[2] / "assets" / "fonts"),
            )),
            max_queue_depth=_env_int("PRINTER_MAX_QUEUE_DEPTH", 100),
            max_request_bytes=_env_int("PRINTER_MAX_REQUEST_BYTES", 8 * 1024 * 1024),
            max_rendered_height_px=_env_int("PRINTER_MAX_RENDERED_HEIGHT_PX", 16_000),
            max_raw_height_px=_env_int("PRINTER_MAX_RAW_HEIGHT_PX", 16_000),
            max_decoded_image_pixels=_env_int("PRINTER_MAX_DECODED_IMAGE_PIXELS", 10_000_000),
            idempotency_ttl_s=_env_int("PRINTER_IDEMPOTENCY_TTL_S", 24 * 3600),
            png_cache_max_bytes=_env_int("PRINTER_PNG_CACHE_MAX_BYTES", 100 * 1024 * 1024),
            png_cache_ttl_s=_env_int("PRINTER_PNG_CACHE_TTL_S", 7 * 24 * 3600),
            json_log_max_jobs=_env_int("PRINTER_JSON_LOG_MAX_JOBS", 10_000),
            json_log_max_bytes=_env_int("PRINTER_JSON_LOG_MAX_BYTES", 100 * 1024 * 1024),
            retry_interval_s=_env_int("PRINTER_RETRY_INTERVAL_S", 300),
            max_retry_age_s=_env_int("PRINTER_MAX_RETRY_AGE_S", 24 * 3600),
        )
