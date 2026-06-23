from printer.relay.store import AllowList, InviteStore
from printer.relay.sync import sync_friends


def _al(tmp_path):
    return AllowList(tmp_path / "allowlist.json")


def _inv(tmp_path):
    return InviteStore(tmp_path / "invites.json")


def test_friend_matching_local_invite_is_auto_added(tmp_path):
    al = _al(tmp_path)
    inv = _inv(tmp_path)
    inv.record("inv_mine")
    friends = [{
        "handle": "bob", "display_name": "Bob", "renderer_version": "1.0.0",
        "online": True, "via_invite_id": "inv_mine",
    }]
    result = sync_friends(friends, allowlist=al, invites=inv)
    assert al.contains("bob") is True
    assert result.added == ["bob"] and result.held == []


def test_friend_without_local_invite_is_held_not_added(tmp_path):
    al = _al(tmp_path)
    inv = _inv(tmp_path)  # no invites recorded
    friends = [{
        "handle": "mallory", "display_name": "Mallory", "renderer_version": None,
        "online": False, "via_invite_id": "inv_they_fabricated",
    }]
    result = sync_friends(friends, allowlist=al, invites=inv)
    # A compromised hub cannot make us auto-print for a party we did not invite:
    # there is no locally-recorded invite_id matching the fabricated via_invite_id.
    assert al.contains("mallory") is False
    assert result.held == ["mallory"] and result.added == []


def test_unfriend_removes_from_allowlist(tmp_path):
    al = _al(tmp_path)
    al.add("bob", display_name="Bob", renderer_version="1.0.0")
    inv = _inv(tmp_path)
    # bob no longer in the friend list -> removed
    result = sync_friends([], allowlist=al, invites=inv)
    assert al.contains("bob") is False
    assert result.removed == ["bob"]


def test_metadata_refresh_does_not_re_add_held_friend(tmp_path):
    al = _al(tmp_path)
    al.add("bob", display_name="Bob", renderer_version="1.0.0")
    inv = _inv(tmp_path)
    friends = [
        {"handle": "bob", "display_name": "Bobby", "renderer_version": "2.0.0",
         "online": True, "via_invite_id": None},  # already allow-listed: refresh only
        {"handle": "eve", "display_name": "Eve", "renderer_version": None,
         "online": True, "via_invite_id": None},  # not invited locally: held
    ]
    result = sync_friends(friends, allowlist=al, invites=inv)
    assert al.metadata("bob")["display_name"] == "Bobby"
    assert al.metadata("bob")["renderer_version"] == "2.0.0"
    assert al.contains("eve") is False
    assert result.held == ["eve"] and result.added == [] and result.removed == []
