from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from urllib.parse import quote

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hub.models import Printer
from hub.presence import Presence

AlertSender = Callable[[str, str], Awaitable[None]]

logger = logging.getLogger("hub.alerts")


class OfflineAlertState:
    def __init__(self) -> None:
        self._alerted: set[str] = set()

    def is_alerted(self, printer_id: str) -> bool:
        return printer_id in self._alerted

    def mark_alerted(self, printer_id: str) -> None:
        self._alerted.add(printer_id)

    def mark_recovered(self, printer_id: str) -> None:
        self._alerted.discard(printer_id)

    def prune(self, active_printer_ids: set[str]) -> None:
        self._alerted.intersection_update(active_printer_ids)


async def send_ntfy(topic: str, message: str) -> None:
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            f"https://ntfy.sh/{quote(topic, safe='')}",
            content=message,
        )
        response.raise_for_status()


async def sweep_offline_alerts(
    session: AsyncSession,
    *,
    online: Presence,
    alert_after_s: int | float,
    state: OfflineAlertState,
    send: AlertSender,
    current_time: datetime | None = None,
) -> None:
    current = current_time or datetime.now(UTC)
    printers = (
        await session.execute(
            select(Printer).where(Printer.alert_ntfy_topic.is_not(None))
        )
    ).scalars().all()
    active_ids = {
        printer.id for printer in printers if (printer.alert_ntfy_topic or "").strip()
    }
    state.prune(active_ids)

    for printer in printers:
        topic = (printer.alert_ntfy_topic or "").strip()
        if not topic:
            state.mark_recovered(printer.id)
            continue

        if printer.id in online:
            if state.is_alerted(printer.id):
                sent = await _try_send(
                    printer.id,
                    topic,
                    f"{printer.display_name} ({printer.handle}) is back online.",
                    send,
                )
                if sent:
                    state.mark_recovered(printer.id)
            continue

        if printer.last_seen_at is None:
            continue

        last_seen_at = _aware(printer.last_seen_at)
        recently_seen = current - last_seen_at <= timedelta(seconds=alert_after_s)

        if state.is_alerted(printer.id):
            # A short poll can refresh last_seen_at and release from `online`
            # before this sweep runs, so the printer never gets caught by the
            # "if printer.id in online" branch above. Treat a fresh
            # last_seen_at as recovery here too, or an alerted printer that
            # only ever reconnects between sweep ticks never recovers.
            if recently_seen:
                sent = await _try_send(
                    printer.id,
                    topic,
                    f"{printer.display_name} ({printer.handle}) is back online.",
                    send,
                )
                if sent:
                    state.mark_recovered(printer.id)
            continue

        if recently_seen:
            continue

        sent = await _try_send(
            printer.id,
            topic,
            (
                f"{printer.display_name} ({printer.handle}) is offline since "
                f"{last_seen_at.isoformat()}."
            ),
            send,
        )
        if sent:
            state.mark_alerted(printer.id)


async def _try_send(
    printer_id: str,
    topic: str,
    message: str,
    send: AlertSender,
) -> bool:
    try:
        await send(topic, message)
        return True
    except Exception:
        logger.exception(
            "offline alert post failed for printer %s; retrying next sweep",
            printer_id,
        )
        return False


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value
