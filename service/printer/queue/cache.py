from __future__ import annotations

import contextlib
import os
import re
import time
from collections import OrderedDict
from pathlib import Path

# ``<job>__<index>.png`` is the canonical layout. The legacy single-PNG
# layout (``<job>.png`` from before v0.6.0) is read transparently by
# ``get_chunks`` so PNGs cached prior to upgrade still drain.
_CHUNK_RE = re.compile(r"^(?P<jid>[^_]+)__(?P<idx>\d+)$")


class PngCache:
    """LRU cache of rendered PNG chunks on disk.

    On-disk layout: ``<root>/<job_id>__<chunk_index>.png``. A job has 1+
    chunks; the chunk index runs ``0..N-1``. The LRU is keyed by job id;
    eviction removes all chunks for the evicted job atomically.

    mtime is the cache timestamp, enabling atime-free TTL on tmpfs-style
    mounts. A job's effective mtime is the most recent chunk write.

    Legacy fallback: if a job has only a non-chunked ``<job>.png`` file
    (cached before v0.6.0), ``get_chunks`` returns it as a single-chunk
    list. New writes always use the chunked layout.
    """

    def __init__(self, root: Path, *, max_bytes: int, ttl_s: int) -> None:
        self._root = root
        self._max_bytes = max_bytes
        self._ttl_s = ttl_s
        self._lru: OrderedDict[str, int] = OrderedDict()  # job_id -> total bytes
        root.mkdir(parents=True, exist_ok=True)
        self._scan()

    def _chunk_path(self, job_id: str, index: int) -> Path:
        return self._root / f"{job_id}__{index}.png"

    def _legacy_path(self, job_id: str) -> Path:
        return self._root / f"{job_id}.png"

    def _job_paths(self, job_id: str) -> list[Path]:
        """All on-disk PNGs for ``job_id``, ordered by chunk index, with
        the legacy single-file path as the trailing fallback."""
        chunks = sorted(
            self._root.glob(f"{job_id}__*.png"),
            key=lambda p: int(p.stem.split("__")[1]),
        )
        if chunks:
            return chunks
        legacy = self._legacy_path(job_id)
        return [legacy] if legacy.exists() else []

    def _scan(self) -> None:
        # Group PNG files by job id; the LRU stores total bytes per job.
        by_job: dict[str, tuple[int, float]] = {}  # jid -> (total_bytes, max_mtime)
        for f in self._root.glob("*.png"):
            stem = f.stem
            m = _CHUNK_RE.match(stem)
            jid = m.group("jid") if m else stem
            st = f.stat()
            cur_b, cur_m = by_job.get(jid, (0, 0.0))
            by_job[jid] = (cur_b + st.st_size, max(cur_m, st.st_mtime))
        # Sort by max-mtime ascending so least-recent jobs sit at the front
        # of the OrderedDict (eviction pops from the front).
        for jid, (total, _mtime) in sorted(by_job.items(), key=lambda kv: kv[1][1]):
            self._lru[jid] = total

    def _evict_to_cap(self) -> None:
        total = sum(self._lru.values())
        while total > self._max_bytes and self._lru:
            jid, sz = self._lru.popitem(last=False)
            for p in self._job_paths(jid):
                with contextlib.suppress(FileNotFoundError):
                    p.unlink()
            total -= sz

    def put_chunks(self, job_id: str, chunks: list[bytes]) -> None:
        """Write all chunks for a job. Replaces any existing chunks for this
        job id (including the legacy single-PNG layout). N=0 chunks is a
        no-op — the worker handles a missing-PNG dequeue as
        ``unknown_partial``, but accepting a job with zero chunks at the HTTP
        layer is a caller error.
        """
        # Remove any prior on-disk state for this id (chunked or legacy)
        # so a re-cache doesn't leave orphaned chunks if N shrank.
        for p in self._job_paths(job_id):
            with contextlib.suppress(FileNotFoundError):
                p.unlink()
        total = 0
        for i, png_bytes in enumerate(chunks):
            path = self._chunk_path(job_id, i)
            with open(path, "wb") as f:
                f.write(png_bytes)
                f.flush()
                os.fsync(f.fileno())
            total += len(png_bytes)
        if total > 0:
            self._lru[job_id] = total
            self._lru.move_to_end(job_id, last=True)
            self._evict_to_cap()

    def get_chunks(self, job_id: str) -> list[bytes] | None:
        """Return the list of PNG chunks for a job, or ``None`` if any
        chunk is missing or the job has aged past the TTL. The TTL is
        evaluated against the *most recent* chunk's mtime so partially
        re-touched jobs aren't half-expired.
        """
        paths = self._job_paths(job_id)
        if not paths:
            self._lru.pop(job_id, None)
            return None
        max_mtime = max(p.stat().st_mtime for p in paths)
        if (time.time() - max_mtime) > self._ttl_s:
            for p in paths:
                with contextlib.suppress(FileNotFoundError):
                    p.unlink()
            self._lru.pop(job_id, None)
            return None
        self._lru.move_to_end(job_id, last=True)
        return [p.read_bytes() for p in paths]

    def delete(self, job_id: str) -> None:
        for p in self._job_paths(job_id):
            with contextlib.suppress(FileNotFoundError):
                p.unlink()
        self._lru.pop(job_id, None)
