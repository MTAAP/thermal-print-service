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
