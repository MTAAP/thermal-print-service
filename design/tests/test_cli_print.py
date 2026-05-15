from pathlib import Path

import httpx
import pytest

from tprint_design.cli import main

FIXTURE = Path(__file__).parent / "fixtures" / "html" / "simple.html"


@pytest.mark.slow
def test_print_subcommand_dry_run_posts_to_pi(tmp_path, monkeypatch):
    src = tmp_path / "simple.html"
    src.write_text(FIXTURE.read_text())

    sent: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        sent["url"] = str(request.url)
        sent["content_type"] = request.headers.get("content-type")
        return httpx.Response(200, content=b"\x89PNG", headers={
            "Content-Type": "image/png",
            "X-Estimated-Paper-Mm": "12",
            "X-Renderer-Version": "test",
        })

    monkeypatch.setenv("PRINT_SERVICE_URL", "http://pi.test")
    monkeypatch.setattr(
        "tprint_design.cli._http_client",
        lambda url: httpx.Client(transport=httpx.MockTransport(handler), base_url=url),
    )

    rc = main(["print", str(src), "--dry-run"])
    assert rc == 0
    assert "dry_run=true" in sent["url"]
    assert sent["content_type"] == "image/png"


@pytest.mark.slow
def test_print_refuses_when_lint_errors(tmp_path, monkeypatch):
    src = tmp_path / "bad.html"
    src.write_text(
        "<!doctype html><html><head></head>"
        "<body><img src='https://evil.example/y.png'></body></html>"
    )
    monkeypatch.setenv("PRINT_SERVICE_URL", "http://pi.test")

    posted = {"called": False}

    def handler(request: httpx.Request) -> httpx.Response:
        posted["called"] = True
        return httpx.Response(202, json={"id": "x", "queued_at": "now",
                                          "estimated_paper_mm": 1,
                                          "renderer_version": "1",
                                          "duplicate": False})

    monkeypatch.setattr(
        "tprint_design.cli._http_client",
        lambda url: httpx.Client(transport=httpx.MockTransport(handler), base_url=url),
    )
    rc = main(["print", str(src)])
    assert rc == 1
    assert posted["called"] is False
