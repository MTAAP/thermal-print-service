import pytest
from PIL import Image

from tprint_design.lint import lint_html_text


@pytest.mark.slow
def test_runner_combines_pre_and_post_findings():
    html = "<body><img src='https://x.example/y.png'><p>hi</p></body>"
    rgb = Image.new("RGB", (576, 200), (0, 0, 0))
    one_bit = Image.new("1", (576, 200), 0)
    rpt = lint_html_text(
        html, rendered_rgb=rgb, rendered_one_bit=one_bit,
        render_ms=1234, blocked_external_requests=1,
    )
    rule_names = {f.rule for f in rpt.errors + rpt.warnings}
    assert "external_resource" in rule_names  # from pre
    # Post rules should also appear if applicable; with all-black image
    # we expect mostly_empty NOT to fire.
    assert "mostly_empty" not in rule_names
    assert rpt.stats["render_ms"] == 1234
    assert rpt.stats["blocked_external_requests"] == 1
    assert rpt.stats["rendered_height_px"] == 200


@pytest.mark.slow
def test_runner_pre_only_when_no_image():
    html = "<body><p style='font-size:20px'>ok</p></body>"
    rpt = lint_html_text(html)
    assert rpt.ok
    assert "rendered_height_px" not in rpt.stats


@pytest.mark.slow
def test_blocked_subresource_fails_lint_even_without_pre_error():
    # The symlink / file-escape case: a relative ref passes pre-render lint
    # (it is not an http/ws external), but the render sandbox blocks the fetch
    # at runtime. That must still fail lint so `print` refuses to send a PNG
    # with the asset missing — not just record a stat.
    html = "<body><img src='./local-looking.png'><p style='font-size:20px'>hi</p></body>"
    rgb = Image.new("RGB", (576, 50), (0, 0, 0))
    one_bit = Image.new("1", (576, 50), 0)
    rpt = lint_html_text(
        html, rendered_rgb=rgb, rendered_one_bit=one_bit,
        blocked_external_requests=1,
    )
    error_rules = {f.rule for f in rpt.errors}
    assert "external_resource" not in error_rules  # pre-render didn't catch it
    assert "blocked_subresource" in error_rules    # but the runtime block did
    assert not rpt.ok
