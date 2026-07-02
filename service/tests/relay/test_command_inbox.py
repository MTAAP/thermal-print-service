import json
import os
import threading
import time

from printer.relay import store as relay_store
from printer.relay.commands import hub_friends_accept
from printer.relay.config import RelayConfig
from printer.relay.hub_client import HubClient
from printer.relay.local_client import LocalClient
from printer.relay.loop import RelayClient
from printer.relay.store import AllowList, CommandInbox


def _cfg(relay_paths):
    return RelayConfig.from_env({
        "HUB_URL": "http://hub.test",
        "PRINTER_RELAY_STATE_DIR": str(relay_paths.root),
        "PRINTER_RELAY_LONG_POLL_WAIT_S": "0.1",
    })


def _client(cfg, relay_paths, hub_http, local_ac):
    return RelayClient(
        cfg, relay_paths,
        hub=HubClient(hub_http, device_token="dev-token", api_token="api-token"),
        local=LocalClient(local_ac),
    )


async def test_accept_while_running_drains_before_sync_refresh_preserves_accept(
    relay_paths, mock_hub, hub_http, fake_deps,
):
    from tests.conftest import lifespan_client

    AllowList(relay_paths.allowlist_path).add(
        "alice", display_name="Alice", renderer_version="1.0.0"
    )

    async with lifespan_client(fake_deps) as local_ac:
        client = _client(_cfg(relay_paths), relay_paths, hub_http, local_ac)
        hub_friends_accept(relay_paths, "bob")
        client.drain_commands_once()

        mock_hub.friends = [
            {
                "handle": "alice",
                "display_name": "Alice A.",
                "renderer_version": "1.0.1",
                "online": True,
                "via_invite_id": None,
            },
            {
                "handle": "bob",
                "display_name": "Bob",
                "renderer_version": "1.0.0",
                "online": True,
                "via_invite_id": None,
            },
        ]
        await client.sync_friends_once()

    reloaded = AllowList(relay_paths.allowlist_path)
    assert reloaded.contains("bob") is True
    assert reloaded.metadata("alice")["display_name"] == "Alice A."


def test_accept_while_stopped_replays_on_relay_start_and_removes_commands(relay_paths):
    hub_friends_accept(relay_paths, "carol")

    RelayClient(_cfg(relay_paths), relay_paths)

    assert AllowList(relay_paths.allowlist_path).contains("carol") is True
    assert relay_paths.commands_path.exists() is False


def test_command_inbox_tolerates_torn_tail(relay_paths, caplog):
    relay_paths.commands_path.write_text(
        json.dumps({"op": "accept", "handle": "dana", "ts": "2026-07-02T12:00:00Z"})
        + "\n"
        + '{"op": "accept", "handle": "erin"'
    )

    ops = CommandInbox(relay_paths.commands_path).drain()

    assert ops == [{"op": "accept", "handle": "dana", "ts": "2026-07-02T12:00:00Z"}]
    assert relay_paths.commands_path.exists() is False
    assert "commands.jsonl unreadable line" in caplog.text


def test_command_inbox_recovers_renamed_drain_snapshot(relay_paths):
    snapshot = relay_paths.commands_path.with_name(f"{relay_paths.commands_path.name}.draining")
    snapshot.write_text(
        json.dumps({"op": "accept", "handle": "faye", "ts": "2026-07-02T12:00:00Z"})
        + "\n"
    )

    ops = CommandInbox(relay_paths.commands_path).drain()

    assert ops == [{"op": "accept", "handle": "faye", "ts": "2026-07-02T12:00:00Z"}]
    assert snapshot.exists() is False


def test_command_inbox_drain_does_not_lose_append_opened_before_rename(
    relay_paths, monkeypatch,
):
    inbox = CommandInbox(relay_paths.commands_path)
    op = {"op": "accept", "handle": "gina", "ts": "2026-07-02T12:00:00Z"}
    write_entered = threading.Event()
    release_write = threading.Event()
    append_done = threading.Event()
    drain_ops: list[dict] = []
    original_write = os.write

    def delayed_write(fd, data):
        write_entered.set()
        assert release_write.wait(timeout=2), "test timed out waiting to release write"
        return original_write(fd, data)

    monkeypatch.setattr(relay_store.os, "write", delayed_write)

    def append_command():
        try:
            inbox.append(op)
        finally:
            append_done.set()

    def drain_commands():
        drain_ops.extend(inbox.drain())

    append_thread = threading.Thread(target=append_command)
    append_thread.start()
    assert write_entered.wait(timeout=2), "append did not reach write"

    drain_thread = threading.Thread(target=drain_commands)
    drain_thread.start()
    time.sleep(0.05)
    release_write.set()

    append_thread.join(timeout=2)
    drain_thread.join(timeout=2)
    assert append_done.is_set(), "append did not finish"
    assert not drain_thread.is_alive(), "drain did not finish"

    assert drain_ops + inbox.drain() == [op]


def test_unknown_command_is_warned_and_skipped(relay_paths, caplog):
    CommandInbox(relay_paths.commands_path).append(
        {"op": "frobnicate", "handle": "eve", "ts": "2026-07-02T12:00:00Z"}
    )

    RelayClient(_cfg(relay_paths), relay_paths)

    assert AllowList(relay_paths.allowlist_path).contains("eve") is False
    assert relay_paths.commands_path.exists() is False
    assert "unknown command op" in caplog.text
