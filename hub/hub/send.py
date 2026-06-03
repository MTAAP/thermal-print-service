from __future__ import annotations

import hashlib
import json
import time
from collections import defaultdict, deque
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hub.capabilities import CapabilityError, schema_for_recipient, validate_document
from hub.friends import are_friends, resolve_handles
from hub.ids import new_id
from hub.jobs.wakeup import WakeupRegistry
from hub.models import Job, Printer, SendReceipt
from hub.schemas import SendResp, SendResult

# Process-local sliding-window per-sender limiter (v1 single-instance, §9.3).
_WINDOW: dict[str, deque[float]] = defaultdict(deque)


def _now() -> datetime:
    return datetime.now(UTC)


def _payload_hash(document: dict | None, raw_png_b64: str | None) -> str:
    blob = json.dumps({"d": document, "r": raw_png_b64}, sort_keys=True).encode()
    return hashlib.sha256(blob).hexdigest()


def _throttled(sender_handle: str, limit_per_min: int) -> bool:
    win = _WINDOW[sender_handle]
    cutoff = time.monotonic() - 60.0
    while win and win[0] < cutoff:
        win.popleft()
    if len(win) >= limit_per_min:
        return True
    win.append(time.monotonic())
    return False


async def send_document(
    session: AsyncSession, wake: WakeupRegistry, *, sender_handle: str,
    to: list[str], document: dict | None, idempotency_key: str | None,
    sender_rate_per_min: int, raw_png_b64: str | None = None,
) -> SendResp:
    payload_hash = _payload_hash(document, raw_png_b64)

    # Send-level idempotency (per sender). Same key+payload -> original job ids.
    if idempotency_key:
        prior = (
            await session.execute(
                select(SendReceipt).where(
                    SendReceipt.sender_handle == sender_handle,
                    SendReceipt.idempotency_key == idempotency_key,
                )
            )
        ).scalar_one_or_none()
        if prior is not None and prior.payload_hash == payload_hash:
            return SendResp(results=[
                SendResult(to=h, status="queued", job_id=jid)
                for h, jid in prior.job_ids
            ])

    sender = (
        await session.execute(select(Printer).where(Printer.handle == sender_handle))
    ).scalar_one()
    known, unknown = await resolve_handles(session, to)
    sent_at = _now()
    results: list[SendResult] = []
    created: list[tuple[str, str]] = []

    for handle in to:
        if handle in unknown:
            results.append(SendResult(to=handle, status="recipient_unknown"))
            continue
        recipient_id = known[handle]
        if not await are_friends(session, sender.id, recipient_id):
            results.append(SendResult(to=handle, status="not_friend"))
            continue
        if _throttled(sender_handle, sender_rate_per_min):
            results.append(SendResult(to=handle, status="sender_throttled"))
            continue
        # capability gate (document path only; raw_png is opaque bytes)
        if document is not None:
            schema = await schema_for_recipient(session, recipient_id)
            if schema is not None:
                try:
                    validate_document(schema, document)
                except CapabilityError as exc:
                    results.append(SendResult(to=handle, status="incompatible",
                                              detail=exc.detail))
                    continue
        job_id = new_id("job")
        session.add(Job(
            id=job_id, sender_handle=sender_handle, recipient_id=recipient_id,
            state="queued", kind=("raw" if raw_png_b64 else "document"),
            payload=({"raw_png_b64": raw_png_b64} if raw_png_b64 else {"document": document}),
            sent_at=sent_at, created_at=_now(), lease_expires_at=None, leased_by=None,
        ))
        results.append(SendResult(to=handle, status="queued", job_id=job_id))
        created.append((handle, job_id))

    if idempotency_key and created:
        session.add(SendReceipt(
            sender_handle=sender_handle, idempotency_key=idempotency_key,
            payload_hash=payload_hash, job_ids=created, created_at=_now(),
        ))
    await session.commit()

    # Wake held polls only after the rows are committed.
    for _h, jid in created:
        job = await session.get(Job, jid)
        if job is not None:
            wake.signal(job.recipient_id)
    return SendResp(results=results)
