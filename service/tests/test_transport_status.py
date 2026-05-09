from printer.transport.status import StatusReader


def test_status_reader_returns_none_for_unsupported_signals():
    r = StatusReader(supports_status=False)
    snap = r.read()
    assert snap.printer_connected is None
    assert snap.paper_present is None
    assert snap.cover_closed is None


def test_status_reader_marks_connected_when_supported():
    r = StatusReader(supports_status=True, _stub_online=True)
    snap = r.read()
    assert snap.printer_connected is True
