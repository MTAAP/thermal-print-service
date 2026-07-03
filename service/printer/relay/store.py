from __future__ import annotations

import contextlib
import fcntl
import json
import logging
import os
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

logger = logging.getLogger("printer.relay")


def _atomic_write(path: Path, data: bytes) -> None:
    # Temp file in the same dir + fsync + os.replace so a crash never leaves a
    # torn file. Same durability discipline the joblog write earns the local
    # 202 (spec §16.3): relay state must survive a power cut on a Pi Zero.
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


@contextlib.contextmanager
def _exclusive_file_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        with contextlib.suppress(OSError):
            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


class CredsStore:
    """Hub credentials: printer_id, handle, hub_url, device_token, api_token."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> dict[str, Any] | None:
        # Read-then-parse with no exists() pre-check: an exists()-then-read_text()
        # races a concurrent `printer-svc hub leave/join` CLI unlinking the file
        # between the two calls. A missing file (OSError) or a torn write
        # (JSONDecodeError, from a power cut mid-save) returns None -- treated as
        # "not joined" rather than crashing run_forever. Without this, the read
        # fault propagates out, asyncio.run exits non-zero, and systemd crash-loops
        # the unit until StartLimitBurst trips and STOPS it -- the relay goes
        # permanently dark with no replay. (JobMap has the same tolerance.)
        try:
            return json.loads(self._path.read_text())  # type: ignore[no-any-return]
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("relay: creds.json unreadable (%s); treating as not joined", exc)
            return None

    def save(self, creds: dict[str, Any]) -> None:
        _atomic_write(self._path, json.dumps(creds, sort_keys=True).encode())

    def clear(self) -> None:
        if self._path.exists():
            self._path.unlink()


class AllowList:
    """The Pi's local auto-print allow-list. Mutated ONLY by local actions
    (spec §16.2): hub join, friends accept, or a sync that matches a local invite.
    Sync may remove + refresh metadata but never silently auto-add."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._data: dict[str, dict[str, Any]] = {}
        if path.exists():
            # Tolerate a torn allowlist.json (power cut mid-write on a Pi Zero):
            # an unguarded json.loads here would raise out of RelayClient.__init__
            # so `printer-svc relay run` never reaches run_forever and systemd
            # crash-loops until hand-repaired. Empty fails safe -- prints are
            # rejected until the allow-list is re-synced from the hub. Mirrors
            # JobMap's bad-line tolerance.
            try:
                self._data = json.loads(path.read_text())
            except (json.JSONDecodeError, OSError, TypeError) as exc:
                logger.warning("relay: allowlist.json unreadable (%s); starting empty", exc)
                self._data = {}

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


class CommandInbox:
    """Durable local command queue from short-lived CLIs to the relay loop.

    Commands are append-only JSONL so the CLI never rewrites relay-owned state:
    the long-lived relay drains this inbox and remains the only allowlist.json
    writer, avoiding stale in-memory clobbers from a second AllowList instance.

    drain() and ack() are a two-phase handoff: drain() hands back ops and keeps
    the snapshot on disk, ack() deletes it. The relay must not call ack() until
    every op has been applied, so a crash between the two leaves the snapshot
    in place for the next drain() to replay.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock_path = path.with_name(f"{path.name}.lock")

    def append(self, op: dict[str, Any]) -> None:
        line = (json.dumps(op, sort_keys=True) + "\n").encode()
        with _exclusive_file_lock(self._lock_path):
            fd = os.open(self._path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
            try:
                written = os.write(fd, line)
                if written != len(line):
                    raise OSError(
                        f"short write to {self._path}: {written} of {len(line)} bytes"
                    )
                os.fsync(fd)
            finally:
                os.close(fd)

    def drain(self) -> list[dict[str, Any]]:
        """Return queued commands without deleting the snapshot.

        The caller must call ack() only after every returned op has been durably
        applied. Deleting the snapshot here (the old behavior) would lose queued
        commands forever if the process crashes after drain() returns but before
        the ops are applied to allowlist.json. If ack() hasn't happened yet
        (e.g. a crash mid-apply), the next drain() re-reads the same pending
        snapshot instead of picking up self._path, so repeated calls are safe:
        applying an "accept" op twice is a no-op overwrite in AllowList.add.
        """
        snapshot = self._path.with_name(f"{self._path.name}.draining")
        with _exclusive_file_lock(self._lock_path):
            if not snapshot.exists():
                try:
                    os.replace(self._path, snapshot)
                except FileNotFoundError:
                    return []
            return self._read_snapshot(snapshot)

    def ack(self) -> None:
        """Delete the drain snapshot after its ops have been applied.

        Must only be called once every op from the matching drain() has been
        durably applied -- see drain()'s docstring for why the deletion is
        split out from the read.
        """
        snapshot = self._path.with_name(f"{self._path.name}.draining")
        with _exclusive_file_lock(self._lock_path), contextlib.suppress(FileNotFoundError):
            snapshot.unlink()

    def _read_snapshot(self, snapshot: Path) -> list[dict[str, Any]]:
        ops: list[dict[str, Any]] = []
        for line in snapshot.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            # A power cut can leave a torn final append. Bad command lines
            # must not stop relay startup: skip the damaged op and replay
            # every complete command, matching JobMap's bad-line tolerance.
            try:
                op = json.loads(line)
                if not isinstance(op, dict):
                    raise TypeError("command line is not a JSON object")
                ops.append(op)
            except (json.JSONDecodeError, TypeError) as exc:
                logger.warning("relay: commands.jsonl unreadable line skipped (%s)", exc)
        return ops


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
            # Tolerate a torn invites.json (power cut mid-write): an unguarded
            # json.loads would crash RelayClient.__init__ and systemd would
            # crash-loop the relay. Empty holds any pending friends un-accepted
            # until the user re-issues an invite -- safe, never auto-adds. Mirrors
            # JobMap's bad-line tolerance.
            try:
                self._invite_ids = set(json.loads(path.read_text()))
            except (json.JSONDecodeError, OSError, TypeError) as exc:
                logger.warning("relay: invites.json unreadable (%s); starting empty", exc)
                self._invite_ids = set()

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
