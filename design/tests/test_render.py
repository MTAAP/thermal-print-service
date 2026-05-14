import pytest
from PIL import Image

from tprint_design.render import RenderError, RenderResult, render_html_to_png


@pytest.mark.slow
def test_render_simple_html_returns_576px_wide_png():
    html = (
        "<!doctype html><html><head></head>"
        "<body><div style='height:200px'>x</div></body></html>"
    )
    result = render_html_to_png(html)
    assert isinstance(result, RenderResult)
    img = Image.open(result.png_path)
    assert img.width == 576
    assert img.height >= 200  # at least the div's height
    assert result.duration_ms > 0


@pytest.mark.slow
def test_render_html_with_no_head_is_wrapped():
    result = render_html_to_png("<p>hi</p>")
    img = Image.open(result.png_path)
    assert img.width == 576


@pytest.mark.slow
def test_render_blocks_external_resources():
    html = (
        "<!doctype html><html><head></head>"
        "<body><img src='https://example.com/never.png'>"
        "<p>after</p></body></html>"
    )
    result = render_html_to_png(html)
    # External fetches blocked at the route handler; render still completes
    # (the broken image renders as the alt/empty box) and the blocked
    # request count is reported back.
    assert result.blocked_external_requests >= 1


@pytest.mark.slow
def test_render_times_out_on_hung_page():
    html = (
        "<!doctype html><html><head>"
        "<script>while(true){}</script></head><body>x</body></html>"
    )
    with pytest.raises(RenderError) as exc:
        render_html_to_png(html, timeout_ms=2000)
    assert "timeout" in str(exc.value).lower()
