from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request


class MockHub:
    """In-process fake hub. Tests queue jobs into ``inbox`` and inspect the
    recorded ack/status/capability/invite/friends calls. Auth is not enforced
    here (the hub's own auth is tested in the hub plan); the relay tests assert
    the relay sends the right token in the Authorization header."""

    def __init__(self) -> None:
        self.inbox: list[dict[str, Any]] = []
        self.acked: list[str] = []
        self.statuses: list[tuple[str, str]] = []  # (job_id, status), all attempts
        # First terminal status recorded per job; drives the idempotent 200 vs.
        # conflicting-409 response (the relay must tolerate the 409 -- Fix A).
        self._terminal_status: dict[str, str] = {}
        self.capabilities: list[dict[str, Any]] = []
        self.invites_created = 0
        self.friends: list[dict[str, Any]] = []
        self.auth_seen: list[str | None] = []
        self.fail_inbox_times = 0  # for reconnect tests: 503 then recover
        self.fail_friends_times = 0  # for friend-sync isolation tests: 503 then recover
        self.friends_fetched = 0  # how many times GET /friends was served

    def app(self) -> FastAPI:
        api = FastAPI()

        @api.post("/register")
        async def register(body: dict) -> dict:
            return {
                "printer_id": "prn_self", "handle": body["handle"],
                "device_token": "dev-token", "api_token": "api-token",
                "inviter_handle": "alice",
            }

        @api.post("/invites")
        async def invites(request: Request) -> dict:
            self.auth_seen.append(request.headers.get("authorization"))
            self.invites_created += 1
            n = self.invites_created
            # CreateInviteResp: {code, invite_id, expires_at}.
            return {"code": f"CODE{n}", "invite_id": f"inv_{n}",
                    "expires_at": "2026-06-10T00:00:00+00:00"}

        @api.get("/friends")
        async def get_friends(request: Request) -> list[dict]:
            self.auth_seen.append(request.headers.get("authorization"))
            if self.fail_friends_times > 0:
                self.fail_friends_times -= 1
                from fastapi.responses import JSONResponse
                return JSONResponse(status_code=503, content={"detail": "down"})
            self.friends_fetched += 1
            return self.friends

        @api.put("/capabilities")
        async def put_caps(request: Request, body: dict) -> dict:
            self.auth_seen.append(request.headers.get("authorization"))
            self.capabilities.append(body)
            return {"ok": True}

        @api.get("/inbox")
        async def inbox(request: Request, wait: float = 25.0) -> dict:
            self.auth_seen.append(request.headers.get("authorization"))
            if self.fail_inbox_times > 0:
                self.fail_inbox_times -= 1
                from fastapi.responses import JSONResponse
                return JSONResponse(status_code=503, content={"detail": "down"})
            if self.inbox:
                return {"job": self.inbox.pop(0)}
            return {"job": None}

        @api.post("/jobs/{job_id}/ack")
        async def ack(job_id: str) -> dict:
            self.acked.append(job_id)
            return {"ok": True}

        @api.post("/jobs/{job_id}/status")
        async def status(job_id: str, body: dict) -> dict:
            new_status = body["status"]
            self.statuses.append((job_id, new_status))
            # Model the now-idempotent hub: a job is terminal once a status is
            # recorded. Re-posting the SAME terminal status returns 200; posting
            # a DIFFERENT status for an already-terminal job returns 409 (the
            # relay must tolerate this -- Fix A). First status always wins.
            prior = self._terminal_status.get(job_id)
            if prior is None:
                self._terminal_status[job_id] = new_status
                return {"ok": True}
            if prior == new_status:
                return {"ok": True}
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=409,
                content={"detail": "job already terminal", "current_status": prior},
            )

        return api
