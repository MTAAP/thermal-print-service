from printer.health import HealthCollector
from printer.transport.status import StatusReader


def test_collector_reports_clock_sync_and_uptime(monkeypatch):
    monkeypatch.setattr("printer.health._read_clock_synchronized", lambda: True)
    reader = StatusReader(supports_status=False)
    c = HealthCollector(status_reader=reader, queue_depth=lambda: 3,
                        last_print_at=lambda: "2026-05-09T06:30:14Z",
                        last_error=lambda: "printer offline",
                        oldest_pending_age_s=lambda: 42,
                        process_started_at=1_000_000.0,
                        clock_now=lambda: 1_000_500.0)
    h = c.snapshot()
    assert h.printer_connected is None
    assert h.paper_present is None
    assert h.cover_closed is None
    assert h.clock_synchronized is True
    assert h.queue_depth == 3
    assert h.last_print_at == "2026-05-09T06:30:14Z"
    assert h.last_error == "printer offline"
    assert h.oldest_pending_age_s == 42
    assert h.uptime_s == 500
