from __future__ import annotations

from datetime import UTC, datetime

import pytest_asyncio
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

from hub.config import HubConfig
from hub.db import init_models, make_engine, make_sessionmaker
from hub.jobs.wakeup import WakeupRegistry
from hub.routes import AppDeps


@pytest_asyncio.fixture
async def sm():
    # In-memory SQLite, shared across the connection pool for one test.
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    await init_models(engine)
    maker = make_sessionmaker(engine)
    yield maker
    await engine.dispose()


def now() -> datetime:
    return datetime.now(UTC)


@pytest_asyncio.fixture
async def app_client(sm):
    from hub.app import create_app
    deps = AppDeps(config=HubConfig.from_env({}), sessionmaker=sm,
                   wake=WakeupRegistry(), online=set())
    app = create_app(deps, run_sweeper=False)  # no background sweeper in tests
    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://hub") as c:
            yield c, deps
