from __future__ import annotations

import math

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel

from hub.auth import TokenKind, authenticate
from hub.ids import new_id
from hub.jobs.lease import ack_delivered, lease_next, report_terminal
from hub.models import Job
from hub.routes import AppDeps, bearer

router = APIRouter()


async def _device(deps: AppDeps, s, authorization: str | None):
    token = bearer(authorization)
    try:
        return await authenticate(s, token, required=TokenKind.DEVICE)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.get("/inbox")
async def get_inbox(request: Request, wait: float | None = None,
                    authorization: str | None = Header(default=None)):
    deps: AppDeps = request.app.state.deps
    # Clamp the client-requested hold to the server's configured long-poll window.
    # An unbounded wait (e.g. ?wait=inf or ?wait=1e9) would pin a connection and an
    # asyncio task for ~forever -- a DoS any valid DEVICE token could trigger. The
    # client must never hold a poll longer than the window the server advertises.
    if wait is None:
        wait_s = deps.config.long_poll_wait_s
    else:
        if not math.isfinite(wait):
            raise HTTPException(status_code=400, detail="wait must be a finite number")
        wait_s = max(0.0, min(float(wait), deps.config.long_poll_wait_s))
    poll_id = new_id("poll")
    async with deps.sessionmaker() as s:
        me = await _device(deps, s, authorization)
        # Stamp last-seen so the web Friends view can show recency even when the
        # printer is not currently holding a poll. Online (deps.online) is the
        # live signal; last_seen_at is the durable fallback.
        from datetime import UTC, datetime

        me.last_seen_at = datetime.now(UTC)
        await s.commit()
    deps.online.add(me.id)
    try:
        # Try immediately, then wait on the wakeup event once if empty.
        async with deps.sessionmaker() as s:
            job = await lease_next(s, recipient_id=me.id, poll_id=poll_id,
                                   visibility_s=deps.config.lease_visibility_timeout_s)
        if job is None:
            await deps.wake.wait(me.id, timeout=wait_s)
            async with deps.sessionmaker() as s:
                job = await lease_next(s, recipient_id=me.id, poll_id=poll_id,
                                       visibility_s=deps.config.lease_visibility_timeout_s)
        if job is None:
            return {"job": None}
        return {"job": {
            "job_id": job.id, "sender": job.sender_handle, "kind": job.kind,
            "sent_at": job.sent_at.isoformat(), "payload": job.payload,
        }}
    finally:
        deps.online.release(me.id)


@router.post("/jobs/{job_id}/ack")
async def post_ack(request: Request, job_id: str,
                   authorization: str | None = Header(default=None)):
    deps: AppDeps = request.app.state.deps
    async with deps.sessionmaker() as s:
        me = await _device(deps, s, authorization)
        # Ownership guard: a device may only ack jobs addressed to it. 404 (not
        # 403) so a device cannot probe the existence of other printers' jobs.
        job = await s.get(Job, job_id)
        if job is None or job.recipient_id != me.id:
            raise HTTPException(status_code=404, detail="job not found")
        ok = await ack_delivered(s, job_id=job_id, poll_id="")
    if not ok:
        raise HTTPException(status_code=409, detail="job not in leased state")
    return {"ok": True}


class StatusReq(BaseModel):
    status: str


@router.post("/jobs/{job_id}/status")
async def post_status(request: Request, job_id: str, body: StatusReq,
                      authorization: str | None = Header(default=None)):
    deps: AppDeps = request.app.state.deps
    async with deps.sessionmaker() as s:
        me = await _device(deps, s, authorization)
        # Ownership guard: a device may only report status on its own jobs.
        job = await s.get(Job, job_id)
        if job is None or job.recipient_id != me.id:
            raise HTTPException(status_code=404, detail="job not found")
        try:
            ok = await report_terminal(s, job_id=job_id, status=body.status)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not ok:
        raise HTTPException(status_code=409, detail="job not in a reportable state")
    return {"ok": True}
