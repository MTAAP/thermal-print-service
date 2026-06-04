from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from hub.friends import list_friends
from hub.history import list_jobs
from hub.invites import create_invite
from hub.routes import AppDeps
from hub.send import send_document
from hub.web_auth import NotAuthenticated, console_printer

router = APIRouter()
_templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))

# A week-long member invite, matching the hub's other member-invite TTLs.
_INVITE_TTL_S = 7 * 24 * 3600

# Module-level singleton for the repeated "to" form field. Hoisted out of the
# parameter default because ruff B008 (no function calls in argument defaults)
# fires on a Form() backing a list-valued field; the call must live at import
# time, not per-request. default_factory=list yields a fresh [] per request.
_TO_FORM = Form(default_factory=list)


def _login_redirect() -> RedirectResponse:
    return RedirectResponse(url="/console/login", status_code=303)


@router.get("/")
async def friends_view(request: Request):
    deps: AppDeps = request.app.state.deps
    async with deps.sessionmaker() as s:
        try:
            me = await console_printer(request, s)
        except NotAuthenticated:
            return _login_redirect()
        friends = await list_friends(s, me.id, online_ids=deps.online)
    return _templates.TemplateResponse(
        request, "friends.html", {"me": me.handle, "friends": friends}
    )


@router.post("/friends/invite")
async def make_invite(request: Request):
    deps: AppDeps = request.app.state.deps
    async with deps.sessionmaker() as s:
        try:
            me = await console_printer(request, s)
        except NotAuthenticated:
            return _login_redirect()
        code = await create_invite(s, issuer_printer_id=me.id, ttl_s=_INVITE_TTL_S)
    # HTMX swaps this fragment into the invite slot; a full-page fallback also works
    # because the friends template includes the same partial.
    return _templates.TemplateResponse(request, "friends.html", {
        "me": me.handle, "friends": await _friends(deps, me.id), "invite_code": code,
    })


async def _friends(deps: AppDeps, owner_id: str):
    async with deps.sessionmaker() as s:
        return await list_friends(s, owner_id, online_ids=deps.online)


# The v1 composer uses ONLY the documented common-core block set that is stable
# across renderer versions (spec §6.2): a titled note is header + paragraph; a
# plain message is a single paragraph. No other block types are offered here.
# Field names verified against service/printer/schema/blocks.py: HeaderBlock and
# ParagraphBlock both carry a required `text: str` field (not `content`). The
# permissive test schema (blocks_schema={"type": "object"}) does NOT verify field
# names -- the real recipient schema does, so this must match the Pi's contract.
def _compose_document(title: str, message: str) -> dict:
    blocks: list[dict] = []
    if title.strip():
        blocks.append({"type": "header", "text": title.strip()})
    blocks.append({"type": "paragraph", "text": message})
    return {"blocks": blocks}


@router.get("/compose")
async def compose_view(request: Request):
    deps: AppDeps = request.app.state.deps
    async with deps.sessionmaker() as s:
        try:
            me = await console_printer(request, s)
        except NotAuthenticated:
            return _login_redirect()
        friends = await list_friends(s, me.id, online_ids=deps.online)
    return _templates.TemplateResponse(request, "compose.html", {
        "me": me.handle, "friends": friends, "results": None,
    })


@router.post("/compose")
async def compose_send(
    request: Request,
    to: list[str] = _TO_FORM,
    title: str = Form(default=""),
    message: str = Form(default=""),
):
    deps: AppDeps = request.app.state.deps
    async with deps.sessionmaker() as s:
        try:
            me = await console_printer(request, s)
        except NotAuthenticated:
            return _login_redirect()
        # Call the send logic module in-process -- NOT an HTTP self-call to /send.
        resp = await send_document(
            s, deps.wake, sender_handle=me.handle, to=to,
            document=_compose_document(title, message), idempotency_key=None,
            sender_rate_per_min=deps.config.sender_rate_per_min,
        )
        friends = await list_friends(s, me.id, online_ids=deps.online)
    return _templates.TemplateResponse(request, "compose.html", {
        "me": me.handle, "friends": friends, "results": resp.results,
    })


@router.get("/history")
async def history_view(request: Request):
    deps: AppDeps = request.app.state.deps
    async with deps.sessionmaker() as s:
        try:
            me = await console_printer(request, s)
        except NotAuthenticated:
            return _login_redirect()
        history = await list_jobs(s, owner_id=me.id, handle=me.handle)
    return _templates.TemplateResponse(request, "history.html", {
        "me": me.handle, "history": history,
    })
