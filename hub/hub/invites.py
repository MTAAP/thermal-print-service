from __future__ import annotations

from datetime import UTC, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hub.auth import TokenKind, hash_token, mint_token
from hub.ids import new_id, new_invite_code
from hub.models import Friendship, Invite, Printer, Token
from hub.schemas import RegisterResp


class InviteError(Exception):
    pass


def _now():
    from datetime import datetime
    return datetime.now(UTC)


async def create_invite(
    session: AsyncSession, *, issuer_printer_id: str | None, ttl_s: int
) -> str:
    code = new_invite_code()
    session.add(Invite(
        id=new_id("inv"),
        code_hash=hash_token(code),
        issuer_printer_id=issuer_printer_id,
        redeemed_by=None,
        created_at=_now(),
        expires_at=_now() + timedelta(seconds=ttl_s),
    ))
    await session.commit()
    return code


async def redeem_invite(
    session: AsyncSession, *, code: str, handle: str, display_name: str
) -> RegisterResp:
    inv = (
        await session.execute(select(Invite).where(Invite.code_hash == hash_token(code)))
    ).scalar_one_or_none()
    if inv is None:
        raise InviteError("unknown invite code")
    if inv.redeemed_by is not None:
        raise InviteError("invite already redeemed")
    # SQLite (aiosqlite) drops tzinfo on read-back; normalize so the comparison
    # against tz-aware _now() works. No-op on Postgres timestamptz.
    expires_at = inv.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if expires_at <= _now():
        raise InviteError("invite expired")

    exists = (
        await session.execute(select(Printer).where(Printer.handle == handle))
    ).scalar_one_or_none()
    if exists is not None:
        raise InviteError("handle already taken")

    printer = Printer(id=new_id("prn"), handle=handle, display_name=display_name,
                      renderer_version=None, last_seen_at=None, created_at=_now())
    session.add(printer)

    dev_plain, dev_hash = mint_token()
    api_plain, api_hash = mint_token()
    session.add(Token(id=new_id("tok"), printer_id=printer.id, kind=TokenKind.DEVICE.value,
                      token_hash=dev_hash, revoked_at=None, created_at=_now()))
    session.add(Token(id=new_id("tok"), printer_id=printer.id, kind=TokenKind.API.value,
                      token_hash=api_hash, revoked_at=None, created_at=_now()))

    inviter_handle: str | None = None
    if inv.issuer_printer_id is not None:
        issuer = (
            await session.execute(
                select(Printer).where(Printer.id == inv.issuer_printer_id)
            )
        ).scalar_one()
        inviter_handle = issuer.handle
        # Mutual friendship: two ordered rows.
        session.add(Friendship(owner_id=issuer.id, friend_id=printer.id,
                               origin_invite_id=inv.id, created_at=_now()))
        session.add(Friendship(owner_id=printer.id, friend_id=issuer.id,
                               origin_invite_id=inv.id, created_at=_now()))

    inv.redeemed_by = printer.id
    await session.commit()
    return RegisterResp(
        printer_id=printer.id, handle=printer.handle,
        device_token=dev_plain, api_token=api_plain, inviter_handle=inviter_handle,
    )
