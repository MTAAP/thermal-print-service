from __future__ import annotations

from pathlib import Path


class StatePaths:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.jobs = root / "jobs"           # JSONL log + per-job json + per-job png
        self.cache = root / "cache"         # PNG cache (LRU)
        self.idempotency = root / "idempotency"  # idempotency index

    def ensure(self) -> None:
        for p in (self.jobs, self.cache, self.idempotency):
            p.mkdir(parents=True, exist_ok=True)

    def job_json_path(self, job_id: str) -> Path:
        return self.jobs / f"{job_id}.json"

    def job_png_path(self, job_id: str) -> Path:
        return self.jobs / f"{job_id}.png"

    @property
    def joblog_path(self) -> Path:
        return self.jobs / "log.jsonl"

    @property
    def idempotency_path(self) -> Path:
        return self.idempotency / "index.jsonl"
