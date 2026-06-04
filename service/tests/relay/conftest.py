from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from printer.relay.paths import RelayPaths
from tests.relay.mock_hub import MockHub


@pytest.fixture
def relay_paths(tmp_path):
    paths = RelayPaths(tmp_path / "relay")
    paths.ensure()
    return paths


@pytest.fixture
def mock_hub() -> MockHub:
    return MockHub()


@pytest_asyncio.fixture
async def hub_http(mock_hub):
    transport = ASGITransport(app=mock_hub.app())
    async with AsyncClient(transport=transport, base_url="http://hub.test") as c:
        yield c
