from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from hub.config import HubConfig
from hub.jobs.wakeup import WakeupRegistry
from hub.presence import Presence


@dataclass
class AppDeps:
    config: HubConfig
    sessionmaker: async_sessionmaker[AsyncSession]
    wake: WakeupRegistry
    online: Presence  # ref-counted /inbox-poll presence per printer id
    # The engine is carried so the lifespan can run init_models on the server's
    # event loop (prod). Tests build deps without it and create tables in their
    # own fixture, so it defaults to None.
    engine: AsyncEngine | None = None


def bearer(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail="missing bearer token")
    return authorization.split(" ", 1)[1]
