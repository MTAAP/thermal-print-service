from pathlib import Path

import pytest

from tprint_design.cli import main

FIXTURE = Path(__file__).parent / "fixtures" / "html" / "simple.html"


@pytest.mark.slow
def test_preview_subcommand_compiles_and_calls_opener(tmp_path, monkeypatch):
    src = tmp_path / "simple.html"
    src.write_text(FIXTURE.read_text())

    opened: list[Path] = []
    monkeypatch.setattr("tprint_design.cli._open_default", opened.append)

    rc = main(["preview", str(src)])
    assert rc == 0
    assert (tmp_path / "simple.png").exists()
    assert opened == [tmp_path / "simple.png"]
