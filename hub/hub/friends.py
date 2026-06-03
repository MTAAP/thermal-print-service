from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from hub.models import Friendship, Printer
from hub.schemas import FriendOut


async def are_friends(session: AsyncSession, owner_id: str, friend_id: str) -> bool:
    row = (
        await session.execute(
            select(Friendship.id).where(
                Friendship.owner_id == owner_id, Friendship.friend_id == friend_id
            )
        )
    ).first()
    return row is not None


async def list_friends(
    session: AsyncSession, owner_id: str, *, online_ids: set[str]
) -> list[FriendOut]:
    rows = (
        await session.execute(
            select(Printer, Friendship.origin_invite_id)
            .join(Friendship, Friendship.friend_id == Printer.id)
            .where(Friendship.owner_id == owner_id)
            .order_by(Printer.handle)
        )
    ).all()
    return [
        FriendOut(
            handle=p.handle, display_name=p.display_name,
            renderer_version=p.renderer_version, online=p.id in online_ids,
            via_invite_id=origin_invite_id,
        )
        for p, origin_invite_id in rows
    ]


async def unfriend(session: AsyncSession, a_id: str, b_id: str) -> None:
    await session.execute(
        delete(Friendship).where(
            ((Friendship.owner_id == a_id) & (Friendship.friend_id == b_id))
            | ((Friendship.owner_id == b_id) & (Friendship.friend_id == a_id))
        )
    )
    await session.commit()


async def resolve_handles(
    session: AsyncSession, handles: list[str]
) -> tuple[dict[str, str], list[str]]:
    """Return ({handle: printer_id} for known}, [unknown handles])."""
    rows = (
        await session.execute(select(Printer).where(Printer.handle.in_(handles)))
    ).scalars().all()
    known = {p.handle: p.id for p in rows}
    unknown = [h for h in handles if h not in known]
    return known, unknown
