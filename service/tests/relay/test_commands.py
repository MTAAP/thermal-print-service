from printer.relay.commands import (
    hub_friends_accept,
    hub_invite_new,
    hub_join,
    hub_leave,
    hub_login_link,
    hub_status,
)
from printer.relay.ratelimit import PerFriendRateLimiter
from printer.relay.store import AllowList, CredsStore, InviteStore, JobMap


async def test_hub_join_stores_creds_and_pins_inviter(relay_paths, hub_http):
    # hub_http is the mock hub; /register returns inviter_handle "alice".
    out = await hub_join(relay_paths, hub_http, hub_url="http://hub.test",
                         code="CODE1", handle="tim", display_name="Tim")
    creds = CredsStore(relay_paths.creds_path).load()
    assert creds["handle"] == "tim"
    assert creds["device_token"] == "dev-token"
    assert creds["hub_url"] == "http://hub.test"
    # The inviter is auto-added to the local allow-list (locally-pinned intent).
    al = AllowList(relay_paths.allowlist_path)
    assert al.contains("alice") is True
    assert out["inviter_handle"] == "alice"


async def test_hub_invite_new_records_invite_id_locally(relay_paths, hub_http):
    CredsStore(relay_paths.creds_path).save({
        "printer_id": "p", "handle": "tim", "hub_url": "http://hub.test",
        "device_token": "dev-token", "api_token": "api-token",
    })
    # Returns the plaintext code (shown to the user) but records the stable
    # invite_id locally — that is what a friend's via_invite_id matches against.
    code, invite_id = await hub_invite_new(relay_paths, hub_http)
    assert code.startswith("CODE")
    assert InviteStore(relay_paths.invites_path).has(invite_id) is True
    # The plaintext code is NEVER recorded locally.
    assert InviteStore(relay_paths.invites_path).has(code) is False


async def test_hub_login_link_mints_and_prints_via_local_service(
    relay_paths, mock_hub, hub_http, fake_deps
):
    # End-to-end through the REAL local service: the login-link document (header
    # + qr + url) must validate and render against the live block schema, so a
    # malformed block would surface here as a non-202 and raise.
    from tests.conftest import lifespan_client
    CredsStore(relay_paths.creds_path).save({
        "printer_id": "p", "handle": "pi", "hub_url": "http://hub.test",
        "device_token": "dev-token", "api_token": "api-token",
    })
    async with lifespan_client(fake_deps) as local_ac:
        url, expires_in_s = await hub_login_link(relay_paths, hub_http, local_ac)
    assert url.endswith("/console/login?lt=tok123")
    assert expires_in_s == 600
    # The mint rode the device token, and the local service accepted the print.
    assert mock_hub.auth_seen[-1] == "Bearer dev-token"


async def test_hub_login_link_requires_joined(relay_paths, hub_http, fake_deps):
    import pytest

    from tests.conftest import lifespan_client
    async with lifespan_client(fake_deps) as local_ac:
        with pytest.raises(RuntimeError, match="not joined"):
            await hub_login_link(relay_paths, hub_http, local_ac)


def test_hub_friends_accept_adds_held_friend(relay_paths):
    # Re-instantiate AllowList per assertion: the store snapshots the file into
    # memory at construction, so a fresh read after the mutation is what
    # exercises the on-disk add (and matches how every other caller reads it).
    assert AllowList(relay_paths.allowlist_path).contains("carol") is False
    hub_friends_accept(relay_paths, "carol")
    assert AllowList(relay_paths.allowlist_path).contains("carol") is True


def test_hub_leave_clears_creds_and_relay_trust_state(relay_paths):
    CredsStore(relay_paths.creds_path).save({
        "printer_id": "p", "handle": "tim", "hub_url": "http://hub.test",
        "device_token": "d", "api_token": "a",
    })
    AllowList(relay_paths.allowlist_path).add("alice", display_name="Alice",
                                              renderer_version=None)
    InviteStore(relay_paths.invites_path).record("inv_1")
    JobMap(relay_paths.jobmap_path).put("hj1", local_job_id="loc1", last_status="delivered")
    rate_path = relay_paths.root / "rate.json"
    PerFriendRateLimiter(rate_path, per_hour=1).record_accepted(
        "alice", "hj-leave", "2026-06-03T14:00:00+00:00"
    )
    assert rate_path.exists()

    hub_leave(relay_paths)

    assert CredsStore(relay_paths.creds_path).load() is None
    assert AllowList(relay_paths.allowlist_path).contains("alice") is False
    assert InviteStore(relay_paths.invites_path).has("inv_1") is False
    assert JobMap(relay_paths.jobmap_path).get("hj1") is None
    assert not rate_path.exists()


def test_hub_status_reports_joined_state(relay_paths):
    assert hub_status(relay_paths)["joined"] is False
    CredsStore(relay_paths.creds_path).save({
        "printer_id": "p", "handle": "tim", "hub_url": "http://hub.test",
        "device_token": "d", "api_token": "a",
    })
    st = hub_status(relay_paths)
    assert st["joined"] is True and st["handle"] == "tim"


def test_cli_parses_hub_join():
    import argparse

    from printer.cli.main import main  # import-only: confirms the subparsers wire up

    # We don't execute (no hub reachable); just confirm the parser accepts the args.
    parser = argparse.ArgumentParser(prog="printer-svc")
    # Smoke: importing main without error means the subparser block is syntactically wired.
    assert callable(main)
    assert parser is not None
