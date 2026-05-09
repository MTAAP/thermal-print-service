"""Tests for CJK (Chinese/Japanese/Korean) character rendering support."""
from __future__ import annotations

import pytest
from PIL import Image

from printer.render.typography import (
    contains_cjk,
    is_cjk_char,
    render_body_text_mixed,
    segment_by_script,
    supersample_render_mixed,
)


class TestCjkDetection:
    """Tests for CJK character detection functions."""

    def test_is_cjk_char_detects_chinese(self):
        assert is_cjk_char("中")
        assert is_cjk_char("文")
        assert is_cjk_char("你")
        assert is_cjk_char("好")

    def test_is_cjk_char_detects_japanese_hiragana(self):
        assert is_cjk_char("あ")
        assert is_cjk_char("い")

    def test_is_cjk_char_detects_japanese_katakana(self):
        assert is_cjk_char("ア")
        assert is_cjk_char("イ")

    def test_is_cjk_char_detects_korean(self):
        assert is_cjk_char("한")
        assert is_cjk_char("글")

    def test_is_cjk_char_rejects_latin(self):
        assert not is_cjk_char("A")
        assert not is_cjk_char("z")
        assert not is_cjk_char("0")
        assert not is_cjk_char(" ")

    def test_is_cjk_char_detects_fullwidth_forms(self):
        assert is_cjk_char("！")  # Fullwidth exclamation mark
        assert is_cjk_char("：")  # Fullwidth colon

    def test_contains_cjk_with_chinese_text(self):
        assert contains_cjk("你好世界")
        assert contains_cjk("Hello 世界")
        assert contains_cjk("测试 test 测试")

    def test_contains_cjk_with_pure_latin(self):
        assert not contains_cjk("Hello World")
        assert not contains_cjk("abc 123")
        assert not contains_cjk("")

    def test_contains_cjk_with_mixed_text(self):
        assert contains_cjk("Hello世界")
        assert contains_cjk("你好World")


class TestSegmentByScript:
    """Tests for text segmentation by script."""

    def test_segment_pure_latin(self):
        segments = segment_by_script("Hello World")
        assert len(segments) == 1
        assert segments[0] == ("Hello World", False)

    def test_segment_pure_chinese(self):
        segments = segment_by_script("你好世界")
        assert len(segments) == 1
        assert segments[0] == ("你好世界", True)

    def test_segment_mixed_text(self):
        segments = segment_by_script("Hello世界")
        assert len(segments) == 2
        assert segments[0] == ("Hello", False)
        assert segments[1] == ("世界", True)

    def test_segment_alternating(self):
        segments = segment_by_script("Hello世界Test测试End")
        assert len(segments) == 5
        assert segments[0] == ("Hello", False)
        assert segments[1] == ("世界", True)
        assert segments[2] == ("Test", False)
        assert segments[3] == ("测试", True)
        assert segments[4] == ("End", False)

    def test_segment_empty_string(self):
        segments = segment_by_script("")
        assert len(segments) == 0

    def test_segment_single_cjk_char(self):
        segments = segment_by_script("中")
        assert len(segments) == 1
        assert segments[0] == ("中", True)


class TestFontRegistry:
    """Tests for CJK font support in FontRegistry."""

    def test_registry_has_cjk_font(self, fonts):
        assert fonts.has_cjk_font()

    def test_registry_loads_cjk_regular(self, fonts):
        cjk_font = fonts.cjk(bold=False, size_px=16)
        assert cjk_font is not None

    def test_registry_loads_cjk_bold(self, fonts):
        cjk_font = fonts.cjk(bold=True, size_px=16)
        assert cjk_font is not None


class TestSupersampleRenderMixed:
    """Tests for mixed Latin/CJK supersample rendering."""

    def test_render_pure_latin(self, fonts):
        img = supersample_render_mixed(
            text="Hello",
            latin_font=fonts.display(weight="medium", size_px=24),
            cjk_font=fonts.cjk(size_px=24),
            target_size_px=24,
            max_width_px=400,
        )
        assert img.mode == "1"
        assert img.width <= 400
        assert img.width > 0
        assert img.height > 0

    def test_render_pure_chinese(self, fonts):
        img = supersample_render_mixed(
            text="你好世界",
            latin_font=fonts.display(weight="medium", size_px=24),
            cjk_font=fonts.cjk(size_px=24),
            target_size_px=24,
            max_width_px=400,
        )
        assert img.mode == "1"
        assert img.width <= 400
        assert img.width > 0
        assert img.height > 0

    def test_render_mixed_text(self, fonts):
        img = supersample_render_mixed(
            text="Hello 世界 World",
            latin_font=fonts.display(weight="medium", size_px=24),
            cjk_font=fonts.cjk(size_px=24),
            target_size_px=24,
            max_width_px=500,
        )
        assert img.mode == "1"
        assert img.width <= 500
        assert img.width > 0
        assert img.height > 0

    def test_render_empty_text(self, fonts):
        img = supersample_render_mixed(
            text="",
            latin_font=fonts.display(weight="medium", size_px=24),
            cjk_font=fonts.cjk(size_px=24),
            target_size_px=24,
            max_width_px=400,
        )
        assert img.mode == "1"


class TestRenderBodyTextMixed:
    """Tests for mixed body text rendering (bitmap + CJK fallback)."""

    def test_render_pure_latin_body(self, fonts):
        img = render_body_text_mixed(
            text="Hello World",
            body_font=fonts.body(),
            cjk_font=fonts.cjk(size_px=16),
        )
        assert img.mode == "1"
        assert img.width > 0
        assert img.height > 0

    def test_render_pure_chinese_body(self, fonts):
        img = render_body_text_mixed(
            text="你好世界",
            body_font=fonts.body(),
            cjk_font=fonts.cjk(size_px=16),
        )
        assert img.mode == "1"
        assert img.width > 0
        assert img.height > 0

    def test_render_mixed_body(self, fonts):
        img = render_body_text_mixed(
            text="Hello 你好 World",
            body_font=fonts.body(),
            cjk_font=fonts.cjk(size_px=16),
        )
        assert img.mode == "1"
        assert img.width > 0
        assert img.height > 0

    def test_render_empty_body(self, fonts):
        img = render_body_text_mixed(
            text="",
            body_font=fonts.body(),
            cjk_font=fonts.cjk(size_px=16),
        )
        assert img.mode == "1"
