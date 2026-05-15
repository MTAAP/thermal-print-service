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
def test_text_shadow_in_style_block_flagged():
    # Shadow set via a <style> rule (not inline style="...") — the el.style
    # walk can't see this and the reset's !important forces computed-style
    # back to 'none'. The stylesheet-rule scan must catch it.
    html = (
        "<head><style>"
        "p { text-shadow: 1px 1px #000; }"
        "</style></head><body><p>x</p></body>"
    )
    findings = pre_render_lint(html)
    assert any(f.rule == "text_shadow" for f in findings)


@pytest.mark.slow
def test_box_shadow_via_class_selector_flagged():
    html = (
        "<head><style>"
        ".card { box-shadow: 0 0 4px #000; }"
        "</style></head><body><div class='card'>x</div></body>"
    )
    findings = pre_render_lint(html)
    assert any(f.rule == "box_shadow" for f in findings)


@pytest.mark.slow
def test_reset_shadow_none_does_not_self_flag():
    # The reset itself contains `* { text-shadow: none !important }`. That
    # must not trip the rule scan — only non-'none' shadow values count.
    html = "<body><p>plain text</p></body>"
    findings = pre_render_lint(html)
    assert not any(f.rule in ("text_shadow", "box_shadow") for f in findings)


@pytest.mark.slow
def test_external_resource_in_css_url_flagged():
    # background-image URL pointing at a CDN — blocked at runtime, must
    # surface in lint as well so the user sees the offending URL.
    html = (
        "<head><style>"
        "body { background-image: url('https://cdn.example.com/bg.png'); }"
        "</style></head><body>hi</body>"
    )
    findings = pre_render_lint(html)
    assert any(
        f.rule == "external_resource"
        and "https://cdn.example.com/bg.png" in f.message
        for f in findings
    )


@pytest.mark.slow
def test_external_resource_in_css_import_flagged():
    html = (
        "<head><style>"
        "@import url('https://cdn.example.com/styles.css');"
        "</style></head><body>hi</body>"
    )
    findings = pre_render_lint(html)
    assert any(
        f.rule == "external_resource"
        and "https://cdn.example.com/styles.css" in f.message
        for f in findings
    )


@pytest.mark.slow
def test_clean_html_produces_no_pre_render_findings():
    html = "<body><p style='font-size:18px'>hi</p></body>"
    findings = pre_render_lint(html)
    assert findings == []
