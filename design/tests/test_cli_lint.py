import json

import pytest

from tprint_design.cli import main


@pytest.mark.slow
def test_lint_subcommand_clean(tmp_path):
    src = tmp_path / "ok.html"
    src.write_text("<body><p style='font-size:18px'>hi</p></body>")
    rc = main(["lint", str(src)])
    assert rc == 0


@pytest.mark.slow
def test_lint_subcommand_writes_json(tmp_path):
    src = tmp_path / "ok.html"
    src.write_text("<body><p style='font-size:18px'>hi</p></body>")
    main(["lint", str(src), "--out", str(tmp_path / "rep.json")])
    payload = json.loads((tmp_path / "rep.json").read_text())
    assert payload["ok"] is True


@pytest.mark.slow
def test_lint_subcommand_errors_exit_1(tmp_path):
    src = tmp_path / "bad.html"
    src.write_text("<body><img src='https://x.example/y.png'></body>")
    rc = main(["lint", str(src)])
    assert rc == 1
