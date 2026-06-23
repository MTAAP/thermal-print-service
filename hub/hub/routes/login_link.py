from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Request

from hub.auth import TokenKind, authenticate
from hub.login import create_login_link, login_url
from hub.routes import AppDeps, bearer
from hub.schemas import LoginLinkResp

router = APIRouter()


@router.post("/login-links", response_model=LoginLinkResp)
async def mint_login_link(request: Request, authorization: str | None = Header(default=None)):
    """A registered device mints a one-time console login link for ITS OWN
    handle and gets back a ready-to-print URL.

    Device-token ONLY, deliberately: a login link is bearer-equivalent (whoever
    opens it gets a console session for the handle), so only the device that
    owns the handle -- proven by its device token -- may request one. API and
    console callers act on behalf of a human and must not be able to mint a
    fresh session link for an arbitrary device.
    """
    deps: AppDeps = request.app.state.deps
    token = bearer(authorization)
    async with deps.sessionmaker() as s:
        try:
            me = await authenticate(s, token, required=TokenKind.DEVICE)
        except PermissionError as exc:
            raise HTTPException(
                status_code=403, detail="login link requires a device token"
            ) from exc
        code = await create_login_link(s, handle=me.handle, ttl_s=deps.config.login_link_ttl_s)
    return LoginLinkResp(
        url=login_url(deps.config.public_url, code),
        expires_in_s=deps.config.login_link_ttl_s,
    )
