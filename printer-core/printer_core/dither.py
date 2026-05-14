"""Dither algorithms for thermal output.

Single source of truth for both ``service/`` (Pi-side renderer) and
``design/`` (laptop-side HTML compiler). Anything that converts grayscale
to 1-bit for the thermal head should import from here.
"""

from __future__ import annotations

from PIL import Image


def atkinson_dither(image: Image.Image, *, threshold: int = 128) -> Image.Image:
    """Atkinson dither — distributes 1/8 of error to each of 6 neighbors.

    The 6/8 = 0.75 propagation (vs. 1.0 in Floyd-Steinberg) preserves more of
    the local greyscale character; large flat regions shed less error and stay
    clean. This is what gives display-font output its weighted, semi-soft edge
    rather than the harsh on/off look of pure thresholding.
    """
    if image.mode != "L":
        image = image.convert("L")
    px = image.load()
    assert px is not None  # L-mode images always provide pixel access
    w, h = image.size
    for y in range(h):
        for x in range(w):
            old = int(px[x, y])  # type: ignore[arg-type]  # L-mode returns int
            new = 0 if old < threshold else 255
            px[x, y] = new
            err = (old - new) // 8
            for dx, dy in ((1, 0), (2, 0), (-1, 1), (0, 1), (1, 1), (0, 2)):
                nx, ny = x + dx, y + dy
                if 0 <= nx < w and 0 <= ny < h:
                    cur = int(px[nx, ny])  # type: ignore[arg-type]  # L-mode returns int
                    px[nx, ny] = max(0, min(255, cur + err))
    return image.convert("1")


def floyd_steinberg(image: Image.Image) -> Image.Image:
    return image.convert("L").convert("1", dither=Image.Dither.FLOYDSTEINBERG)


# Bayer 8x8 threshold map. Values 0..63, normalized to 0..255 via
# ``(v + 1) * 256 / 65`` so the cell at the brightest threshold (63) maps to
# 252 and the darkest (0) to 4 — every cell sits strictly inside (0, 255),
# which gives uniform grey ramps a clean dither without solid bands at the
# extremes.
_BAYER_8 = (
    (0, 32, 8, 40, 2, 34, 10, 42),
    (48, 16, 56, 24, 50, 18, 58, 26),
    (12, 44, 4, 36, 14, 46, 6, 38),
    (60, 28, 52, 20, 62, 30, 54, 22),
    (3, 35, 11, 43, 1, 33, 9, 41),
    (51, 19, 59, 27, 49, 17, 57, 25),
    (15, 47, 7, 39, 13, 45, 5, 37),
    (63, 31, 55, 23, 61, 29, 53, 21),
)
_BAYER_THRESH = tuple(
    tuple(int((v + 1) * 256 / 65) for v in row) for row in _BAYER_8
)


def ordered_dither(image: Image.Image) -> Image.Image:
    """Bayer 8x8 ordered dither.

    Per-pixel threshold from the matrix above; output is 1-bit. Unlike
    error-diffusion (Atkinson/Floyd-Steinberg), ordered dither is purely
    local: every pixel's decision depends only on its (x, y) position
    modulo 8 and its grey value. That makes uniform ramps tile cleanly
    instead of forming horizontal stripes — the failure mode Atkinson
    shows on ``gradient_band``.
    """
    grey = image.convert("L")
    px = grey.load()
    assert px is not None
    w, h = grey.size
    for y in range(h):
        row_thresh = _BAYER_THRESH[y % 8]
        for x in range(w):
            v = int(px[x, y])  # type: ignore[arg-type]
            t = row_thresh[x % 8]
            px[x, y] = 0 if v < t else 255
    return grey.convert("1")


def no_dither(image: Image.Image) -> Image.Image:
    return image.convert("L").point(lambda v: 0 if v < 128 else 255).convert("1")


DITHERS = {
    "atkinson": atkinson_dither,
    "floyd_steinberg": floyd_steinberg,
    "ordered": ordered_dither,
    "none": no_dither,
}
