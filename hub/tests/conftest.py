from __future__ import annotations

from datetime import UTC, datetime

import pytest_asyncio

from hub.db import init_models, make_engine, make_sessionmaker


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
