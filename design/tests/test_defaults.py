from pathlib import Path

from tprint_design import defaults


def test_thermal_reset_present():
    css = defaults.thermal_reset_css()
    assert "color: #000000" in css
    assert "width: 576px" in css
    assert "image-rendering: pixelated" in css


def test_font_face_block_includes_all_required_families():
    css = defaults.font_face_block()
    for family in (
        "IBM Plex Sans",
        "JetBrains Mono",
        "Noto Sans SC",
    ):
        assert family in css


def test_font_face_block_uses_file_urls():
    css = defaults.font_face_block()
    assert "file://" in css


def test_font_face_block_paths_resolve():
    css = defaults.font_face_block()
    # Extract every src URL and verify the file exists.
    import re
    for match in re.finditer(r"url\('file://([^']+)'\)", css):
        path = Path(match.group(1))
        assert path.exists(), f"font not found at {path}"


def test_inject_into_full_html_document():
    html = "<!doctype html><html><head><title>x</title></head><body>hi</body></html>"
    out = defaults.inject_into(html)
    assert "color: #000000" in out
    assert "<title>x</title>" in out
    assert out.index("color: #000000") < out.index("hi"), \
        "reset must be injected into the head, before body content"


def test_inject_wraps_html_with_no_head():
    html = "<p>hello</p>"
    out = defaults.inject_into(html)
    assert "<head>" in out
    assert "color: #000000" in out
    assert "<p>hello</p>" in out
