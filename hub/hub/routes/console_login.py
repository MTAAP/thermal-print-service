from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from hub.login import LoginLinkError, consume_login_link
from hub.routes import AppDeps
from hub.web_auth import SESSION_TOKEN_KEY

router = APIRouter()
_templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))


@router.get("/console/login")
async def console_login(request: Request, lt: str | None = None):
    deps: AppDeps = request.app.state.deps
    if lt:
        async with deps.sessionmaker() as s:
            try:
                token = await consume_login_link(s, code=lt)
            except LoginLinkError:
                token = None
        if token is not None:
            request.session[SESSION_TOKEN_KEY] = token
            # 303 so the browser re-GETs Friends without resubmitting the link.
            return RedirectResponse(url="/", status_code=303)
    # No link, or an invalid/expired/used one: render the landing notice.
    return _templates.TemplateResponse(
        request, "login_landing.html", {"invalid": bool(lt)}
    )


@router.post("/console/logout")
async def console_logout(request: Request):
    deps: AppDeps = request.app.state.deps
    token = request.session.pop(SESSION_TOKEN_KEY, None)
    if token:
        from hub.auth import revoke_token
        async with deps.sessionmaker() as s:
            await revoke_token(s, token)
    return RedirectResponse(url="/console/login", status_code=303)
