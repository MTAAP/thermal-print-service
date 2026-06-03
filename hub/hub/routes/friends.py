from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Request

from hub.auth import TokenKind, authenticate
from hub.friends import list_friends
from hub.invites import create_invite
from hub.routes import AppDeps, bearer
from hub.schemas import CreateInviteResp, FriendOut

router = APIRouter()


@router.get("/friends", response_model=list[FriendOut])
async def get_friends(request: Request, authorization: str | None = Header(default=None)):
    deps: AppDeps = request.app.state.deps
    token = bearer(authorization)
    async with deps.sessionmaker() as s:
        try:
            me = await authenticate(s, token, required=TokenKind.API)
        except PermissionError:
            try:
                me = await authenticate(s, token, required=TokenKind.CONSOLE)
            except PermissionError as exc:
                raise HTTPException(status_code=403, detail=str(exc)) from exc
        return await list_friends(s, me.id, online_ids=deps.online)


@router.post("/invites", response_model=CreateInviteResp)
async def member_invite(request: Request, authorization: str | None = Header(default=None)):
    deps: AppDeps = request.app.state.deps
    token = bearer(authorization)
    async with deps.sessionmaker() as s:
        # api OR console: the Pi's CLI (`hub invite new`) uses its api token;
        # the web console uses its session token. Both issue member invites.
        me = None
        for kind in (TokenKind.API, TokenKind.CONSOLE):
            try:
                me = await authenticate(s, token, required=kind)
                break
            except PermissionError:
                continue
        if me is None:
            raise HTTPException(status_code=403, detail="invite requires api or console token")
        code = await create_invite(s, issuer_printer_id=me.id, ttl_s=7 * 24 * 3600)
        from hub.auth import hash_token
        from hub.models import Invite
        inv = await s.get(Invite, hash_token(code))
        assert inv is not None  # just committed in this session
        return CreateInviteResp(code=code, invite_id=inv.id, expires_at=inv.expires_at.isoformat())
