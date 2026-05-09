from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path


class IdempotencyConflict(Exception):
    """Same scope+key reused with a different payload hash within TTL."""


@dataclass(frozen=True)
class IdempotencyHit:
    job_id: str
    queued_at: str


def _scope_key(scope: str | None) -> str:
    return scope if scope is not None else "anonymous"


class IdempotencyCache:
    """In-memory map persisted as JSONL for crash safety, with 24 h default TTL."""

    def __init__(self, path: Path, *, ttl_s: int) -> None:
        self._path = path
        self._ttl = ttl_s
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.touch(exist_ok=True)
        self._mem: dict[tuple[str, str], tuple[str, str, str, float]] = {}
        # key: (scope, key) -> (payload_hash, job_id, queued_at, recorded_at_unix)
        self._load()

    def _load(self) -> None:
        with open(self._path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    o = json.loads(line)
                    self._mem[(o["scope"], o["key"])] = (
                        o["payload_hash"], o["job_id"], o["queued_at"], o["recorded_at"]
                    )
                except (json.JSONDecodeError, KeyError):
                    continue

    def _is_fresh(self, recorded_at_unix: float) -> bool:
        return (time.time() - recorded_at_unix) < self._ttl

    def lookup(self, *, scope: str | None, key: str, payload_hash: str) -> IdempotencyHit | None:
        ent = self._mem.get((_scope_key(scope), key))
        if ent is None:
            return None
        prev_hash, job_id, queued_at, recorded_at = ent
        if not self._is_fresh(recorded_at):
            return None
        if prev_hash != payload_hash:
            raise IdempotencyConflict(
                f"scope={scope!r} key={key!r} reused with different payload hash"
            )
        return IdempotencyHit(job_id=job_id, queued_at=queued_at)

    def record(self, *, scope: str | None, key: str, payload_hash: str,
               job_id: str, queued_at: str) -> None:
        sk = _scope_key(scope)
        recorded_at = time.time()
        self._mem[(sk, key)] = (payload_hash, job_id, queued_at, recorded_at)
        line = json.dumps({
            "scope": sk, "key": key, "payload_hash": payload_hash,
            "job_id": job_id, "queued_at": queued_at, "recorded_at": recorded_at,
        })
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
            f.flush()
            os.fsync(f.fileno())
