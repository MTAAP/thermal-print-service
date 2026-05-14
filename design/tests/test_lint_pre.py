import pytest

from tprint_design.lint_pre import pre_render_lint


@pytest.mark.slow
def test_external_resource_flagged_as_error():
    html = "<body><img src='https://cdn.example.com/x.png'></body>"
    findings = pre_render_lint(html)
    rule_names = {f.rule for f in findings}
    assert "external_resource" in rule_names
    assert any(f.severity.value == "error" for f in findings if f.rule == "external_resource")


@pytest.mark.slow
def test_small_font_size_warns():
    html = "<body><p style='font-size:11px'>tiny</p></body>"
    findings = pre_render_lint(html)
    assert any(f.rule == "font_size_small" for f in findings)


@pytest.mark.slow
def test_very_small_font_size_errors():
    html = "<body><p style='font-size:8px'>tiny</p></body>"
    findings = pre_render_lint(html)
    assert any(
        f.rule == "font_size_too_small" and f.severity.value == "error"
        for f in findings
    )


@pytest.mark.slow
def test_text_shadow_warns():
    html = "<body><p style='text-shadow: 1px 1px #000'>x</p></body>"
    findings = pre_render_lint(html)
    assert any(f.rule == "text_shadow" for f in findings)


@pytest.mark.slow
def test_clean_html_produces_no_pre_render_findings():
    html = "<body><p style='font-size:18px'>hi</p></body>"
    findings = pre_render_lint(html)
    assert findings == []
