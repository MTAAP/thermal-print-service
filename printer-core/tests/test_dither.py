import hashlib
from pathlib import Path

from PIL import Image

from printer_core.dither import (
    DITHERS,
    atkinson_dither,
    floyd_steinberg,
    no_dither,
    ordered_dither,
)

FIXTURE = Path(__file__).parent / "fixtures" / "grayscale_ramp.png"


def _digest(img: Image.Image) -> str:
    return hashlib.sha256(img.tobytes()).hexdigest()


def test_atkinson_returns_one_bit_image():
    img = Image.open(FIXTURE)
    out = atkinson_dither(img.copy())
    assert out.mode == "1"
    assert out.size == img.size


def test_atkinson_is_deterministic():
    img = Image.open(FIXTURE)
    a = _digest(atkinson_dither(img.copy()))
    b = _digest(atkinson_dither(img.copy()))
    assert a == b


def test_dithers_dict_exposes_named_algorithms():
    assert set(DITHERS) == {"atkinson", "floyd_steinberg", "ordered", "none"}


def test_no_dither_thresholds_at_128():
    img = Image.new("L", (4, 1))
    img.putpixel((0, 0), 0)
    img.putpixel((1, 0), 127)
    img.putpixel((2, 0), 128)
    img.putpixel((3, 0), 255)
    out = no_dither(img)
    assert list(out.getdata()) == [0, 0, 255, 255]


def test_ordered_dither_uses_bayer_threshold():
    # Pixel (0,0) of Bayer 8 maps to 4 (smallest), so any value >= 4 stays white.
    img = Image.new("L", (1, 1), 4)
    out = ordered_dither(img)
    assert out.getpixel((0, 0)) == 255


def test_floyd_steinberg_returns_one_bit():
    img = Image.open(FIXTURE)
    out = floyd_steinberg(img.copy())
    assert out.mode == "1"


ATKINSON_RAMP_SHA256 = "445ebc8d4995020f866c3750098dd782e1e1397113193527ba314a25d63a3858"


def test_atkinson_golden_digest():
    img = Image.open(FIXTURE)
    out = atkinson_dither(img.copy())
    assert _digest(out) == ATKINSON_RAMP_SHA256, (
        "Atkinson output drifted — this is the authoritative golden for "
        "the algorithm in printer_core.dither. If the change is intentional, "
        "update ATKINSON_RAMP_SHA256 here. The service/ shim and parity "
        "test will reflect the change automatically."
    )
