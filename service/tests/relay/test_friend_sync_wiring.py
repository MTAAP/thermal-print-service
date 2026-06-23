"""Fix B regression: sync_friends must be WIRED into the runtime poll path.

The shipped bug was that sync_friends() had no runtime caller -- only a unit
test invoked it directly -- so the inviter side of the §5 friendship never ran.
These tests deliberately do NOT call sync_friends directly: they drive the
loop's per-cycle path (_poll_once / sync_friends_once) and assert the AllowList
changes through the wiring, which is the exact blind spot that let the bug ship.
"""
from printer.relay.config import RelayConfig
from printer.relay.hub_client import HubClient
from printer.relay.local_client import LocalClient
from printer.relay.loop import RelayClient
from printer.relay.store import AllowList, InviteStore


def _cfg(relay_paths):
    return RelayConfig.from_env({
        "HUB_URL": "http://hub.test",
        "PRINTER_RELAY_STATE_DIR": str(relay_paths.root),
        # Empty inbox returns immediately, but keep the wait tiny so a hub
        # behaviour change never makes the test hang on the long poll.
        "PRINTER_RELAY_LONG_POLL_WAIT_S": "0.1",
    })


def _client(cfg, relay_paths, hub_http, local_ac):
    return RelayClient(
        cfg, relay_paths,
        hub=HubClient(hub_http, device_token="dev-token", api_token="api-token"),
        local=LocalClient(local_ac),
    )


async def test_poll_cycle_auto_adds_friend_matching_local_invite(
    relay_paths, mock_hub, hub_http, fake_deps,
):
    from tests.conftest import lifespan_client

    # Inviter recorded the invite id it issued via `hub invite new`.
    InviteStore(relay_paths.invites_path).record("inv_mine")
    # The hub reports a friend who joined through that invite.
    mock_hub.friends = [{
        "handle": "bob", "display_name": "Bob", "renderer_version": "1.0.0",
        "online": True, "via_invite_id": "inv_mine",
    }]
    assert AllowList(relay_paths.allowlist_path).contains("bob") is False

    async with lifespan_client(fake_deps) as local_ac:
        client = _client(_cfg(relay_paths), relay_paths, hub_http, local_ac)
        # Drive ONE poll cycle: maintenance (replay + caps + friend sync) runs
        # before the empty-inbox long poll returns. No direct sync_friends call.
        await client._poll_once()

    # The friend was auto-added through the wired path, so future prints back
    # from bob pass Gate 1 instead of being rejected_not_allowlisted forever.
    assert mock_hub.friends_fetched == 1
    assert AllowList(relay_paths.allowlist_path).contains("bob") is True


async def test_friend_sync_failure_does_not_raise_or_empty_allowlist(
    relay_paths, mock_hub, hub_http, fake_deps,
):
    from tests.conftest import lifespan_client

    # A pre-existing auto-print friend must survive a transient GET /friends 503:
    # passing [] from a swallowed error into sync_friends would prune it away.
    AllowList(relay_paths.allowlist_path).add(
        "alice", display_name="Alice", renderer_version="1.0.0"
    )
    mock_hub.fail_friends_times = 1  # the next GET /friends 503s

    async with lifespan_client(fake_deps) as local_ac:
        client = _client(_cfg(relay_paths), relay_paths, hub_http, local_ac)
        # Must not raise out of the per-cycle sync despite the hub error.
        await client.sync_friends_once()

    # sync_friends was never called (no successful fetch), so the allow-list is
    # untouched -- the existing friend is NOT pruned toward empty.
    assert mock_hub.friends_fetched == 0
    assert AllowList(relay_paths.allowlist_path).contains("alice") is True
