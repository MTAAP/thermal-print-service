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


@pytest.mark.slow
def test_external_import_in_sidecar_stylesheet_flagged(tmp_path):
    """Regression: a local sidecar stylesheet with @import url(https://...)
    used to slip past the walker (cssRules access on a sidecar can throw
    SecurityError, silently skipping the @import). The route handler
    blocks the fetch but the lint must still surface the finding so
    rpt.ok is false."""
    sidecar = tmp_path / "style.css"
    sidecar.write_text("@import url(https://cdn.example.com/x.css);\n")
    src = tmp_path / "design.html"
    src.write_text(
        '<!doctype html><html><head>'
        '<link rel="stylesheet" href="./style.css">'
        '</head><body>hi</body></html>'
    )
    findings = pre_render_lint(src.read_text(), source_path=src)
    assert any(
        f.rule == "external_resource"
        and "cdn.example.com" in f.message
        and f.severity.value == "error"
        for f in findings
    ), f"sidecar @import not flagged. findings={findings!r}"


@pytest.mark.slow
def test_symlink_escape_under_source_dir_is_blocked(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "secret.png"
    secret.write_bytes(b"\x89PNG\r\n\x1a\n")

    src_dir = tmp_path / "design"
    src_dir.mkdir()
    link = src_dir / "innocent.png"
    link.symlink_to(secret)
    src = src_dir / "design.html"
    src.write_text(
        "<!doctype html><html><body>"
        '<img src="./innocent.png">'
        "</body></html>"
    )

    findings = pre_render_lint(src.read_text(), source_path=src)
    assert any(
        f.rule == "external_resource"
        and "innocent.png" in f.message
        and f.severity.value == "error"
        for f in findings
    ), f"symlink escape was not blocked. findings={findings!r}"


@pytest.mark.slow
def test_inverse_text_small_size_warns():
    """Regression: a 22 px white-on-black blockquote (the FOLIO landing
    page bug we hit on paper) must produce an ``inverse_text_too_small``
    warning so future agents don't print and rediscover the same heat-
    bleed-erodes-the-reverse failure."""
    html = (
        "<!doctype html><html><head><style>"
        ".q { background: #000; color: #fff; font-size: 22px; "
        "padding: 10px; }"
        "</style></head><body><p class='q'>quoted text</p></body></html>"
    )
    findings = pre_render_lint(html)
    assert any(
        f.rule == "inverse_text_too_small" and f.severity.value == "warning"
        for f in findings
    ), f"22px white-on-black not flagged. findings={findings!r}"


@pytest.mark.slow
def test_inverse_text_at_display_size_with_bold_does_not_warn():
    """The H1 inverse-band aesthetic at 56 px bold (which survived the
    print head fine) must NOT trigger the warning — the lint targets
    the body-size failure case only."""
    html = (
        "<!doctype html><html><head><style>"
        ".banner { background: #000; color: #fff; font-size: 56px; "
        "font-weight: 700; padding: 4px 8px; }"
        "</style></head><body><h1 class='banner'>SURVIVE</h1></body></html>"
    )
    findings = pre_render_lint(html)
    assert not any(
        f.rule == "inverse_text_too_small" for f in findings
    ), f"56px bold white-on-black wrongly flagged. findings={findings!r}"


@pytest.mark.slow
def test_external_resource_inside_media_query_flagged():
    """Regression: shadows declared inside an @media block were silently
    accepted because the walker didn't recurse into CSSMediaRule.cssRules."""
    html = (
        "<!doctype html><html><head><style>"
        "@media (max-width: 1000px) { p { text-shadow: 4px 4px #000 } }"
        "</style></head><body><p>x</p></body></html>"
    )
    findings = pre_render_lint(html)
    assert any(
        f.rule == "text_shadow"
        for f in findings
    ), f"@media-nested text-shadow not flagged. findings={findings!r}"
