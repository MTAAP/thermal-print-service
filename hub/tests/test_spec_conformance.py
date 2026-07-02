from pathlib import Path

from hub.app import create_app
from hub.config import HubConfig
from hub.db import make_engine, make_sessionmaker
from hub.jobs.wakeup import WakeupRegistry
from hub.presence import Presence
from hub.routes import AppDeps

SPEC_PATH = Path(__file__).resolve().parents[2] / "thermal-print-service-spec.md"

# FastAPI-generated documentation endpoints, not part of the hub/relay contract.
_EXEMPT_ROUTE_PATHS = {
    "/docs",
    "/docs/oauth2-redirect",
    "/openapi.json",
    "/redoc",
}


def _route_paths(routes) -> set[str]:
    paths: set[str] = set()
    for route in routes:
        path = getattr(route, "path", None)
        if isinstance(path, str):
            paths.add(path)
        paths.update(_route_paths(getattr(route, "routes", ())))
        router = getattr(route, "original_router", None)
        paths.update(_route_paths(getattr(router, "routes", ())))
    return paths


def test_hub_route_paths_are_documented_in_spec():
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    deps = AppDeps(
        config=HubConfig.from_env({"HUB_SESSION_HTTPS_ONLY": "false"}),
        sessionmaker=make_sessionmaker(engine),
        wake=WakeupRegistry(),
        online=Presence(),
    )
    app = create_app(deps, run_sweeper=False)
    spec = SPEC_PATH.read_text()

    missing = sorted(
        path for path in _route_paths(app.routes)
        if path not in spec and path not in _EXEMPT_ROUTE_PATHS
    )
    assert missing == []
