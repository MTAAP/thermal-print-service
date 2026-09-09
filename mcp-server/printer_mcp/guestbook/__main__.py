from __future__ import annotations

import logging

import uvicorn

from printer_mcp.guestbook.config import GuestbookConfig
from printer_mcp.guestbook.server import build_app


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    cfg = GuestbookConfig.from_env()
    gaps = cfg.missing()
    if gaps:
        # Refuse to start rather than accept a tool call we cannot deliver. A
        # server that boots and then fails every send looks healthy to the chat
        # host and silently swallows guests' messages.
        raise SystemExit(f"guestbook: missing required config: {', '.join(gaps)}")
    app, _aclose = build_app(cfg)
    logging.getLogger("printer.guestbook").info(
        "guestbook: tool=%s recipient=%s caps=%d/guest/hour %d/day",
        cfg.tool_name, cfg.recipient_handle, cfg.per_guest_per_hour, cfg.global_per_day,
    )
    uvicorn.run(app, host=cfg.host, port=cfg.port, log_level="info")


if __name__ == "__main__":
    main()
