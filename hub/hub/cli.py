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
    else:
        print("usage: printer-hub run")
        raise SystemExit(2)
