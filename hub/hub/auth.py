from __future__ import annotations

import enum
import hashlib

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hub.ids import new_token
from hub.models import Printer, Token


class TokenKind(enum.Enum):
    DEVICE = "device"   # Pi <-> hub: poll, ack, status, capabilities
    CONSOLE = "console"  # human web session: manage friends/invites + send
    API = "api"         # MCP / curl: send + list_friends


def hash_token(plaintext: str) -> str:
    # Tokens are high-entropy random secrets, not user passwords, so a fast
    # one-way hash (SHA-256) is appropriate — no need for a slow KDF.
    return hashlib.sha256(plaintext.encode()).hexdigest()


def mint_token() -> tuple[str, str]:
    plaintext = new_token()
    return plaintext, hash_token(plaintext)


async def authenticate(
    session: AsyncSession, plaintext: str, *, required: TokenKind
) -> Printer:
    h = hash_token(plaintext)
    row = (
        await session.execute(select(Token).where(Token.token_hash == h))
    ).scalar_one_or_none()
    if row is None or row.revoked_at is not None or row.kind != required.value:
        raise PermissionError("invalid or insufficiently-scoped token")
    printer = (
        await session.execute(select(Printer).where(Printer.id == row.printer_id))
    ).scalar_one_or_none()
    if printer is None:
        raise PermissionError("token has no printer")
    return printer
