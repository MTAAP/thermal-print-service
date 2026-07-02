from pathlib import Path

from printer.app import create_app
from printer.schema.blocks import block_type_names

SPEC_PATH = Path(__file__).resolve().parents[2] / "thermal-print-service-spec.md"


def _spec_text() -> str:
    return SPEC_PATH.read_text()


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


def test_service_route_paths_are_documented_in_spec(fake_deps):
    app = create_app(fake_deps)
    spec = _spec_text()
    missing = sorted(
        path for path in _route_paths(app.routes)
        if path not in spec
    )
    assert missing == []


def test_block_type_literals_are_documented_in_spec():
    spec = _spec_text()
    missing = sorted(
        block_type for block_type in block_type_names()
        if block_type not in spec
    )
    assert missing == []
