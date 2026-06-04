from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hub.auth import hash_token, mint_console_token
from hub.ids import new_invite_code
from hub.models import LoginLink, Printer


class LoginLinkError(Exception):
    pass


def _now() -> datetime:
    return datetime.now(UTC)


async def create_login_link(session: AsyncSession, *, handle: str, ttl_s: int) -> str:
    """Mint a one-time login link for an existing printer handle. Returns the
    plaintext code (embedded in the login URL); only its hash is stored."""
    printer = (
        await session.execute(select(Printer).where(Printer.handle == handle))
    ).scalar_one_or_none()
    if printer is None:
        raise LoginLinkError(f"unknown handle: {handle}")
    code = new_invite_code()
    session.add(LoginLink(
        code_hash=hash_token(code), printer_id=printer.id,
        created_at=_now(), expires_at=_now() + timedelta(seconds=ttl_s), used_at=None,
    ))
    await session.commit()
    return code


async def consume_login_link(session: AsyncSession, *, code: str) -> str:
    """Validate + single-use-consume a login link, returning a fresh CONSOLE
    token plaintext for the link's printer."""
    link = (
        await session.execute(select(LoginLink).where(LoginLink.code_hash == hash_token(code)))
    ).scalar_one_or_none()
    if link is None:
        raise LoginLinkError("unknown login link")
    if link.used_at is not None:
        raise LoginLinkError("login link already used")
    # SQLite (aiosqlite) drops tzinfo on read-back, and consume runs in a
    # different session than create (real flow: a fresh console request), so
    # expires_at comes back naive. Normalize before comparing to tz-aware _now().
    # No-op on Postgres timestamptz. Mirrors the redeem_invite workaround.
    expires_at = link.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if expires_at <= _now():
        raise LoginLinkError("login link expired")
    link.used_at = _now()
    token = await mint_console_token(session, link.printer_id)
    await session.commit()
    return token
