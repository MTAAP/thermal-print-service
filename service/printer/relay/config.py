from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

_DEFAULT_MAX_RAW_BYTES = 8 * 1024 * 1024
_DEFAULT_MAX_RAW_HEIGHT_PX = 16_000
_DEFAULT_MAX_DECODED_IMAGE_PIXELS = 10_000_000


def _base64_chars_for_bytes(n: int) -> int:
    return ((n + 2) // 3) * 4


@dataclass(frozen=True)
class RelayConfig:
    # The default deliberately fails DNS so a misconfigured Pi is loud, not
    # silently pointed at the wrong host (spec 9.5, mirrors the MCP convention).
    hub_url: str = "https://hub.invalid"
    relay_state_dir: Path = Path("/var/lib/printer/relay")
    local_service_url: str = "http://127.0.0.1:8000"
    long_poll_wait_s: float = 25.0
    # Per-friend ceiling. 12/hour is generous for a 1-20 jobs/day appliance and
    # blunts a compromised-friend flood (spec 7.1).
    per_friend_rate_per_hour: int = 12
    reconnect_backoff_base_s: float = 1.0
    reconnect_backoff_max_s: float = 30.0
    # How long to wait on the local /jobs/{id} reaching a terminal state before
    # giving up the in-loop poll (startup replay catches anything still pending).
    local_terminal_timeout_s: float = 120.0
    # Raw relay caps mirror the local service defaults. The relay enforces them
    # before posting to /print/raw so hostile hub payloads cannot force expensive
    # decode/load work or bypass local request-size limits through JSON base64.
    max_raw_payload_bytes: int = _DEFAULT_MAX_RAW_BYTES
    max_raw_base64_chars: int = _base64_chars_for_bytes(_DEFAULT_MAX_RAW_BYTES)
    max_raw_height_px: int = _DEFAULT_MAX_RAW_HEIGHT_PX
    max_decoded_image_pixels: int = _DEFAULT_MAX_DECODED_IMAGE_PIXELS

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> RelayConfig:
        e = env if env is not None else os.environ
        host = e.get("PRINTER_HOST", "127.0.0.1")
        port = e.get("PRINTER_PORT", "8000")
        local_url = e.get("PRINTER_RELAY_LOCAL_URL", f"http://{host}:{port}")
        max_raw_payload_bytes = int(
            e.get("PRINTER_RELAY_MAX_RAW_BYTES",
                  e.get("PRINTER_MAX_REQUEST_BYTES", cls.max_raw_payload_bytes))
        )
        return cls(
            hub_url=e.get("HUB_URL", cls.hub_url),
            relay_state_dir=Path(e.get("PRINTER_RELAY_STATE_DIR", str(cls.relay_state_dir))),
            local_service_url=local_url,
            long_poll_wait_s=float(e.get("PRINTER_RELAY_LONG_POLL_WAIT_S", cls.long_poll_wait_s)),
            per_friend_rate_per_hour=int(
                e.get("PRINTER_RELAY_RATE_PER_HOUR", cls.per_friend_rate_per_hour)
            ),
            reconnect_backoff_base_s=float(
                e.get("PRINTER_RELAY_BACKOFF_BASE_S", cls.reconnect_backoff_base_s)
            ),
            reconnect_backoff_max_s=float(
                e.get("PRINTER_RELAY_BACKOFF_MAX_S", cls.reconnect_backoff_max_s)
            ),
            local_terminal_timeout_s=float(
                e.get("PRINTER_RELAY_LOCAL_TERMINAL_TIMEOUT_S", cls.local_terminal_timeout_s)
            ),
            max_raw_payload_bytes=max_raw_payload_bytes,
            max_raw_base64_chars=int(
                e.get(
                    "PRINTER_RELAY_MAX_RAW_BASE64_CHARS",
                    _base64_chars_for_bytes(max_raw_payload_bytes),
                )
            ),
            max_raw_height_px=int(
                e.get("PRINTER_RELAY_MAX_RAW_HEIGHT_PX",
                      e.get("PRINTER_MAX_RAW_HEIGHT_PX", cls.max_raw_height_px))
            ),
            max_decoded_image_pixels=int(
                e.get(
                    "PRINTER_RELAY_MAX_DECODED_IMAGE_PIXELS",
                    e.get("PRINTER_MAX_DECODED_IMAGE_PIXELS",
                          cls.max_decoded_image_pixels),
                )
            ),
        )
