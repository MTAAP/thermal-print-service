from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from hub.auth import TokenKind, authenticate
from hub.routes import AppDeps, bearer
from hub.schemas import SendReq
from hub.send import send_document

router = APIRouter()


@router.post("/send")
async def post_send(request: Request, body: SendReq,
                    authorization: str | None = Header(default=None)):
    deps: AppDeps = request.app.state.deps
    token = bearer(authorization)
    async with deps.sessionmaker() as s:
        me = None
        for kind in (TokenKind.API, TokenKind.CONSOLE):
            try:
                me = await authenticate(s, token, required=kind)
                break
            except PermissionError:
                continue
        if me is None:
            raise HTTPException(status_code=403, detail="send requires api or console token")
        resp = await send_document(
            s, deps.wake, sender_handle=me.handle, to=body.to,
            document=body.document, raw_png_b64=body.raw_png_b64,
            idempotency_key=body.idempotency_key,
            sender_rate_per_min=deps.config.sender_rate_per_min,
        )
    any_ok = any(r.status == "queued" for r in resp.results)
    code = 202 if any_ok else 400
    return JSONResponse(status_code=code, content=resp.model_dump())
