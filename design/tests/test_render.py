import pytest
from PIL import Image

from tprint_design.render import RenderResult, render_html_to_png


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
def test_render_resolves_relative_refs_against_source_dir(tmp_path):
    # Without source_path, relative refs in the source HTML resolve against
    # an unrelated render dir (or about:blank) and the image silently 404s.
    # With source_path threaded through, <base href="file:///source-dir/">
    # is injected and ./logo.png loads from next to the HTML file.
    logo = tmp_path / "logo.png"
    Image.new("RGB", (50, 50), (255, 0, 0)).save(logo)
    src = tmp_path / "design.html"
    src.write_text(
        '<body style="margin:0">'
        '<img src="./logo.png" width="50" height="50">'
        "</body>"
    )

    out_path = tmp_path / "out.png"
    result = render_html_to_png(
        src.read_text(),
        source_path=src,
        out_path=out_path,
    )

    # Successful load: any near-pure-red pixel proves the image was fetched
    # and rasterized. A broken-image placeholder would be all white/grey.
    with Image.open(result.png_path) as img:
        rgb = img.convert("RGB")
        assert any(
            r > 200 and g < 50 and b < 50 for r, g, b in rgb.getdata()
        ), "expected red pixel from ./logo.png; got broken-image instead"
    # And no external (http/ws) fetches were attempted.
    assert result.blocked_external_requests == 0


@pytest.mark.slow
def test_render_disables_page_javascript():
    # If page JS ran, the script would replace the body with the marker
    # text and the rendered output would have ink. With JS disabled (the
    # security-posture default), the script is inert and the page stays
    # blank, so the dithered output is all-white above the trim floor.
    html = (
        "<!doctype html><html><body>"
        "<script>document.body.innerHTML = "
        "'<div style=\"width:576px;height:200px;background:#000\">x</div>';"
        "</script>"
        "</body></html>"
    )
    result = render_html_to_png(html)
    img = Image.open(result.png_path).convert("1")
    # No ink anywhere — script that would have produced the black block
    # never ran.
    assert not any(v == 0 for v in img.getdata()), (
        "page JS executed; the black block from the inline script appeared "
        "in the rendered output"
    )


@pytest.mark.slow
def test_render_blocks_arbitrary_file_uri_outside_source_dir(tmp_path):
    # An <iframe src='file:///etc/passwd'> would render the file contents
    # into the screenshot if it weren't blocked. The route filter now
    # allows only the render dir, the source dir, and data: URIs — any
    # other file:// must abort. We verify by attempting to load a file
    # OUTSIDE the source dir (which exists but isn't allowlisted) and
    # checking it shows up in blocked_external_requests.
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    src_dir = tmp_path / "inside"
    src_dir.mkdir()
    src = src_dir / "design.html"
    secret_uri = (outside / "secret.png").resolve().as_uri()
    src.write_text(
        f'<body><iframe src="{secret_uri}"></iframe></body>'
    )
    result = render_html_to_png(src.read_text(), source_path=src)
    assert result.blocked_external_requests >= 1, (
        "file:// URI outside source dir was not blocked; exfil channel open"
    )
