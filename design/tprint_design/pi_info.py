"""Effective max_length_mm resolution for the lint engine.

Resolution order:
  1. Explicit --max-length-mm flag passed by the user.
  2. Cached value from the last successful `tprint-design info` call,
     if the cache is < 24 h old.
  3. Bundled default of 2000 mm (matches the Pi's MAX_LENGTH_MM_DEFAULT).
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from printer_core.constants import MAX_LENGTH_MM_DEFAULT

_CACHE_TTL_S = 24 * 3600


def default_cache_dir() -> Path:
    base = Path(os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache")))
    return base / "tprint-design"


def effective_max_length_mm(
    *,
    flag_value: int | None,
    cache_dir: Path | None = None,
) -> int:
    if flag_value is not None:
        return flag_value
    cache_dir = cache_dir or default_cache_dir()
    payload = _read_cache(cache_dir)
    if payload is not None and "max_length_mm_default" in payload:
        return int(payload["max_length_mm_default"])
    return MAX_LENGTH_MM_DEFAULT


def refresh_cache(*, cache_dir: Path, payload: dict) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    payload = dict(payload)
    payload["ts"] = int(time.time())
    (cache_dir / "pi-info.json").write_text(json.dumps(payload))


def _read_cache(cache_dir: Path) -> dict | None:
    f = cache_dir / "pi-info.json"
    if not f.exists():
        return None
    try:
        data = json.loads(f.read_text())
    except (OSError, ValueError):
        return None
    ts = int(data.get("ts", 0))
    if time.time() - ts > _CACHE_TTL_S:
        return None
    return data
