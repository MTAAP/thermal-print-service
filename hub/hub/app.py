from __future__ import annotations

import asyncio
import contextlib
import logging
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
    console_login,
    friends,
    health,
    inbox,
    register,
    send,
    web,
)

logger = logging.getLogger("hub")


def create_app(deps: AppDeps, *, run_sweeper: bool = True) -> FastAPI:
    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.deps = deps
        task: asyncio.Task | None = None
        if run_sweeper:
            async def _loop() -> None:
                while True:
                    await asyncio.sleep(30)
                    try:
                        async with deps.sessionmaker() as s:
                            await sweep(s, job_ttl_s=deps.config.job_ttl_s)
                    except Exception:
                        # A transient DB error (Railway Postgres deploy rollover /
                        # idle-connection recycling) must NOT kill lease reclamation
                        # for the life of the process. Log and retry next interval.
                        logger.exception("hub sweep failed; retrying next interval")
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

    from starlette.middleware.sessions import SessionMiddleware

    # Signed, httpOnly, SameSite=Lax session cookie. Lax is the v1 CSRF mitigation
    # for the small trusted group (spec §2/§11); a CSRF-token layer is follow-on.
    app.add_middleware(
        SessionMiddleware,
        secret_key=deps.config.session_secret,
        same_site="lax",
        # Secure flag is on by default (HUB_SESSION_HTTPS_ONLY); behind Railway TLS
        # the console session cookie (a CONSOLE bearer token) must never ride a
        # plaintext hop. Only local HTTP dev / tests set it false.
        https_only=deps.config.session_https_only,
    )

    from pathlib import Path

    from fastapi.staticfiles import StaticFiles

    static_dir = Path(__file__).resolve().parent / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    for mod in (health, admin, register, friends, capabilities, send, inbox,
                console_login, web):
        app.include_router(mod.router)
    return app


async def build_default_app() -> FastAPI:
    cfg = HubConfig.from_env()
    engine = make_engine(cfg.database_url)
    await init_models(engine)
    deps = AppDeps(config=cfg, sessionmaker=make_sessionmaker(engine),
                   wake=WakeupRegistry(), online=set())
    return create_app(deps)
