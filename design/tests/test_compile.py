from pathlib import Path

import pytest
from PIL import Image

from tprint_design.compile import CompileResult, compile_html

FIXTURE = Path(__file__).parent / "fixtures" / "html" / "simple.html"


@pytest.mark.slow
def test_compile_emits_one_bit_png(tmp_path):
    out = tmp_path / "simple.png"
    result = compile_html(FIXTURE, out_path=out)
    assert isinstance(result, CompileResult)
    assert out.exists()
    img = Image.open(out)
    assert img.mode == "1"
    assert img.width == 576
    assert img.height >= 60


@pytest.mark.slow
def test_compile_emits_grayscale_preview(tmp_path):
    out = tmp_path / "simple.png"
    result = compile_html(FIXTURE, out_path=out)
    preview_path = out.with_name(out.stem + ".preview.png")
    assert preview_path.exists()
    img = Image.open(preview_path)
    assert img.mode == "L"
    assert result.preview_path == preview_path


@pytest.mark.slow
def test_compile_trims_trailing_whitespace(tmp_path):
    """A short body should not produce an 800-px-tall PNG."""
    html = (
        "<!doctype html><html><head></head>"
        "<body><p>tiny</p></body></html>"
    )
    src = tmp_path / "tiny.html"
    src.write_text(html)
    out = tmp_path / "tiny.png"
    compile_html(src, out_path=out)
    img = Image.open(out)
    # Trim should bring this well below the default 800-px viewport.
    assert img.height < 200
    # But not below the 80-px floor.
    assert img.height >= 80


@pytest.mark.slow
def test_compile_result_exposes_stats(tmp_path):
    out = tmp_path / "simple.png"
    result = compile_html(FIXTURE, out_path=out)
    assert result.rendered_height_px == Image.open(out).height
    assert result.estimated_paper_mm == result.rendered_height_px / 8.0
    assert 0.0 <= result.ink_pixel_ratio <= 1.0
    assert result.render_ms > 0


@pytest.mark.slow
def test_compile_does_not_truncate_content_with_internal_dense_run(tmp_path):
    """Regression: a body with content extending past row 80 must not be
    truncated to the floor when an earlier dense run of ink rows happens
    to satisfy the lookback condition."""
    html = (
        "<!doctype html><html><head><style>"
        "body { padding: 0 24px; font-family: monospace; }"
        "h1 { font-size: 18px; margin: 0; }"
        "pre { font-size: 14px; line-height: 1.0; margin: 0; }"
        "</style></head><body>"
        "<h1>HEADER</h1>"
        "<pre>line 1\nline 2\nline 3\nline 4\nline 5\nline 6\n"
        "line 7\nline 8\nline 9\nline 10</pre>"
        "</body></html>"
    )
    src = tmp_path / "long.html"
    src.write_text(html)
    out = tmp_path / "long.png"
    compile_html(src, out_path=out)
    img = Image.open(out)
    # Header (~18 px) + 10 lines of mono @ 14 px ≈ 158 px of content.
    # The trim must preserve more than the 80-px floor — the bottom of
    # the rendered content must survive.
    assert img.height > 100, (
        f"trim truncated content; height={img.height} px (expected > 100). "
        "If this fails, _trim_trailing_white is breaking inside a content "
        "region instead of at the trailing-whitespace boundary."
    )
