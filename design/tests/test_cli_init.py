import pytest

from tprint_design.cli import main


def test_init_writes_blank_template(tmp_path):
    target = tmp_path / "out.html"
    rc = main(["init", str(target)])
    assert rc == 0
    contents = target.read_text()
    assert "<!doctype html>" in contents.lower()


def test_init_writes_named_template(tmp_path):
    target = tmp_path / "design.html"
    rc = main(["init", str(target), "--template", "literary"])
    assert rc == 0
    assert "Field Notes" in target.read_text()


def test_init_refuses_to_overwrite_without_force(tmp_path):
    target = tmp_path / "x.html"
    target.write_text("existing")
    rc = main(["init", str(target)])
    assert rc == 2
    assert target.read_text() == "existing"


def test_init_unknown_template_errors(tmp_path):
    target = tmp_path / "x.html"
    with pytest.raises(SystemExit) as exc:
        main(["init", str(target), "--template", "no-such"])
    assert exc.value.code != 0
