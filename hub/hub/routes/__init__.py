from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hub.config import HubConfig
from hub.jobs.wakeup import WakeupRegistry


@dataclass
class AppDeps:
    config: HubConfig
    sessionmaker: async_sessionmaker[AsyncSession]
    wake: WakeupRegistry
    online: set[str]  # printer ids currently holding an /inbox poll (presence)


def bearer(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail="missing bearer token")
    return authorization.split(" ", 1)[1]
