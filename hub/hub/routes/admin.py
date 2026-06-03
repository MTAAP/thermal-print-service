from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Request

from hub.invites import create_invite
from hub.routes import AppDeps, bearer
from hub.schemas import CreateInviteResp

router = APIRouter()


def _deps(request: Request) -> AppDeps:
    return request.app.state.deps


@router.post("/admin/invites", response_model=CreateInviteResp)
async def admin_invite(request: Request, authorization: str | None = Header(default=None)):
    deps = _deps(request)
    token = bearer(authorization)
    if not deps.config.admin_token or token != deps.config.admin_token:
        raise HTTPException(status_code=403, detail="bad admin token")
    async with deps.sessionmaker() as s:
        code = await create_invite(s, issuer_printer_id=None, ttl_s=7 * 24 * 3600)
        from hub.auth import hash_token
        from hub.models import Invite
        inv = await s.get(Invite, hash_token(code))
        assert inv is not None  # just committed in this session
        return CreateInviteResp(code=code, invite_id=inv.id, expires_at=inv.expires_at.isoformat())
