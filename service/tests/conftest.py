from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

from printer.app import AppDeps, create_app
from printer.config import ServiceConfig
from printer.health import HealthCollector
from printer.paths import StatePaths
from printer.queue.cache import PngCache
from printer.queue.idempotency import IdempotencyCache
from printer.queue.joblog import JobLog
from printer.queue.worker import PrintWorker, WorkerDeps, make_options_lookup
from printer.render.typography import FontRegistry
from printer.transport.status import StatusReader

# conftest.py lives at ``service/tests/conftest.py``; ``parents[2]`` is the
# repo root. Render tests need the bundled assets/fonts/ directory and use
# this path through the ``font_dir`` / ``fonts`` fixtures so the suite stays
# portable across machines.
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FONT_DIR = REPO_ROOT / "assets" / "fonts"


@pytest.fixture
def font_dir() -> Path:
    return DEFAULT_FONT_DIR


@pytest.fixture
def fonts(font_dir: Path) -> FontRegistry:
    return FontRegistry(font_dir)


@pytest.fixture
def state_dir(tmp_path):
    """Mirror the runtime StateDirectory layout under a tmp path."""
    for sub in ("jobs", "cache", "idempotency"):
        (tmp_path / sub).mkdir()
    return tmp_path


class FakeAsyncTransport:
    def __init__(self) -> None:
        self.printed: list[bytes] = []

    async def print_png(self, png, *, auto_cut, feed_lines_after) -> int:
        self.printed.append(png)
        return 50  # paper_used_mm


@pytest.fixture
def fake_deps(state_dir):
    paths = StatePaths(state_dir)
    paths.ensure()
    cfg = ServiceConfig(
        host="127.0.0.1", port=8000, state_dir=state_dir,
        device="/dev/null",
        font_dir=DEFAULT_FONT_DIR,
    )
    log = JobLog(paths.joblog_path)
    idem = IdempotencyCache(paths.idempotency_path, ttl_s=cfg.idempotency_ttl_s)
    cache = PngCache(paths.cache, max_bytes=cfg.png_cache_max_bytes,
                     ttl_s=cfg.png_cache_ttl_s)
    transport = FakeAsyncTransport()
    health = HealthCollector(
        status_reader=StatusReader(supports_status=False),
        queue_depth=lambda: 0,
        last_print_at=lambda: None,
        process_started_at=0.0,
        clock_now=lambda: 0.0,
    )
    options_store: dict[str, tuple[bool, int, str | None, bool]] = {}
    worker = PrintWorker(
        WorkerDeps(joblog=log, png_cache=cache, transport=transport,
                   retry_interval_s=0.01, max_retry_age_s=60),
        options_lookup=make_options_lookup(options_store),
    )

    return AppDeps(
        config=cfg, paths=paths, joblog=log, idem=idem, png_cache=cache,
        worker=worker, transport=transport, health=health,
        options_store=options_store,
    )


@asynccontextmanager
async def lifespan_client(deps: AppDeps):
    """Async client that drives FastAPI's lifespan, so the worker is started
    and stopped around the test. ``httpx.ASGITransport`` alone does not
    invoke lifespan; tests that need the worker to drain (e.g. asserting
    paper_mm_total increments after a print) must use this.
    """
    app = create_app(deps)
    async with (
        LifespanManager(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac,
    ):
        yield ac
