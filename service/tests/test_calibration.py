from PIL import Image

from printer.calibration import build_calibration_ruler


def test_ruler_is_576_wide_and_has_marks():
    img = build_calibration_ruler(target_height_px=2000)
    assert isinstance(img, Image.Image)
    assert img.mode == "1"
    assert img.width == 576
    assert img.height == 2000
    # Top edge: pixels at column 0 alternate enough to suggest tick marks
    top = [img.getpixel((x, 0)) for x in range(0, 576, 8)]
    assert 0 in top  # at least one black pixel at the very top
