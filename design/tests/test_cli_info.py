import json

from tprint_design.cli import main


def test_info_subcommand_prints_guidelines(capsys):
    rc = main(["info"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Live print area: **528 px**" in out
    assert "576 px" in out


def test_info_json_subcommand(capsys):
    rc = main(["info", "--json"])
    out = capsys.readouterr().out
    assert rc == 0
    payload = json.loads(out)
    assert payload["live_width_px"] == 528
    assert payload["print_head_px"] == 576
    assert payload["dpmm"] == 8.0
    assert payload["max_length_mm_default"] == 2000
    assert "IBM Plex Sans" in payload["fonts_available"]
    assert "rules_markdown" in payload
