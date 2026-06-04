from __future__ import annotations

from typing import Any

import httpx


class HubClient:
    """Thin async wrapper over the hub HTTP API. Device token drives the
    receive path (inbox/ack/status/capabilities); api token drives member
    actions (invites/friends). Two tokens, two scopes (spec 9.1)."""

    def __init__(self, client: httpx.AsyncClient, *, device_token: str, api_token: str) -> None:
        self._c = client
        self._dev = {"Authorization": f"Bearer {device_token}"}
        self._api = {"Authorization": f"Bearer {api_token}"}

    async def get_inbox(self, *, wait_s: float) -> dict[str, Any] | None:
        r = await self._c.get("/inbox", params={"wait": wait_s}, headers=self._dev,
                              timeout=wait_s + 10.0)
        r.raise_for_status()
        return r.json().get("job")

    async def ack(self, job_id: str) -> None:
        r = await self._c.post(f"/jobs/{job_id}/ack", headers=self._dev)
        r.raise_for_status()

    async def post_status(self, job_id: str, status: str) -> None:
        r = await self._c.post(f"/jobs/{job_id}/status", json={"status": status},
                               headers=self._dev)
        # 409 means the hub already considers this job terminal in a DIFFERENT
        # state (the hub is idempotent for the same terminal status -> 200). We
        # treat the conflict as success so _report_terminal still advances the
        # JobMap past 'delivered'; otherwise a 409 during startup replay would
        # raise httpx.HTTPStatusError and crash-loop the relay forever (the map
        # stays at 'delivered', so every restart re-triggers the identical 409).
        if r.status_code == 409:
            return
        r.raise_for_status()

    async def put_capabilities(
        self, *, renderer_version: str, blocks_schema: dict, block_types: list[str]
    ) -> None:
        r = await self._c.put("/capabilities", headers=self._dev, json={
            "renderer_version": renderer_version,
            "blocks_schema": blocks_schema,
            "block_types": block_types,
        })
        r.raise_for_status()

    async def create_invite(self) -> tuple[str, str]:
        # CreateInviteResp = {code, invite_id, expires_at}. The code is shown to
        # the user to share out-of-band; the invite_id is the stable handle the
        # relay records locally and later matches against a friend's via_invite_id.
        r = await self._c.post("/invites", headers=self._api)
        r.raise_for_status()
        body = r.json()
        return body["code"], body["invite_id"]

    async def get_friends(self) -> list[dict[str, Any]]:
        r = await self._c.get("/friends", headers=self._api)
        r.raise_for_status()
        return r.json()

    async def create_login_link(self) -> tuple[str, int]:
        # POST /login-links (device token): the hub mints a one-time CONSOLE
        # login link for THIS device's handle and returns the full URL to print
        # plus its TTL. Device-token scoped because a login link is bearer-
        # equivalent -- only the handle's own device may mint one. The Pi never
        # sees the raw code; it prints exactly the URL the hub builds.
        r = await self._c.post("/login-links", headers=self._dev)
        r.raise_for_status()
        body = r.json()
        return body["url"], body["expires_in_s"]


async def register(client: httpx.AsyncClient, *, code: str, handle: str,
                   display_name: str) -> dict[str, Any]:
    """POST /register with an invite code -> fresh creds. Standalone (no tokens
    exist yet at join time)."""
    r = await client.post("/register", json={
        "code": code, "handle": handle, "display_name": display_name,
    })
    r.raise_for_status()
    return r.json()
