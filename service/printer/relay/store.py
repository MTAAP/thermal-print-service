from __future__ import annotations

import contextlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any


def _atomic_write(path: Path, data: bytes) -> None:
    # Temp file in the same dir + fsync + os.replace so a crash never leaves a
    # torn file. Same durability discipline the joblog write earns the local
    # 202 (spec 7.3): relay state must survive a power cut on a Pi Zero.
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


class CredsStore:
    """Hub credentials: printer_id, handle, hub_url, device_token, api_token."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> dict[str, Any] | None:
        if not self._path.exists():
            return None
        return json.loads(self._path.read_text())

    def save(self, creds: dict[str, Any]) -> None:
        _atomic_write(self._path, json.dumps(creds, sort_keys=True).encode())

    def clear(self) -> None:
        if self._path.exists():
            self._path.unlink()


class AllowList:
    """The Pi's local auto-print allow-list. Mutated ONLY by local actions
    (spec 5): hub join, friends accept, or a sync that matches a local invite.
    Sync may remove + refresh metadata but never silently auto-add."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._data: dict[str, dict[str, Any]] = {}
        if path.exists():
            self._data = json.loads(path.read_text())

    def _flush(self) -> None:
        _atomic_write(self._path, json.dumps(self._data, sort_keys=True).encode())

    def contains(self, handle: str) -> bool:
        return handle in self._data

    def handles(self) -> list[str]:
        return sorted(self._data)

    def metadata(self, handle: str) -> dict[str, Any]:
        return self._data[handle]

    def add(self, handle: str, *, display_name: str | None, renderer_version: str | None) -> None:
        self._data[handle] = {
            "display_name": display_name,
            "renderer_version": renderer_version,
        }
        self._flush()

    def remove(self, handle: str) -> None:
        if handle in self._data:
            del self._data[handle]
            self._flush()


class InviteStore:
    """Stable invite_ids this Pi issued via `hub invite new`. The locally-pinned
    intent the inviter-side allow-list add must match: a hub-reported friend's
    `via_invite_id` is matched against these (spec 5). We store the hub's
    `invite_id`, NOT the plaintext code (the code is only shown to the user to
    share out-of-band)."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._invite_ids: set[str] = set()
        if path.exists():
            self._invite_ids = set(json.loads(path.read_text()))

    def record(self, invite_id: str) -> None:
        self._invite_ids.add(invite_id)
        _atomic_write(self._path, json.dumps(sorted(self._invite_ids)).encode())

    def has(self, invite_id: str) -> bool:
        return invite_id in self._invite_ids


class JobMap:
    """Durable hub_job_id -> {local_job_id, last_status}. Append-only JSONL so
    each update is a single fsynced append; replay takes the last line per id.
    This is the crash-safety spine: persisted+fsynced BEFORE the delivered ACK
    (spec 7.3), and replayed on startup to finish status reporting."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._state: dict[str, dict[str, str]] = {}
        if path.exists():
            for line in path.read_text().splitlines():
                line = line.strip()
                if not line:
                    continue
                # Tolerate a torn or malformed line instead of refusing to start:
                # crashing here would strand EVERY delivered job -- a far worse
                # failure than dropping one record. A power cut can leave a
                # partially-written trailing append. If the torn line is an UPDATE
                # to a job that has an earlier good line, the job reverts to that
                # earlier (still-unfinished) status and replay re-reports it --
                # safe. If the torn line is a job's SOLE record (a crash during the
                # put-before-ack in _on_accepted), that job is forgotten here; a
                # later hub redelivery is then deduped by the local /print
                # idempotency layer, and only double-prints if the outage outlived
                # that layer's TTL -- the same bounded crash window as the
                # submit/persist gap. Mirrors the main joblog's bad-line tolerance.
                try:
                    rec = json.loads(line)
                    self._state[rec["hub_job_id"]] = {
                        "local_job_id": rec["local_job_id"],
                        "last_status": rec["last_status"],
                    }
                except (ValueError, KeyError, TypeError):
                    continue

    def put(self, hub_job_id: str, *, local_job_id: str, last_status: str) -> None:
        rec = {
            "hub_job_id": hub_job_id,
            "local_job_id": local_job_id,
            "last_status": last_status,
        }
        line = (json.dumps(rec, sort_keys=True) + "\n").encode()
        # Append + fsync. We do NOT rewrite the whole file: a single appended,
        # fsynced line is the atomic durable unit (no torn rewrite window).
        with open(self._path, "ab") as f:
            f.write(line)
            f.flush()
            os.fsync(f.fileno())
        self._state[hub_job_id] = {
            "local_job_id": local_job_id,
            "last_status": last_status,
        }

    def get(self, hub_job_id: str) -> dict[str, str] | None:
        return self._state.get(hub_job_id)

    def unfinished(self, *, terminal: set[str]) -> dict[str, dict[str, str]]:
        return {
            k: v for k, v in self._state.items() if v["last_status"] not in terminal
        }
