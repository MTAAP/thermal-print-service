from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel

from hub.auth import TokenKind, authenticate
from hub.ids import new_id
from hub.jobs.lease import ack_delivered, lease_next, report_terminal
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
    wait_s = deps.config.long_poll_wait_s if wait is None else float(wait)
    poll_id = new_id("poll")
    async with deps.sessionmaker() as s:
        me = await _device(deps, s, authorization)
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
        deps.online.discard(me.id)


@router.post("/jobs/{job_id}/ack")
async def post_ack(request: Request, job_id: str,
                   authorization: str | None = Header(default=None)):
    deps: AppDeps = request.app.state.deps
    async with deps.sessionmaker() as s:
        await _device(deps, s, authorization)
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
        await _device(deps, s, authorization)
        try:
            ok = await report_terminal(s, job_id=job_id, status=body.status)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not ok:
        raise HTTPException(status_code=409, detail="job not in a reportable state")
    return {"ok": True}
