from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from hub.invites import InviteError, redeem_invite
from hub.routes import AppDeps
from hub.schemas import RegisterReq, RegisterResp

router = APIRouter()


@router.post("/register", response_model=RegisterResp)
async def register(request: Request, body: RegisterReq):
    deps: AppDeps = request.app.state.deps
    async with deps.sessionmaker() as s:
        try:
            return await redeem_invite(s, code=body.code, handle=body.handle,
                                       display_name=body.display_name)
        except InviteError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
