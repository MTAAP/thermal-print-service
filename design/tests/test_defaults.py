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
    # Path.as_uri() always emits "file:///" with three slashes, never two.
    # Two slashes would mean a hostname-style URL ("file://host/path") and
    # is invalid for local files on most platforms.
    assert "file:///" in css
    assert "file://\\" not in css  # Windows backslash regression guard


def test_font_face_block_paths_resolve():
    import re
    from urllib.parse import unquote, urlparse
    from urllib.request import url2pathname

    css = defaults.font_face_block()
    for match in re.finditer(r"url\('([^']+)'\)", css):
        url = match.group(1)
        # url2pathname converts file:// URLs to native filesystem paths
        # correctly on every platform (including Windows drive letters).
        local_path = Path(url2pathname(unquote(urlparse(url).path)))
        assert local_path.exists(), f"font not found at {local_path}"


def test_inject_into_full_html_document():
    html = "<!doctype html><html><head><title>x</title></head><body>hi</body></html>"
    out = defaults.inject_into(html)
    assert "color: #000000" in out
    assert "<title>x</title>" in out
    assert out.index("color: #000000") < out.index("hi"), \
        "reset must be injected into the head, before body content"


def test_inject_places_reset_before_user_head_styles():
    # User styles declared in <head> must be source-ordered AFTER the reset
    # so they win on tied specificity (e.g. user redefining body padding).
    user_style = "<style>body { padding: 99px; }</style>"
    html = (
        "<!doctype html><html><head>"
        f"{user_style}"
        "</head><body>hi</body></html>"
    )
    out = defaults.inject_into(html)
    reset_idx = out.index("color: #000000")
    user_idx = out.index("padding: 99px")
    assert reset_idx < user_idx, (
        "user CSS must come after the injected reset so source-order ties "
        "favor the user, not the reset"
    )


def test_inject_wraps_html_with_no_head():
    html = "<p>hello</p>"
    out = defaults.inject_into(html)
    assert "<head>" in out
    assert "color: #000000" in out
    assert "<p>hello</p>" in out


def test_inject_adds_base_tag_when_source_path_given(tmp_path):
    src = tmp_path / "design.html"
    src.write_text("<body><p>x</p></body>")
    out = defaults.inject_into(src.read_text(), source_path=src)
    expected = src.parent.resolve().as_uri() + "/"
    assert f'<base href="{expected}">' in out
    # base must appear before the reset block so URL-bearing additions
    # to the injected styles would resolve against it correctly.
    assert out.index("<base href=") < out.index("color: #000000")


def test_inject_skips_base_when_user_has_one(tmp_path):
    src = tmp_path / "design.html"
    user_html = (
        '<head><base href="https://cdn.example.com/"></head>'
        "<body><p>x</p></body>"
    )
    out = defaults.inject_into(user_html, source_path=src)
    # Only the user's <base> survives; ours is not added.
    assert out.count("<base ") == 1
    assert "https://cdn.example.com/" in out
    assert tmp_path.resolve().as_uri() not in out


def test_inject_preserves_user_absolute_base(tmp_path):
    src = tmp_path / "design.html"
    user_html = (
        '<head><base href="https://cdn.example.com/assets/"></head>'
        "<body><p>x</p></body>"
    )
    out = defaults.inject_into(user_html, source_path=src)
    assert out.count("<base ") == 1
    assert 'href="https://cdn.example.com/assets/"' in out
    assert tmp_path.resolve().as_uri() not in out


def test_inject_rewrites_quoted_relative_user_base_against_source_path(tmp_path):
    src = tmp_path / "design.html"
    user_html = (
        '<head><base href="./assets/"></head>'
        "<body><img src='logo.png'></body>"
    )
    out = defaults.inject_into(user_html, source_path=src)
    expected = (src.parent / "assets").resolve().as_uri() + "/"
    assert out.count("<base ") == 1
    assert f'<base href="{expected}">' in out
    assert 'href="./assets/"' not in out


def test_inject_rewrites_unquoted_relative_user_base_against_source_path(tmp_path):
    src = tmp_path / "design.html"
    user_html = (
        "<head><base href=assets/></head>"
        "<body><img src='logo.png'></body>"
    )
    out = defaults.inject_into(user_html, source_path=src)
    expected = (src.parent / "assets").resolve().as_uri() + "/"
    assert out.count("<base ") == 1
    assert f'<base href="{expected}">' in out
    assert "href=assets/" not in out


def test_inject_skips_base_when_no_source_path():
    html = "<body><p>x</p></body>"
    out = defaults.inject_into(html)
    assert "<base " not in out


def test_inject_does_not_match_basefont_as_base(tmp_path):
    # <basefont> is a deprecated but distinct element. A naive `"<base"`
    # substring check would treat it as an existing <base> and skip our
    # injection. The pattern requires whitespace or `>` after `base`.
    src = tmp_path / "design.html"
    html = "<head><basefont color='red'></head><body>x</body>"
    out = defaults.inject_into(html, source_path=src)
    expected = src.parent.resolve().as_uri() + "/"
    assert f'<base href="{expected}">' in out
