import asyncio

from printer.relay.config import RelayConfig
from printer.relay.hub_client import HubClient
from printer.relay.local_client import LocalClient
from printer.relay.loop import RelayClient


def _cfg(relay_paths):
    return RelayConfig.from_env({
        "HUB_URL": "http://hub.test",
        "PRINTER_RELAY_STATE_DIR": str(relay_paths.root),
        "PRINTER_RELAY_BACKOFF_BASE_S": "0.01",
        "PRINTER_RELAY_BACKOFF_MAX_S": "0.05",
    })


async def test_capability_reported_once_per_version(relay_paths, mock_hub, hub_http, fake_deps):
    from tests.conftest import lifespan_client

    async with lifespan_client(fake_deps) as local_ac:
        client = RelayClient(
            _cfg(relay_paths), relay_paths,
            hub=HubClient(hub_http, device_token="dev-token", api_token="api-token"),
            local=LocalClient(local_ac),
        )
        await client.report_capabilities_if_changed()
        await client.report_capabilities_if_changed()  # same version -> no re-report
    assert len(mock_hub.capabilities) == 1
    # The reported schema is the local /schema's full blocks + renderer_version.
    assert "renderer_version" in mock_hub.capabilities[0]
    assert "blocks_schema" in mock_hub.capabilities[0]


async def test_poll_once_recovers_after_503(relay_paths, mock_hub, hub_http, fake_deps):
    from tests.conftest import lifespan_client

    mock_hub.fail_inbox_times = 2  # first two /inbox calls 503, then recover
    async with lifespan_client(fake_deps) as local_ac:
        client = RelayClient(
            _cfg(relay_paths), relay_paths,
            hub=HubClient(hub_http, device_token="dev-token", api_token="api-token"),
            local=LocalClient(local_ac),
        )

        # Drive the reconnect logic directly: two failures then an empty success.
        backoff = client._cfg.reconnect_backoff_base_s
        successes = 0
        for _ in range(5):
            try:
                await client._poll_once()
                successes += 1
                if successes >= 1:
                    break
            except Exception:
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, client._cfg.reconnect_backoff_max_s)
    assert mock_hub.fail_inbox_times == 0  # both failures consumed
    assert successes == 1
