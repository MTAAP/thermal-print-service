from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from printer.relay.store import AllowList, InviteStore


@dataclass
class SyncResult:
    added: list[str] = field(default_factory=list)
    held: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    refreshed: list[str] = field(default_factory=list)


def sync_friends(
    friends: list[dict[str, Any]], *, allowlist: AllowList, invites: InviteStore
) -> SyncResult:
    """Reconcile the hub's friend list against the LOCAL allow-list (spec 5).

    Authority is local: we auto-add ONLY friends matching a locally-recorded
    invite; everything else is held. We remove (unfriend) and refresh metadata,
    but NEVER silently auto-add an auto-print friend."""
    result = SyncResult()
    reported = {f["handle"]: f for f in friends}

    # Remove unfriended peers from the allow-list.
    for handle in allowlist.handles():
        if handle not in reported:
            allowlist.remove(handle)
            result.removed.append(handle)

    for handle, meta in reported.items():
        if allowlist.contains(handle):
            # Already auto-print: refresh metadata only (display name, version).
            allowlist.add(handle, display_name=meta.get("display_name"),
                          renderer_version=meta.get("renderer_version"))
            result.refreshed.append(handle)
            continue
        via_invite_id = meta.get("via_invite_id")
        if via_invite_id is not None and invites.has(via_invite_id):
            # Locally-pinned intent: WE issued this invite (its invite_id is in
            # our InviteStore), so auto-add.
            allowlist.add(handle, display_name=meta.get("display_name"),
                          renderer_version=meta.get("renderer_version"))
            result.added.append(handle)
        else:
            # Held: requires an explicit `hub friends accept <handle>`.
            result.held.append(handle)

    return result
