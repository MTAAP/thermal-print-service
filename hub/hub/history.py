from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hub.models import Job, Printer


@dataclass(frozen=True)
class HistoryRow:
    job_id: str
    # the OTHER party's handle (recipient handle for sent; sender handle for received)
    peer: str
    status: str        # the Job.state value (see jobs/store.STATES)
    sent_at: str       # ISO 8601
    kind: str          # 'document' | 'raw'


@dataclass(frozen=True)
class History:
    sent: list[HistoryRow]
    received: list[HistoryRow]


async def list_jobs(session: AsyncSession, *, owner_id: str, handle: str) -> History:
    """Sent + received jobs for one printer. Sent = jobs whose sender_handle is
    this printer's handle; received = jobs whose recipient_id is this printer.
    Newest first. The sent side joins recipient_id -> handle so the view shows a
    handle as the peer, never an opaque printer id."""
    sent_rows = (
        await session.execute(
            select(Job, Printer.handle)
            .join(Printer, Printer.id == Job.recipient_id)
            .where(Job.sender_handle == handle)
            .order_by(Job.created_at.desc())
        )
    ).all()
    received_rows = (
        await session.execute(
            select(Job).where(Job.recipient_id == owner_id).order_by(Job.created_at.desc())
        )
    ).scalars().all()
    sent = [
        HistoryRow(job_id=j.id, peer=peer_handle, status=j.state,
                   sent_at=j.sent_at.isoformat(), kind=j.kind)
        for (j, peer_handle) in sent_rows
    ]
    received = [
        HistoryRow(job_id=j.id, peer=j.sender_handle, status=j.state,
                   sent_at=j.sent_at.isoformat(), kind=j.kind)
        for j in received_rows
    ]
    return History(sent=sent, received=received)
