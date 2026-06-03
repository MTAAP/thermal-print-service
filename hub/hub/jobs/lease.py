from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import cast

from sqlalchemy import CursorResult, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from hub.jobs.store import RELAY_REPORTABLE
from hub.models import Job


def _now() -> datetime:
    return datetime.now(UTC)


async def lease_next(
    session: AsyncSession, *, recipient_id: str, poll_id: str, visibility_s: float
) -> Job | None:
    """Atomically lease the oldest queued job for a recipient. The conditional
    UPDATE ... WHERE state='queued' is the real anti-double-delivery guard and
    is portable across SQLite (tests) and Postgres (prod)."""
    while True:
        candidate = (
            await session.execute(
                select(Job.id).where(Job.recipient_id == recipient_id, Job.state == "queued")
                .order_by(Job.created_at).limit(1)
            )
        ).scalar_one_or_none()
        if candidate is None:
            return None
        res = cast(
            "CursorResult",
            await session.execute(
                update(Job)
                .where(Job.id == candidate, Job.state == "queued")
                .values(state="leased", leased_by=poll_id,
                        lease_expires_at=_now() + timedelta(seconds=visibility_s))
            ),
        )
        await session.commit()
        if res.rowcount == 1:
            return await session.get(Job, candidate)
        # lost the race to another poll; try the next queued job


async def ack_delivered(session: AsyncSession, *, job_id: str, poll_id: str) -> bool:
    res = cast(
        "CursorResult",
        await session.execute(
            update(Job).where(Job.id == job_id, Job.state == "leased")
            .values(state="delivered", lease_expires_at=None)
        ),
    )
    await session.commit()
    return res.rowcount == 1


async def report_terminal(session: AsyncSession, *, job_id: str, status: str) -> bool:
    if status not in RELAY_REPORTABLE:
        raise ValueError(f"not a relay-reportable status: {status}")
    res = cast(
        "CursorResult",
        await session.execute(
            update(Job).where(Job.id == job_id, Job.state.in_(["leased", "delivered"]))
            .values(state=status)
        ),
    )
    await session.commit()
    return res.rowcount == 1


async def sweep(session: AsyncSession, *, job_ttl_s: int) -> dict[str, int]:
    """Reclaim expired leases -> queued; expire never-delivered jobs -> relay_expired."""
    reclaimed = cast(
        "CursorResult",
        await session.execute(
            update(Job).where(Job.state == "leased", Job.lease_expires_at < _now())
            .values(state="queued", leased_by=None, lease_expires_at=None)
        ),
    )
    cutoff = _now() - timedelta(seconds=job_ttl_s)
    expired = cast(
        "CursorResult",
        await session.execute(
            update(Job).where(Job.state == "queued", Job.created_at < cutoff)
            .values(state="relay_expired")
        ),
    )
    await session.commit()
    return {"reclaimed": reclaimed.rowcount, "relay_expired": expired.rowcount}
