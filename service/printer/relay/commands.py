from __future__ import annotations

from typing import Any

import httpx

from printer.relay.hub_client import HubClient, register
from printer.relay.paths import RelayPaths
from printer.relay.store import AllowList, CredsStore, InviteStore


async def hub_join(
    paths: RelayPaths, client: httpx.AsyncClient, *, hub_url: str,
    code: str, handle: str, display_name: str,
) -> dict[str, Any]:
    """Redeem an invite, store creds, and pin the inviter into the local
    allow-list (the redeemer's local action == locally-pinned intent, spec 5)."""
    reg = await register(client, code=code, handle=handle, display_name=display_name)
    CredsStore(paths.creds_path).save({
        "printer_id": reg["printer_id"], "handle": reg["handle"], "hub_url": hub_url,
        "device_token": reg["device_token"], "api_token": reg["api_token"],
    })
    inviter = reg.get("inviter_handle")
    if inviter:
        AllowList(paths.allowlist_path).add(
            inviter, display_name=inviter, renderer_version=None
        )
    return reg


async def hub_invite_new(paths: RelayPaths, client: httpx.AsyncClient) -> tuple[str, str]:
    """Create an invite via the hub and record its stable invite_id locally so
    the later redemption can be matched (inviter-side locally-pinned intent,
    spec 5). Returns (code, invite_id): the plaintext code is shown to the user
    to share out-of-band; the invite_id is recorded locally (NOT the code) — a
    friend's via_invite_id from GET /friends is matched against it."""
    creds = CredsStore(paths.creds_path).load()
    if creds is None:
        raise RuntimeError("not joined to a hub; run `hub join <code>` first")
    hub = HubClient(client, device_token=creds["device_token"], api_token=creds["api_token"])
    code, invite_id = await hub.create_invite()
    InviteStore(paths.invites_path).record(invite_id)
    return code, invite_id


def hub_friends_accept(paths: RelayPaths, handle: str) -> None:
    """Manually add a HELD friend to the local allow-list (explicit local
    action — the only way a non-invite-matched friend ever auto-prints)."""
    AllowList(paths.allowlist_path).add(handle, display_name=handle, renderer_version=None)


def hub_leave(paths: RelayPaths) -> None:
    CredsStore(paths.creds_path).clear()


def hub_status(paths: RelayPaths) -> dict[str, Any]:
    creds = CredsStore(paths.creds_path).load()
    if creds is None:
        return {"joined": False}
    al = AllowList(paths.allowlist_path)
    return {
        "joined": True, "handle": creds["handle"], "hub_url": creds["hub_url"],
        "allowlisted_friends": al.handles(),
    }
