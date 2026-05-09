"""CJK fallback rendering tests."""
from __future__ import annotations

from printer.render.renderer import render_document
from printer.render.typography import (
    iter_atoms,
    render_body_line,
    supersample_render,
    wrap_body_text,
)
from printer.schema.document import Document


def test_iter_atoms_pure_latin(fonts):
    atoms = list(iter_atoms("Hello world", fonts=fonts))
    assert atoms == ["Hello", " ", "world"]


def test_iter_atoms_pure_chinese(fonts):
    """CJK runs break per codepoint so spaceless scripts can wrap mid-run."""
    atoms = list(iter_atoms("你好世界", fonts=fonts))
    assert atoms == ["你", "好", "世", "界"]


def test_iter_atoms_mixed_script(fonts):
    atoms = list(iter_atoms("Hello 世界 World", fonts=fonts))
    assert atoms == ["Hello", " ", "世", "界", " ", "World"]


def test_wrap_body_text_chinese_breaks_per_char(fonts):
    """Long Chinese paragraphs (no whitespace) must wrap, not overflow.
    `textwrap.wrap` would have treated this as one un-breakable word."""
    long_chinese = "你好世界" * 30  # 120 chars, well past one body line
    lines = wrap_body_text(long_chinese, fonts=fonts, max_width_px=528)
    assert len(lines) >= 2
    # No line should exceed the live width when measured against the body grid.
    for line in lines:
        assert fonts.body_atom_width(line) <= 528


def test_wrap_body_text_long_url_breaks_at_chars(fonts):
    """Spaceless Latin atoms wider than max_width_px must split mid-word."""
    long_url = "https://example.com/very/deep/path/" + "a" * 200
    lines = wrap_body_text(long_url, fonts=fonts, max_width_px=528)
    assert len(lines) >= 2
    for line in lines:
        assert fonts.body_atom_width(line) <= 528


def test_wrap_body_text_mixed_script(fonts):
    """Mixed Latin/CJK paragraphs should wrap at sensible boundaries."""
    text = "The Chinese word for hello is 你好 and goodbye is 再见 — useful when traveling."
    lines = wrap_body_text(text, fonts=fonts, max_width_px=400)
    assert len(lines) >= 2
    for line in lines:
        assert fonts.body_atom_width(line) <= 400


def test_render_body_line_chinese_renders_ink(fonts):
    """A pure-Chinese line should render as actual ink, not a row of empty
    .notdef boxes. Verify by checking the histogram has more black pixels
    than the same-width canvas would have if every glyph were tofu."""
    img = render_body_line("你好世界", fonts=fonts, max_width_px=528)
    assert img.mode == "1"
    assert img.height > 0
    black_pixels = img.histogram()[0]
    # Pure tofu boxes (4 outline rectangles) would have very few black pixels
    # relative to image area; real glyphs fill far more.
    assert black_pixels > img.width * img.height * 0.05


def test_render_body_line_mixed_renders_both_scripts(fonts):
    img = render_body_line("Hello 世界 World", fonts=fonts, max_width_px=528)
    assert img.mode == "1"
    assert img.width > 0
    assert img.height > 0
    # Mixed line should be at least as black as either pure variant scaled to width.
    assert img.histogram()[0] > 0


def test_supersample_render_falls_through_for_pure_latin(fonts):
    """Pure-Latin text should bypass the composite path even when a fallback
    is provided. The output should match what the fast path produces."""
    primary = fonts.display(weight="bold", size_px=22)
    cjk = fonts.cjk(bold=True)
    fast = supersample_render(
        text="Hello", font=primary, target_size_px=22, max_width_px=400,
    )
    with_fb = supersample_render(
        text="Hello", font=primary, fallback_font=cjk,
        target_size_px=22, max_width_px=400,
    )
    assert fast.tobytes() == with_fb.tobytes()


def test_supersample_render_emoji_does_not_crash(fonts):
    """Codepoints missing in BOTH primary and fallback render as the
    primary's .notdef glyph. We just need the call not to crash."""
    img = supersample_render(
        text="hi 🎉",
        font=fonts.display(weight="medium", size_px=22),
        fallback_font=fonts.cjk(bold=False),
        target_size_px=22, max_width_px=400,
    )
    assert img.mode == "1"
    assert img.width > 0


def test_paragraph_with_chinese_wraps_and_renders(fonts):
    doc = Document.model_validate({"blocks": [
        {"type": "paragraph",
         "text": "你好世界 Hello world. " + "测试" * 30},
    ]})
    img = render_document(doc, fonts=fonts)
    # Should wrap to multiple body lines (each line is 26 px now).
    assert img.height >= 26 * 3


def test_bullets_with_chinese_items(fonts):
    doc = Document.model_validate({"blocks": [
        {"type": "bullets", "items": [
            "你好世界",
            "Mixed item: 这是一个很长的中文句子，需要换行才能在小票宽度内显示完整。",
            "Plain Latin",
        ]},
    ]})
    img = render_document(doc, fonts=fonts)
    assert img.height > 0


def test_header_with_chinese_renders(fonts):
    doc = Document.model_validate({"blocks": [
        {"type": "header", "text": "早上好 — Morning Brief", "style": "inverse_band"},
    ]})
    img = render_document(doc, fonts=fonts)
    assert img.width == 576
    assert img.height > 0
