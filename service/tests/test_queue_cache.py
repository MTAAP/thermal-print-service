import io
import time

from PIL import Image

from printer.queue.cache import PngCache


def _png_bytes(w: int = 576, h: int = 100) -> bytes:
    buf = io.BytesIO()
    Image.new("1", (w, h), 1).save(buf, format="PNG")
    return buf.getvalue()


def test_put_and_get_chunks_roundtrip(state_dir):
    c = PngCache(state_dir, max_bytes=10 * 1024 * 1024, ttl_s=3600)
    data = _png_bytes()
    c.put_chunks("job-A", [data])
    got = c.get_chunks("job-A")
    assert got == [data]


def test_multi_chunk_roundtrip_preserves_order(state_dir):
    c = PngCache(state_dir, max_bytes=10 * 1024 * 1024, ttl_s=3600)
    a = _png_bytes(h=10)
    b = _png_bytes(h=20)
    c_chunk = _png_bytes(h=30)
    c.put_chunks("multi", [a, b, c_chunk])
    got = c.get_chunks("multi")
    assert got == [a, b, c_chunk]


def test_lru_evicts_when_over_cap(state_dir):
    big = b"\x00" * 5_000_000  # 5 MB filler
    c = PngCache(state_dir, max_bytes=10_000_000, ttl_s=3600)
    c.put_chunks("a", [big])
    c.put_chunks("b", [big])
    c.put_chunks("c", [big])  # forces eviction of "a"
    assert c.get_chunks("a") is None
    assert c.get_chunks("b") is not None
    assert c.get_chunks("c") is not None


def test_ttl_evicts_stale(state_dir):
    c = PngCache(state_dir, max_bytes=10_000_000, ttl_s=0)
    c.put_chunks("a", [_png_bytes()])
    time.sleep(0.05)
    assert c.get_chunks("a") is None


def test_legacy_single_png_still_drains(state_dir):
    """v0.5.x cached jobs as ``<job>.png``. v0.6.0 added the ``__N`` suffix
    for multi-chunk support; the read path must still find the single-PNG
    layout so jobs cached pre-upgrade keep printing after the service
    restarts."""
    legacy_path = state_dir / "legacy-job.png"
    data = _png_bytes(h=42)
    legacy_path.write_bytes(data)
    c = PngCache(state_dir, max_bytes=10_000_000, ttl_s=3600)
    got = c.get_chunks("legacy-job")
    assert got == [data]


def test_replacing_job_drops_orphan_chunks(state_dir):
    """If a job is re-cached with fewer chunks than before, the old extra
    chunks must be removed so they don't reappear in the next ``get_chunks``."""
    c = PngCache(state_dir, max_bytes=10_000_000, ttl_s=3600)
    c.put_chunks("j", [b"A", b"B", b"C"])
    assert c.get_chunks("j") == [b"A", b"B", b"C"]
    c.put_chunks("j", [b"X"])
    assert c.get_chunks("j") == [b"X"]


def test_delete_removes_all_chunks(state_dir):
    c = PngCache(state_dir, max_bytes=10_000_000, ttl_s=3600)
    c.put_chunks("j", [b"a", b"b"])
    c.delete("j")
    assert c.get_chunks("j") is None
    # No orphan files
    assert list(state_dir.glob("j*.png")) == []
