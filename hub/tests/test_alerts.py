from __future__ import annotations

from datetime import timedelta

from hub.models import Printer
from hub.presence import Presence
from tests.conftest import now


class Recorder:
    def __init__(self) -> None:
        self.posts: list[tuple[str, str]] = []

    async def send(self, topic: str, message: str) -> None:
        self.posts.append((topic, message))


async def _printer(
    sm,
    *,
    printer_id: str = "prn_bob",
    topic: str | None = "example-alert-topic",
    last_seen_delta: timedelta | None = timedelta(seconds=301),
) -> None:
    async with sm() as s:
        s.add(
            Printer(
                id=printer_id,
                handle="bob",
                display_name="Bob",
                renderer_version=None,
                last_seen_at=now() - last_seen_delta if last_seen_delta is not None else None,
                alert_ntfy_topic=topic,
                created_at=now(),
            )
        )
        await s.commit()


async def test_offline_transition_sends_once_then_suppresses_duplicates(sm):
    from hub.alerts import OfflineAlertState, sweep_offline_alerts

    await _printer(sm)
    recorder = Recorder()
    state = OfflineAlertState()

    async with sm() as s:
        await sweep_offline_alerts(
            s,
            online=Presence(),
            alert_after_s=300,
            state=state,
            send=recorder.send,
        )
        await sweep_offline_alerts(
            s,
            online=Presence(),
            alert_after_s=300,
            state=state,
            send=recorder.send,
        )

    assert len(recorder.posts) == 1
    assert recorder.posts[0][0] == "example-alert-topic"
    assert "Bob" in recorder.posts[0][1]
    assert "offline" in recorder.posts[0][1]


async def test_recovery_sends_once_after_offline_alert(sm):
    from hub.alerts import OfflineAlertState, sweep_offline_alerts

    await _printer(sm)
    recorder = Recorder()
    state = OfflineAlertState()
    online = Presence()

    async with sm() as s:
        await sweep_offline_alerts(
            s,
            online=online,
            alert_after_s=300,
            state=state,
            send=recorder.send,
        )
        online.add("prn_bob")
        await sweep_offline_alerts(
            s,
            online=online,
            alert_after_s=300,
            state=state,
            send=recorder.send,
        )
        await sweep_offline_alerts(
            s,
            online=online,
            alert_after_s=300,
            state=state,
            send=recorder.send,
        )

    assert len(recorder.posts) == 2
    assert "offline" in recorder.posts[0][1]
    assert "back online" in recorder.posts[1][1]


async def test_flapping_inside_threshold_does_not_alert(sm):
    from hub.alerts import OfflineAlertState, sweep_offline_alerts

    await _printer(sm, last_seen_delta=timedelta(seconds=119))
    recorder = Recorder()

    async with sm() as s:
        await sweep_offline_alerts(
            s,
            online=Presence(),
            alert_after_s=300,
            state=OfflineAlertState(),
            send=recorder.send,
        )

    assert recorder.posts == []


async def test_printer_without_topic_is_skipped(sm):
    from hub.alerts import OfflineAlertState, sweep_offline_alerts

    await _printer(sm, topic=None)
    recorder = Recorder()

    async with sm() as s:
        await sweep_offline_alerts(
            s,
            online=Presence(),
            alert_after_s=300,
            state=OfflineAlertState(),
            send=recorder.send,
        )

    assert recorder.posts == []


async def test_ntfy_failure_is_logged_and_retried_next_sweep(sm, caplog):
    from hub.alerts import OfflineAlertState, sweep_offline_alerts

    await _printer(sm)
    recorder = Recorder()
    state = OfflineAlertState()
    attempts = 0

    async def flaky_send(topic: str, message: str) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("ntfy unavailable")
        await recorder.send(topic, message)

    async with sm() as s:
        await sweep_offline_alerts(
            s,
            online=Presence(),
            alert_after_s=300,
            state=state,
            send=flaky_send,
        )
        await sweep_offline_alerts(
            s,
            online=Presence(),
            alert_after_s=300,
            state=state,
            send=flaky_send,
        )

    assert attempts == 2
    assert len(recorder.posts) == 1
    assert "offline alert post failed" in caplog.text
