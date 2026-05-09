from PIL import Image

from printer.render.dither import DITHERS, atkinson_dither


def test_atkinson_outputs_1bit():
    img = Image.new("L", (16, 16), 128)
    out = atkinson_dither(img)
    assert out.mode == "1"
    assert out.size == (16, 16)


def test_atkinson_pure_white_stays_white():
    img = Image.new("L", (8, 8), 255)
    out = atkinson_dither(img)
    # PIL's "1" mode getpixel returns 0 or 255 (not 0/1) — every pixel should be white.
    assert all(out.getpixel((x, y)) == 255 for x in range(8) for y in range(8))


def test_atkinson_pure_black_stays_black():
    img = Image.new("L", (8, 8), 0)
    out = atkinson_dither(img)
    assert all(out.getpixel((x, y)) == 0 for x in range(8) for y in range(8))


def test_dither_registry_complete():
    assert set(DITHERS) == {"atkinson", "floyd_steinberg", "ordered", "none"}
