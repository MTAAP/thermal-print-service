"""Calibration ruler renderer.

Prints a 576-px-wide ruler with major/minor tick marks every N pixels and
labelled distances. The user measures the printed length with calipers
and we pin DPMM in constants.py. Reference is in pixels (deterministic,
DPI-independent); the printout's physical length is the unknown we are
trying to measure.
"""
from __future__ import annotations

from PIL import Image, ImageDraw, ImageFont


def build_calibration_ruler(target_height_px: int = 2000) -> Image.Image:
    img = Image.new("1", (576, target_height_px), 1)  # white
    d = ImageDraw.Draw(img)

    # Vertical centerline ruler; ticks every 50 px (major) / 10 px (minor)
    centerline_x = 100
    d.line([(centerline_x, 0), (centerline_x, target_height_px - 1)], fill=0, width=2)

    try:
        font = ImageFont.load_default()
    except Exception:
        font = None

    for y in range(0, target_height_px, 10):
        if y % 100 == 0:
            tick_len = 30
            label = f"{y} px"
            if font is not None:
                d.text((centerline_x + tick_len + 6, max(0, y - 6)), label, fill=0, font=font)
        elif y % 50 == 0:
            tick_len = 18
        else:
            tick_len = 8
        d.line([(centerline_x, y), (centerline_x + tick_len, y)], fill=0, width=1)

    # Header
    d.text((centerline_x + 80, 10), "DPMM CALIBRATION", fill=0, font=font)
    d.text((centerline_x + 80, 30), "Measure physical length 0->2000 px", fill=0, font=font)

    return img
