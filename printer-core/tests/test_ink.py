from PIL import Image

from printer_core.ink import ink_ratio


def test_all_black_is_full_ratio():
    img = Image.new("1", (10, 10), color=0)
    assert ink_ratio(img) == 1.0


def test_all_white_is_zero_ratio():
    img = Image.new("1", (10, 10), color=1)
    assert ink_ratio(img) == 0.0


def test_half_black_half_white():
    img = Image.new("1", (10, 10), color=1)
    for y in range(10):
        for x in range(5):
            img.putpixel((x, y), 0)
    assert ink_ratio(img) == 0.5


def test_empty_image_returns_zero():
    img = Image.new("1", (0, 0))
    assert ink_ratio(img) == 0.0


def test_converts_non_1bit_input():
    # Pure white/black RGB convert unambiguously (no dither pattern), proving
    # ink_ratio accepts non-"1" input by converting first.
    white = Image.new("RGB", (8, 8), color=(255, 255, 255))
    assert ink_ratio(white) == 0.0
    black = Image.new("RGB", (8, 8), color=(0, 0, 0))
    assert ink_ratio(black) == 1.0
