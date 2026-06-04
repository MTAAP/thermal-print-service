from __future__ import annotations

import asyncio

import uvicorn


def main() -> None:
    import os
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "run":
        from hub.app import build_default_app
        # build_default_app is synchronous; uvicorn owns the event loop and runs
        # the lifespan (which opens the DB) on it. Do NOT wrap this in a separate
        # run_until_complete loop -- that opens asyncpg connections on a loop the
        # server never uses, poisoning the pool.
        app = build_default_app()
        uvicorn.run(app, host=os.environ.get("HUB_HOST", "0.0.0.0"),
                    port=int(os.environ.get("PORT", "8000")))
        return

    if len(sys.argv) > 2 and sys.argv[1] == "mint-login-link":
        handle = sys.argv[2]
        from hub.config import HubConfig
        from hub.db import make_engine, make_sessionmaker
        from hub.login import create_login_link, login_url

        cfg = HubConfig.from_env()
        engine = make_engine(cfg.database_url)
        sm = make_sessionmaker(engine)

        async def _mint() -> str:
            async with sm() as s:
                return await create_login_link(s, handle=handle, ttl_s=cfg.login_link_ttl_s)

        code = asyncio.get_event_loop().run_until_complete(_mint())
        # Print the login URL for the operator to open. cfg.public_url defaults to
        # a loud placeholder that fails DNS (matching the MCP misconfig convention),
        # and login_url is shared with the device-facing /login-links endpoint.
        print(login_url(cfg.public_url, code))
        return

    print("usage: printer-hub run | mint-login-link <handle>")
    raise SystemExit(2)
