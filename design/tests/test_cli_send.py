"""Tests for `tprint-design send <png>` — compile-free post path."""
import io

import httpx
import pytest
from PIL import Image

from tprint_design.cli import main


def _png_at_width(width: int) -> bytes:
    buf = io.BytesIO()
    Image.new("1", (width, 100), 1).save(buf, format="PNG")
    return buf.getvalue()


def test_send_posts_png_without_recompiling(tmp_path, monkeypatch):
    png = tmp_path / "design.png"
    png.write_bytes(_png_at_width(576))
    monkeypatch.setenv("PRINT_SERVICE_URL", "http://printer.test.ts.net")

    sent: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        sent["content_type"] = request.headers.get("content-type")
        sent["idempotency_key"] = request.headers.get("x-idempotency-key")
        sent["body_len"] = len(request.content)
        return httpx.Response(202, json={
            "id": "ok", "queued_at": "2026-01-01T00:00:00Z",
            "estimated_paper_mm": 12, "renderer_version": "1.0",
            "duplicate": False,
        })

    monkeypatch.setattr(
        "tprint_design.cli._http_client",
        lambda url: httpx.Client(transport=httpx.MockTransport(handler), base_url=url),
    )

    rc = main(["send", str(png)])
    assert rc == 0
    assert sent["content_type"] == "image/png"
    # Auto-derived idempotency key when caller doesn't pass one.
    assert sent["idempotency_key"] is not None
    assert len(sent["idempotency_key"]) == 16


def test_send_rejects_wrong_width_before_posting(tmp_path, monkeypatch, capsys):
    png = tmp_path / "wrong.png"
    png.write_bytes(_png_at_width(500))
    monkeypatch.setenv("PRINT_SERVICE_URL", "http://printer.test.ts.net")

    posted = {"called": False}

    def handler(request: httpx.Request) -> httpx.Response:
        posted["called"] = True
        return httpx.Response(202, json={})

    monkeypatch.setattr(
        "tprint_design.cli._http_client",
        lambda url: httpx.Client(transport=httpx.MockTransport(handler), base_url=url),
    )

    rc = main(["send", str(png)])
    assert rc == 2
    assert posted["called"] is False
    err = capsys.readouterr().err
    assert "500px wide" in err
    assert "576px" in err


def test_send_with_explicit_key_overrides_auto(tmp_path, monkeypatch):
    png = tmp_path / "design.png"
    png.write_bytes(_png_at_width(576))
    monkeypatch.setenv("PRINT_SERVICE_URL", "http://printer.test.ts.net")

    sent: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        sent["idempotency_key"] = request.headers.get("x-idempotency-key")
        return httpx.Response(202, json={
            "id": "ok", "queued_at": "2026-01-01T00:00:00Z",
            "estimated_paper_mm": 12, "renderer_version": "1.0",
            "duplicate": False,
        })

    monkeypatch.setattr(
        "tprint_design.cli._http_client",
        lambda url: httpx.Client(transport=httpx.MockTransport(handler), base_url=url),
    )

    rc = main(["send", str(png), "--idempotency-key", "manual-key-2026-05-17"])
    assert rc == 0
    assert sent["idempotency_key"] == "manual-key-2026-05-17"


def test_send_dry_run_does_not_print(tmp_path, monkeypatch):
    png = tmp_path / "design.png"
    png.write_bytes(_png_at_width(576))
    monkeypatch.setenv("PRINT_SERVICE_URL", "http://printer.test.ts.net")

    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(200, content=b"\x89PNG", headers={
            "Content-Type": "image/png",
            "X-Estimated-Paper-Mm": "10",
            "X-Renderer-Version": "1.0",
        })

    monkeypatch.setattr(
        "tprint_design.cli._http_client",
        lambda url: httpx.Client(transport=httpx.MockTransport(handler), base_url=url),
    )

    rc = main(["send", str(png), "--dry-run"])
    assert rc == 0
    assert "dry_run=true" in seen["url"]


def test_send_missing_png_returns_2(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("PRINT_SERVICE_URL", "http://printer.test.ts.net")
    rc = main(["send", str(tmp_path / "nope.png")])
    assert rc == 2
    assert "png not found" in capsys.readouterr().err


@pytest.mark.parametrize("subcmd", ["print", "send"])
def test_auto_idempotency_key_is_content_addressed(subcmd, tmp_path, monkeypatch):
    """Two distinct PNG payloads must auto-derive distinct keys; identical
    bytes must derive identical keys (verified at the helper level in
    test_client.py; here we assert the CLI threads the helper through)."""
    keys_seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        keys_seen.append(request.headers.get("x-idempotency-key") or "")
        return httpx.Response(202, json={
            "id": "ok", "queued_at": "t", "estimated_paper_mm": 1,
            "renderer_version": "1.0", "duplicate": False,
        })

    monkeypatch.setenv("PRINT_SERVICE_URL", "http://printer.test.ts.net")
    monkeypatch.setattr(
        "tprint_design.cli._http_client",
        lambda url: httpx.Client(transport=httpx.MockTransport(handler), base_url=url),
    )

    if subcmd == "send":
        png_a = tmp_path / "a.png"
        png_b = tmp_path / "b.png"
        png_a.write_bytes(_png_at_width(576))
        # Different height -> different bytes
        buf = io.BytesIO()
        Image.new("1", (576, 200), 1).save(buf, format="PNG")
        png_b.write_bytes(buf.getvalue())
        assert main(["send", str(png_a)]) == 0
        assert main(["send", str(png_b)]) == 0
        # Same payload again must reuse the same key
        assert main(["send", str(png_a)]) == 0
        assert keys_seen[0] != keys_seen[1]
        assert keys_seen[0] == keys_seen[2]
