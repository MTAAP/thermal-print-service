"""Runtime config for the guestbook MCP server.

Everything is an environment variable so the deployment stays out of this
public repo: the recipient handle, the owner's name and the tool name are all
site-specific, and nothing here names a particular person or printer."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class GuestbookConfig:
    # Unset defaults are deliberately unusable rather than plausible: an
    # unconfigured server must fail on its first tool call, not quietly queue
    # paper for whoever happens to hold the handle. Mirrors the .invalid
    # convention the stdio server uses for its URLs.
    hub_url: str = "https://printer-pals-hub.invalid"
    hub_api_token: str = ""
    recipient_handle: str = ""
    owner_name: str = "the owner"
    tool_name: str = "message_owner"

    state_dir: Path = Path("/var/lib/printer-guestbook")
    host: str = "0.0.0.0"
    port: int = 8000
    timeout_s: float = 30.0

    # A guest account is ephemeral, so the per-guest window is a speed bump
    # against one conversation running away, not an identity-based quota. The
    # daily total is the control that actually bounds a roll of paper.
    per_guest_per_hour: int = 10
    global_per_day: int = 100

    max_name_chars: int = 40
    max_message_chars: int = 500
    max_message_lines: int = 20
    # Preformatted sends get their own, larger budget: a drawing needs the room
    # that prose does not, and 40 lines of the small font is about 8cm of paper.
    # max_art_cols is the renderer's column budget for ascii_art at font=small,
    # not a taste call -- wider lines are clipped, not wrapped.
    max_art_chars: int = 1500
    max_art_lines: int = 40
    max_art_cols: int = 52

    # LibreChat substitutes {{LIBRECHAT_USER_ID}} into MCP headers, which is how
    # one chat session is told apart from another.
    guest_id_header: str = "x-guest-id"

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> GuestbookConfig:
        e = env if env is not None else os.environ
        return cls(
            hub_url=e.get("HUB_URL", cls.hub_url).rstrip("/"),
            hub_api_token=e.get("HUB_API_TOKEN", cls.hub_api_token),
            recipient_handle=e.get("GUESTBOOK_RECIPIENT", cls.recipient_handle),
            owner_name=e.get("GUESTBOOK_OWNER_NAME", cls.owner_name),
            tool_name=e.get("GUESTBOOK_TOOL_NAME", cls.tool_name),
            state_dir=Path(e.get("GUESTBOOK_STATE_DIR", str(cls.state_dir))),
            host=e.get("GUESTBOOK_HOST", cls.host),
            port=int(e.get("GUESTBOOK_PORT", cls.port)),
            timeout_s=float(e.get("GUESTBOOK_TIMEOUT_S", cls.timeout_s)),
            per_guest_per_hour=int(
                e.get("GUESTBOOK_PER_GUEST_PER_HOUR", cls.per_guest_per_hour)
            ),
            global_per_day=int(e.get("GUESTBOOK_GLOBAL_PER_DAY", cls.global_per_day)),
            max_name_chars=int(e.get("GUESTBOOK_MAX_NAME_CHARS", cls.max_name_chars)),
            max_message_chars=int(
                e.get("GUESTBOOK_MAX_MESSAGE_CHARS", cls.max_message_chars)
            ),
            max_message_lines=int(
                e.get("GUESTBOOK_MAX_MESSAGE_LINES", cls.max_message_lines)
            ),
            max_art_chars=int(e.get("GUESTBOOK_MAX_ART_CHARS", cls.max_art_chars)),
            max_art_lines=int(e.get("GUESTBOOK_MAX_ART_LINES", cls.max_art_lines)),
            max_art_cols=int(e.get("GUESTBOOK_MAX_ART_COLS", cls.max_art_cols)),
            guest_id_header=e.get("GUESTBOOK_GUEST_ID_HEADER", cls.guest_id_header).lower(),
        )

    def missing(self) -> list[str]:
        """Config the server cannot invent. Checked at boot so a misconfigured
        deployment is loud in the logs instead of at a guest's first message."""
        gaps = []
        if not self.hub_api_token:
            gaps.append("HUB_API_TOKEN")
        if not self.recipient_handle:
            gaps.append("GUESTBOOK_RECIPIENT")
        if self.hub_url.endswith(".invalid"):
            gaps.append("HUB_URL")
        return gaps
