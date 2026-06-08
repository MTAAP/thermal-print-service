from __future__ import annotations

import contextlib
import secrets
from typing import Any

import httpx

from printer.relay.hub_client import HubClient, register
from printer.relay.local_client import LocalClient, SubmitOutcome
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


def _login_link_document(url: str, expires_in_s: int) -> dict[str, Any]:
    """A small thermal document: a scannable QR of the login URL, the URL in
    plain text (in case the QR won't scan), and a single-use/expiry note. Uses
    only common-core blocks the local renderer always supports."""
    minutes = max(1, expires_in_s // 60)
    return {"blocks": [
        {"type": "header", "text": "Printer Pals login"},
        {"type": "qr", "data": url, "caption": "Scan to open the console", "size": "lg"},
        {"type": "paragraph", "text": url},
        {"type": "paragraph", "text": f"Single-use link. Expires in about {minutes} min."},
    ]}


async def hub_login_link(
    paths: RelayPaths, hub_client: httpx.AsyncClient, local_client: httpx.AsyncClient,
) -> tuple[str, int]:
    """Ask the hub to mint a one-time console login link for THIS Pi's handle,
    then print it (QR + URL) on local paper. Returns (url, expires_in_s) so the
    CLI can also echo it. Device-owned action -> device-token auth.

    A fresh random idempotency key per invocation: every `hub login-link` mints
    a brand-new link, so the local print must never be deduped against a prior
    one (the same operator running it twice wants two slips, not one)."""
    creds = CredsStore(paths.creds_path).load()
    if creds is None:
        raise RuntimeError("not joined to a hub; run `hub join <code>` first")
    hub = HubClient(hub_client, device_token=creds["device_token"], api_token=creds["api_token"])
    url, expires_in_s = await hub.create_login_link()
    result = await LocalClient(local_client).print_document(
        _login_link_document(url, expires_in_s),
        sender="login-link", idempotency_key=secrets.token_urlsafe(12),
    )
    if result.outcome is not SubmitOutcome.ACCEPTED:
        raise RuntimeError(f"local print did not accept the login link: {result.outcome.value}")
    return url, expires_in_s


def hub_friends_accept(paths: RelayPaths, handle: str) -> None:
    """Manually add a HELD friend to the local allow-list (explicit local
    action — the only way a non-invite-matched friend ever auto-prints)."""
    AllowList(paths.allowlist_path).add(handle, display_name=handle, renderer_version=None)


def hub_leave(paths: RelayPaths) -> None:
    for path in (
        paths.creds_path,
        paths.allowlist_path,
        paths.invites_path,
        paths.jobmap_path,
        paths.rate_path,
    ):
        with contextlib.suppress(FileNotFoundError):
            path.unlink()


def hub_status(paths: RelayPaths) -> dict[str, Any]:
    creds = CredsStore(paths.creds_path).load()
    if creds is None:
        return {"joined": False}
    al = AllowList(paths.allowlist_path)
    return {
        "joined": True, "handle": creds["handle"], "hub_url": creds["hub_url"],
        "allowlisted_friends": al.handles(),
    }
