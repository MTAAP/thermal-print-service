from pathlib import Path

import httpx
import pytest

from tprint_design.cli import main, validate_print_service_url

FIXTURE = Path(__file__).parent / "fixtures" / "html" / "simple.html"


@pytest.mark.parametrize(
    "url",
    [
        "http://printer.tailfoo.ts.net:8000",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://10.0.0.1:8000",
        "http://192.168.1.42",
        "http://172.20.0.5:8000",
        "https://pi.house.ts.net",
        # Tailscale CGNAT (100.64.0.0/10) node IPs — reached by address
        # rather than MagicDNS name.
        "http://100.64.0.1:8000",
        "https://100.127.255.254",
    ],
)
def test_validate_url_accepts_trusted_targets(url):
    assert validate_print_service_url(url, allow_public=False) is None


@pytest.mark.parametrize(
    "url",
    [
        "http://100.63.255.255",   # just below the CGNAT block
        "http://100.128.0.0",      # just above the CGNAT block
    ],
)
def test_validate_url_rejects_addresses_adjacent_to_cgnat(url):
    # Guard against an over-broad allowlist: only 100.64.0.0/10 is tailnet
    # shared space; neighbouring public addresses must still be rejected.
    assert validate_print_service_url(url, allow_public=False) is not None


@pytest.mark.parametrize(
    "url",
    [
        "http://printer.example.com",
        "https://attacker.com",
        "http://8.8.8.8",
        "https://api.openai.com",
    ],
)
def test_validate_url_rejects_public_targets(url):
    err = validate_print_service_url(url, allow_public=False)
    assert err is not None
    assert "PRINT_SERVICE_URL" in err


def test_validate_url_rejects_non_http_scheme():
    err = validate_print_service_url("file:///tmp/x", allow_public=False)
    assert err is not None
    assert "scheme" in err


def test_validate_url_allow_public_overrides():
    assert validate_print_service_url(
        "https://attacker.com", allow_public=True
    ) is None


@pytest.mark.slow
def test_print_rejects_public_url_by_default(tmp_path, monkeypatch, capsys):
    src = tmp_path / "simple.html"
    src.write_text(FIXTURE.read_text())
    monkeypatch.setenv("PRINT_SERVICE_URL", "https://attacker.example")

    rc = main(["print", str(src)])
    assert rc == 2
    err = capsys.readouterr().err
    assert "PRINT_SERVICE_URL" in err
    assert "--allow-public-url" in err


@pytest.mark.slow
def test_print_accepts_public_url_with_env_opt_out(tmp_path, monkeypatch):
    src = tmp_path / "simple.html"
    src.write_text(FIXTURE.read_text())
    monkeypatch.setenv("PRINT_SERVICE_URL", "https://attacker.example")
    monkeypatch.setenv("PRINT_SERVICE_ALLOW_PUBLIC_URL", "1")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"\x89PNG", headers={
            "Content-Type": "image/png",
            "X-Estimated-Paper-Mm": "10",
        })

    monkeypatch.setattr(
        "tprint_design.cli._http_client",
        lambda url: httpx.Client(transport=httpx.MockTransport(handler), base_url=url),
    )
    rc = main(["print", str(src), "--dry-run"])
    assert rc == 0


@pytest.mark.slow
def test_print_catches_network_error_as_exit_2(tmp_path, monkeypatch, capsys):
    src = tmp_path / "simple.html"
    src.write_text(FIXTURE.read_text())
    monkeypatch.setenv("PRINT_SERVICE_URL", "http://printer.test.ts.net")

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("simulated DNS / network failure")

    monkeypatch.setattr(
        "tprint_design.cli._http_client",
        lambda url: httpx.Client(transport=httpx.MockTransport(handler), base_url=url),
    )
    rc = main(["print", str(src)])
    assert rc == 2
    err = capsys.readouterr().err
    assert "network error" in err
