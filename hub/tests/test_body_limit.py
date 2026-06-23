"""Body-size cap middleware: oversized requests are refused with 413 before
routing, and legitimate (within-cap) requests still pass."""

from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

from hub.app import create_app
from hub.config import HubConfig
from hub.jobs.wakeup import WakeupRegistry
from hub.presence import Presence
from hub.routes import AppDeps


async def _client(sm, max_body: str):
    cfg = HubConfig.from_env(
        {"HUB_SESSION_HTTPS_ONLY": "false", "HUB_MAX_REQUEST_BODY_BYTES": max_body}
    )
    deps = AppDeps(config=cfg, sessionmaker=sm, wake=WakeupRegistry(), online=Presence())
    app = create_app(deps, run_sweeper=False)
    return app, deps


async def test_oversized_content_length_returns_413_before_auth(sm):
    # A declared Content-Length over the cap is refused with 413 -- and BEFORE
    # auth, so the body is never buffered (the auth header here is bogus).
    app, _deps = await _client(sm, max_body="500")
    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://hub") as c:
            r = await c.post(
                "/send",
                headers={"Authorization": "Bearer nope"},
                json={"to": ["a"], "raw_png_b64": "x" * 2000},
            )
            assert r.status_code == 413


async def test_within_cap_body_passes_the_middleware(sm):
    # A request under the cap is NOT 413: it reaches routing and gets the normal
    # auth rejection (401) for a missing bearer, proving the middleware passed it.
    app, _deps = await _client(sm, max_body=str(1024 * 1024))
    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://hub") as c:
            r = await c.post("/send", json={"to": ["a"], "document": {"blocks": []}})
            assert r.status_code != 413
            # No Authorization header at all -> 401 from the bearer() guard.
            assert r.status_code == 401
