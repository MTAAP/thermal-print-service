from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError

from hub.auth import mint_console_token
from hub.friends import list_friends
from hub.history import list_jobs
from hub.invites import InviteError, create_invite, redeem_invite
from hub.routes import AppDeps
from hub.schemas import RegisterReq
from hub.send import send_document
from hub.web_auth import SESSION_TOKEN_KEY, NotAuthenticated, console_printer

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


def _is_htmx(request: Request) -> bool:
    # HTMX sets this header on every request it issues. We branch on it so an
    # interactive (JS) request gets back ONLY the fragment to swap into its
    # target slot, while a no-JS form POST gets a full page. Returning a full
    # page (which extends base.html) into an hx-swap="innerHTML" target is what
    # nested the entire console inside #results-slot / #invite-slot -- the
    # duplicate-UI bug. The header is the canonical HTMX request marker.
    return request.headers.get("hx-request") == "true"


def _same_origin(request: Request, public_url: str) -> bool:
    # Login-CSRF defense for POST /join. /join is the one state-changing endpoint
    # that works WITHOUT a session cookie, so SameSite=Lax (which protects the
    # authed console POSTs -- a cross-site POST drops the session cookie) gives it
    # no protection. A browser always sends Origin on a cross-origin form POST, so
    # reject when Origin (or Referer, as a fallback) is present and points at a
    # different host than ours. Absent both -> allow: a CSRF attack is by
    # definition browser-driven and will carry one. A misconfigured/empty
    # public_url never blocks a join (it would already have broken the join link).
    expected = urlparse(public_url).netloc
    if not expected:
        return True
    for header in ("origin", "referer"):
        value = request.headers.get(header)
        if value:
            return urlparse(value).netloc == expected
    return True


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
        # One invite, two onboarding paths: a shareable /join link for a friend
        # with no printer (web-only), and the raw code for a friend with a Pi
        # (`printer-svc hub join <code>`). The template surfaces both.
        join = f"{deps.config.public_url.rstrip('/')}/join?code={code}"
        # Interactive request: return only the invite-code fragment that the
        # friends page also includes, so HTMX swaps it into #invite-slot alone.
        if _is_htmx(request):
            return _templates.TemplateResponse(
                request, "invite_code.html", {"invite_code": code, "join_url": join}
            )
        friends = await list_friends(s, me.id, online_ids=deps.online)
    # No-JS fallback: the full friends page, with the code rendered in its slot.
    return _templates.TemplateResponse(request, "friends.html", {
        "me": me.handle, "friends": friends, "invite_code": code, "join_url": join,
    })


@router.get("/join")
async def join_view(request: Request, code: str | None = None):
    # Public onboarding page. Prefills the invite code from the query param so a
    # shared /join?code=... link is a single click. No session required -- this
    # is how a friend WITHOUT a Pi gets into the console at all.
    return _templates.TemplateResponse(request, "join.html", {"code": code})


@router.post("/join")
async def join_submit(
    request: Request,
    code: str = Form(...),
    handle: str = Form(...),
    display_name: str = Form(...),
):
    deps: AppDeps = request.app.state.deps
    # Reject cross-origin browser submits before doing any work (see _same_origin).
    if not _same_origin(request, deps.config.public_url):
        raise HTTPException(status_code=403, detail="cross-origin join blocked")
    # Validate via the same RegisterReq contract the JSON /register path uses, so
    # a web-joined handle obeys the identical rules. The message covers BOTH fields
    # because either can fail (a pasted >80-char display name, an uppercase handle).
    try:
        req = RegisterReq(code=code.strip(), handle=handle.strip(),
                          display_name=display_name.strip())
    except ValidationError:
        return _templates.TemplateResponse(request, "join.html", {
            "code": code, "handle": handle, "display_name": display_name,
            "error": "Handle must be 1-40 characters (lowercase letters, numbers, "
                     "dashes or underscores) and display name 1-80 characters.",
        })
    async with deps.sessionmaker() as s:
        try:
            reg = await redeem_invite(
                s, code=req.code, handle=req.handle, display_name=req.display_name
            )
        except InviteError as exc:
            return _templates.TemplateResponse(request, "join.html", {
                "code": code, "handle": handle, "display_name": display_name,
                "error": str(exc),
            })
        # Redeemed: establish a console session immediately (same CONSOLE token
        # mechanism as the login link) so a Pi-less friend is signed in without a
        # Pi to print a link or any hub-CLI access -- the onboarding wall.
        token = await mint_console_token(s, reg.printer_id)
    request.session[SESSION_TOKEN_KEY] = token
    return RedirectResponse(url="/", status_code=303)


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
        # Interactive request: return only the per-recipient results fragment
        # that the compose page also includes, so HTMX swaps it into
        # #results-slot alone instead of nesting the whole console.
        if _is_htmx(request):
            return _templates.TemplateResponse(
                request, "send_results.html", {"results": resp.results}
            )
        friends = await list_friends(s, me.id, online_ids=deps.online)
    # No-JS fallback: the full compose page, with results rendered in its slot.
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
