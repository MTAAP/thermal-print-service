"""Tests for `tprint-design status` and the --wait flag."""
import io

import httpx
from PIL import Image

from tprint_design.cli import main


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("1", (576, 100), 1).save(buf, format="PNG")
    return buf.getvalue()


def test_status_prints_snapshot(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("PRINT_SERVICE_URL", "http://printer.test.ts.net")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/jobs/abc123"
        return httpx.Response(200, json={
            "id": "abc123", "status": "queued",
            "sender": "tprint-design", "document_type": "raw",
            "queued_at": "2026-05-17T12:00:00Z", "printed_at": None,
            "paper_used_mm": None, "renderer_version": "0.9.1",
            "reprint_mode": "png_cached", "reprint_url": "/jobs/abc123/reprint",
        })

    monkeypatch.setattr(
        "tprint_design.cli._http_client",
        lambda url: httpx.Client(transport=httpx.MockTransport(handler), base_url=url),
    )
    rc = main(["status", "abc123"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "abc123" in out
    assert "queued" in out


def test_status_allow_public_url_flag(monkeypatch, capsys):
    # A user who sent a job to a public host with `print --allow-public-url`
    # must be able to inspect it with `status --allow-public-url` too.
    monkeypatch.setenv("PRINT_SERVICE_URL", "https://printer.public.example")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "id": "pub1", "status": "printed",
            "sender": "tprint-design", "document_type": "raw",
            "queued_at": "2026-05-17T12:00:00Z",
            "printed_at": "2026-05-17T12:00:05Z",
            "paper_used_mm": 42, "renderer_version": "0.9.1",
            "reprint_mode": "png_cached", "reprint_url": "/jobs/pub1/reprint",
        })

    monkeypatch.setattr(
        "tprint_design.cli._http_client",
        lambda url: httpx.Client(transport=httpx.MockTransport(handler), base_url=url),
    )
    rc = main(["status", "--allow-public-url", "pub1"])
    assert rc == 0
    assert "pub1" in capsys.readouterr().out


def test_status_rejects_public_url_without_flag(monkeypatch, capsys):
    monkeypatch.setenv("PRINT_SERVICE_URL", "https://printer.public.example")
    rc = main(["status", "somejob"])
    assert rc == 2
    assert "--allow-public-url" in capsys.readouterr().err


def test_status_returns_2_for_missing_job(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("PRINT_SERVICE_URL", "http://printer.test.ts.net")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"reason": "job_not_found"})

    monkeypatch.setattr(
        "tprint_design.cli._http_client",
        lambda url: httpx.Client(transport=httpx.MockTransport(handler), base_url=url),
    )
    rc = main(["status", "no-such-job"])
    assert rc == 2
    assert "not found" in capsys.readouterr().err


def test_status_wait_blocks_until_terminal(monkeypatch):
    """First two polls return queued; third returns printed."""
    sleeps: list[float] = []
    monkeypatch.setattr("time.sleep", sleeps.append)
    monkeypatch.setenv("PRINT_SERVICE_URL", "http://printer.test.ts.net")

    state = {"poll": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["poll"] += 1
        if state["poll"] < 3:
            return httpx.Response(200, json={"id": "j", "status": "queued"})
        return httpx.Response(200, json={
            "id": "j", "status": "printed", "paper_used_mm": 33,
        })

    monkeypatch.setattr(
        "tprint_design.cli._http_client",
        lambda url: httpx.Client(transport=httpx.MockTransport(handler), base_url=url),
    )
    rc = main(["status", "j", "--wait"])
    assert rc == 0
    assert state["poll"] == 3
    # Two sleeps between three polls.
    assert len(sleeps) == 2


def test_status_wait_returns_1_for_non_printed_terminal(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    monkeypatch.setenv("PRINT_SERVICE_URL", "http://printer.test.ts.net")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": "j", "status": "expired"})

    monkeypatch.setattr(
        "tprint_design.cli._http_client",
        lambda url: httpx.Client(transport=httpx.MockTransport(handler), base_url=url),
    )
    rc = main(["status", "j", "--wait"])
    # expired counts as a terminal but non-success exit.
    assert rc == 1


def test_send_wait_polls_after_202(tmp_path, monkeypatch):
    """--wait on send must POST first, then poll the returned id."""
    monkeypatch.setattr("time.sleep", lambda s: None)
    monkeypatch.setenv("PRINT_SERVICE_URL", "http://printer.test.ts.net")

    png = tmp_path / "design.png"
    png.write_bytes(_png())
    state = {"post": False, "polls": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/print/raw":
            state["post"] = True
            return httpx.Response(202, json={
                "id": "wait-j", "queued_at": "t",
                "estimated_paper_mm": 10, "renderer_version": "1.0",
                "duplicate": False,
            })
        if request.method == "GET" and request.url.path == "/jobs/wait-j":
            state["polls"] += 1
            if state["polls"] < 2:
                return httpx.Response(200, json={"id": "wait-j", "status": "queued"})
            return httpx.Response(200, json={
                "id": "wait-j", "status": "printed", "paper_used_mm": 10,
            })
        return httpx.Response(404)

    monkeypatch.setattr(
        "tprint_design.cli._http_client",
        lambda url: httpx.Client(transport=httpx.MockTransport(handler), base_url=url),
    )

    rc = main(["send", str(png), "--wait"])
    assert rc == 0
    assert state["post"] is True
    assert state["polls"] == 2


def test_status_wait_times_out_returns_2(monkeypatch, capsys):
    """If the job never reaches a terminal state within the timeout
    budget, exit 2 with a clear message."""
    monkeypatch.setattr("time.sleep", lambda s: None)

    # Pump monotonic time forward so the deadline is reached after a few
    # polls without actually waiting.
    fake_now = {"t": 0.0}

    def fake_monotonic():
        fake_now["t"] += 60.0
        return fake_now["t"]

    monkeypatch.setattr("time.monotonic", fake_monotonic)
    monkeypatch.setenv("PRINT_SERVICE_URL", "http://printer.test.ts.net")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": "j", "status": "queued"})

    monkeypatch.setattr(
        "tprint_design.cli._http_client",
        lambda url: httpx.Client(transport=httpx.MockTransport(handler), base_url=url),
    )
    rc = main(["status", "j", "--wait"])
    assert rc == 2
    assert "timed out" in capsys.readouterr().err
