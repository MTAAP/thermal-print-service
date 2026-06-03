from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator

from fastapi import FastAPI

from hub.config import HubConfig
from hub.db import init_models, make_engine, make_sessionmaker
from hub.jobs.lease import sweep
from hub.jobs.wakeup import WakeupRegistry
from hub.routes import (
    AppDeps,
    admin,
    capabilities,
    friends,
    health,
    inbox,
    register,
    send,
)


def create_app(deps: AppDeps, *, run_sweeper: bool = True) -> FastAPI:
    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.deps = deps
        task: asyncio.Task | None = None
        if run_sweeper:
            async def _loop() -> None:
                while True:
                    await asyncio.sleep(30)
                    async with deps.sessionmaker() as s:
                        await sweep(s, job_ttl_s=deps.config.job_ttl_s)
            task = asyncio.create_task(_loop())
        try:
            yield
        finally:
            if task is not None:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

    app = FastAPI(title="thermal-print-hub", lifespan=lifespan)
    app.state.deps = deps
    for mod in (health, admin, register, friends, capabilities, send, inbox):
        app.include_router(mod.router)
    return app


async def build_default_app() -> FastAPI:
    cfg = HubConfig.from_env()
    engine = make_engine(cfg.database_url)
    await init_models(engine)
    deps = AppDeps(config=cfg, sessionmaker=make_sessionmaker(engine),
                   wake=WakeupRegistry(), online=set())
    return create_app(deps)
