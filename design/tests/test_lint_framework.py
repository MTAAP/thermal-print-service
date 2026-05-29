from tprint_design.lint import LintFinding, LintReport, LintSeverity


def test_lint_report_is_ok_when_no_errors():
    rpt = LintReport(errors=[], warnings=[], stats={})
    assert rpt.ok is True
    assert rpt.to_dict()["ok"] is True


def test_lint_report_has_errors_means_not_ok():
    rpt = LintReport(
        errors=[LintFinding(rule="x", severity=LintSeverity.ERROR, message="m")],
        warnings=[],
        stats={"render_ms": 100},
    )
    assert rpt.ok is False
    out = rpt.to_dict()
    assert out["ok"] is False
    assert out["errors"][0]["rule"] == "x"
    assert out["stats"]["render_ms"] == 100


def test_lint_finding_serializes_with_optional_selector():
    f = LintFinding(
        rule="r", severity=LintSeverity.WARNING,
        message="m", selector="body > p:nth-child(1)",
    )
    d = f.to_dict()
    assert d["selector"] == "body > p:nth-child(1)"
    assert d["severity"] == "warning"


def test_lint_finding_omits_selector_when_none():
    f = LintFinding(rule="r", severity=LintSeverity.WARNING, message="m")
    assert "selector" not in f.to_dict()
