from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel

from hub.auth import TokenKind, authenticate
from hub.capabilities import CapabilityConflict, upsert_capability
from hub.routes import AppDeps, bearer

router = APIRouter()


class CapabilityReq(BaseModel):
    renderer_version: str
    blocks_schema: dict
    block_types: list[str]


@router.put("/capabilities")
async def put_capabilities(request: Request, body: CapabilityReq,
                           authorization: str | None = Header(default=None)):
    deps: AppDeps = request.app.state.deps
    token = bearer(authorization)
    async with deps.sessionmaker() as s:
        try:
            me = await authenticate(s, token, required=TokenKind.DEVICE)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        try:
            await upsert_capability(
                s, printer_id=me.id, renderer_version=body.renderer_version,
                blocks_schema=body.blocks_schema, block_types=body.block_types)
        except CapabilityConflict as exc:
            raise HTTPException(status_code=409, detail=exc.detail) from exc
    return {"ok": True}
