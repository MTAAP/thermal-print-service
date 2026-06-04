from __future__ import annotations

import asyncio

import uvicorn


def main() -> None:
    import os
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "run":
        from hub.app import build_default_app
        app = asyncio.get_event_loop().run_until_complete(build_default_app())
        uvicorn.run(app, host=os.environ.get("HUB_HOST", "0.0.0.0"),
                    port=int(os.environ.get("PORT", "8000")))
        return

    if len(sys.argv) > 2 and sys.argv[1] == "mint-login-link":
        handle = sys.argv[2]
        from hub.config import HubConfig
        from hub.db import make_engine, make_sessionmaker
        from hub.login import create_login_link

        cfg = HubConfig.from_env()
        engine = make_engine(cfg.database_url)
        sm = make_sessionmaker(engine)

        async def _mint() -> str:
            async with sm() as s:
                return await create_login_link(s, handle=handle, ttl_s=cfg.login_link_ttl_s)

        code = asyncio.get_event_loop().run_until_complete(_mint())
        base = os.environ.get("HUB_PUBLIC_URL", "https://hub.example.invalid")
        # Print the login URL for the operator to open. The default base is a
        # placeholder that fails loudly (matching the MCP misconfig convention).
        print(f"{base}/console/login?lt={code}")
        return

    print("usage: printer-hub run | mint-login-link <handle>")
    raise SystemExit(2)
