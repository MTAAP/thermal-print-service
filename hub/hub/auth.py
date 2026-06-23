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


async def mint_console_token(session: AsyncSession, printer_id: str) -> str:
    """Mint a CONSOLE-class token for a printer. The plaintext is returned once
    (it rides in the signed session cookie); only the hash is stored, so the
    token stays independently revocable per §9.1. The caller owns the commit so
    a console token can be minted in the same transaction as the action granting
    it, such as one-time login-link consumption."""
    from datetime import UTC, datetime

    from hub.ids import new_id

    plaintext, h = mint_token()
    session.add(Token(id=new_id("tok"), printer_id=printer_id,
                      kind=TokenKind.CONSOLE.value, token_hash=h,
                      revoked_at=None, created_at=datetime.now(UTC)))
    return plaintext


async def revoke_token(session: AsyncSession, plaintext: str) -> bool:
    """Revoke a token by plaintext (used by console logout). Idempotent."""
    from datetime import UTC, datetime
    from typing import cast

    from sqlalchemy import CursorResult, update

    # Async execute() is typed Result[Any] but an UPDATE returns a CursorResult
    # at runtime; cast to read rowcount, matching the jobs/lease.py convention.
    res = cast(
        "CursorResult",
        await session.execute(
            update(Token).where(Token.token_hash == hash_token(plaintext),
                                Token.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC))
        ),
    )
    await session.commit()
    return res.rowcount == 1
