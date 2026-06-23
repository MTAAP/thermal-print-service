from __future__ import annotations

from datetime import UTC, datetime

import pytest_asyncio
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

from hub.config import HubConfig
from hub.db import init_models, make_engine, make_sessionmaker
from hub.jobs.wakeup import WakeupRegistry
from hub.presence import Presence
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
    # Tests drive the app over http:// via ASGITransport, so the Secure cookie
    # flag must be off or the cookie jar would drop the console session cookie.
    deps = AppDeps(config=HubConfig.from_env({"HUB_SESSION_HTTPS_ONLY": "false"}),
                   sessionmaker=sm, wake=WakeupRegistry(), online=Presence())
    app = create_app(deps, run_sweeper=False)  # no background sweeper in tests
    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://hub") as c:
            yield c, deps


@pytest_asyncio.fixture
async def web_client(app_client):
    """A web client already carrying a valid CONSOLE session cookie for 'alice',
    plus the deps and alice's registration. Built by minting a login link and
    walking the real /console/login route so the cookie is set exactly as prod."""
    client, deps = app_client
    from hub.invites import create_invite, redeem_invite
    from hub.login import create_login_link

    async with deps.sessionmaker() as s:
        alice = await redeem_invite(
            s, code=await create_invite(s, issuer_printer_id=None, ttl_s=3600),
            handle="alice", display_name="Alice")
        link = await create_login_link(s, handle="alice", ttl_s=600)

    # Walk the real login route: it consumes the link, sets the signed cookie,
    # and redirects to Friends. follow_redirects=False so we can assert the 303.
    resp = await client.get(f"/console/login?lt={link}", follow_redirects=False)
    assert resp.status_code == 303
    # httpx's AsyncClient persists the Set-Cookie across subsequent requests.
    yield client, deps, alice
