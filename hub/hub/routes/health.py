from __future__ import annotations

from fastapi import APIRouter

from hub.__about__ import __version__
from hub.config import build_git_sha

router = APIRouter()


@router.get("/healthz")
async def healthz() -> dict[str, bool | str]:
    return {"ok": True, "git_sha": build_git_sha(), "version": __version__}
