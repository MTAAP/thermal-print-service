from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import cast

from sqlalchemy import CursorResult, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from hub.auth import hash_token, mint_console_token
from hub.ids import new_invite_code
from hub.models import LoginLink, Printer


class LoginLinkError(Exception):
    pass


def _now() -> datetime:
    return datetime.now(UTC)


def login_url(public_url: str, code: str) -> str:
    """Build the console login URL embedding a one-time code. Single source of
    truth for both the `mint-login-link` CLI and the device-facing /login-links
    API, so the URL shape never drifts between them."""
    return f"{public_url.rstrip('/')}/console/login?lt={code}"


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
    code_hash = hash_token(code)
    link = (
        await session.execute(select(LoginLink).where(LoginLink.code_hash == code_hash))
    ).scalar_one_or_none()
    if link is None:
        raise LoginLinkError("unknown login link")
    # SQLite (aiosqlite) drops tzinfo on read-back, and consume runs in a
    # different session than create (real flow: a fresh console request), so
    # expires_at comes back naive. Normalize before comparing to tz-aware _now().
    # No-op on Postgres timestamptz. Mirrors the redeem_invite workaround.
    expires_at = link.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if expires_at <= _now():
        raise LoginLinkError("login link expired")
    # Atomic single-use claim, and the SOLE used-check (there is deliberately no
    # earlier `if link.used_at is not None` guard -- that would be a second,
    # redundant implementation of the same check, and a check-then-act race). Two
    # console requests racing on the same printed link (a double-clicked QR, a
    # retry) both pass the SELECT above, but only one UPDATE can flip used_at from
    # NULL: the winner matches one row, the loser matches zero and is rejected.
    # Async execute() is typed Result[Any] but an UPDATE returns a CursorResult at
    # runtime; cast to read rowcount, matching the jobs/lease.py + auth.py convention.
    result = cast(
        "CursorResult",
        await session.execute(
            update(LoginLink)
            .where(LoginLink.code_hash == code_hash, LoginLink.used_at.is_(None))
            .values(used_at=_now())
        ),
    )
    if result.rowcount != 1:
        raise LoginLinkError("login link already used")
    token = await mint_console_token(session, link.printer_id)
    await session.commit()
    return token
