from __future__ import annotations

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from hub.auth import TokenKind, authenticate
from hub.models import Printer

# The session cookie carries the CONSOLE token plaintext under this key.
SESSION_TOKEN_KEY = "console_token"


class NotAuthenticated(Exception):
    """Raised when a web route has no valid console session. Routes catch this
    and redirect to the login landing -- there is intentionally NO bearer-header
    fallback, so device/api tokens cannot reach console views (spec §9.1)."""


async def console_printer(request: Request, session: AsyncSession) -> Printer:
    """Resolve the current console session to a Printer using ONLY the signed
    session cookie. The Authorization header is never consulted here."""
    token = request.session.get(SESSION_TOKEN_KEY)
    if not token:
        raise NotAuthenticated
    try:
        return await authenticate(session, token, required=TokenKind.CONSOLE)
    except PermissionError as exc:
        # Token revoked, wrong kind, or unknown -> treat as no session.
        raise NotAuthenticated from exc
