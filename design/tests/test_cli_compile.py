import json
from pathlib import Path

import pytest

from tprint_design.cli import main

FIXTURE = Path(__file__).parent / "fixtures" / "html" / "simple.html"


@pytest.mark.slow
def test_compile_subcommand_emits_artifacts(tmp_path):
    src = tmp_path / "simple.html"
    src.write_text(FIXTURE.read_text())
    rc = main(["compile", str(src)])
    assert rc == 0
    assert (tmp_path / "simple.png").exists()
    assert (tmp_path / "simple.preview.png").exists()
    assert (tmp_path / "simple.lint.json").exists()
    payload = json.loads((tmp_path / "simple.lint.json").read_text())
    assert payload["ok"] is True
    assert "stats" in payload


@pytest.mark.slow
def test_compile_returns_1_when_lint_errors(tmp_path):
    src = tmp_path / "bad.html"
    src.write_text(
        "<!doctype html><html><head></head>"
        "<body><img src='https://evil.example/x.png'></body></html>"
    )
    rc = main(["compile", str(src)])
    assert rc == 1
    payload = json.loads((tmp_path / "bad.lint.json").read_text())
    assert payload["ok"] is False
    assert any(f["rule"] == "external_resource" for f in payload["errors"])


@pytest.mark.slow
def test_compile_no_lint_flag_skips_lint(tmp_path):
    src = tmp_path / "bad.html"
    src.write_text(
        "<!doctype html><html><head></head>"
        "<body><img src='https://evil.example/x.png'></body></html>"
    )
    rc = main(["compile", str(src), "--no-lint"])
    assert rc == 0
    assert not (tmp_path / "bad.lint.json").exists()
