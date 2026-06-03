"""Unit tests for _trim_trailing_white.

Direct algorithm tests (no Chromium round-trip) so the regression
guards stay fast and stable.
"""
from PIL import Image, ImageDraw

from tprint_design.compile import _trim_trailing_white


def _blank(width: int = 576, height: int = 400) -> Image.Image:
    img = Image.new("1", (width, height), 1)  # 1 = white in mode "1"
    return img


def _draw_filled_band(img: Image.Image, top: int, bottom: int) -> None:
    """Fill rows top..bottom (inclusive) with black across the full width."""
    d = ImageDraw.Draw(img)
    d.rectangle([0, top, img.width - 1, bottom], fill=0)


def _draw_sparse_band(img: Image.Image, top: int, bottom: int,
                      pixels_per_row: int = 6) -> None:
    """Fill rows top..bottom with `pixels_per_row` black pixels each.

    Simulates a caption line: enough ink per row to clear the trim
    density threshold but not a dense block.
    """
    d = ImageDraw.Draw(img)
    for y in range(top, bottom + 1):
        for k in range(pixels_per_row):
            d.point((10 + k * 5, y), fill=0)


def test_trim_preserves_sparse_caption_past_internal_whitespace_gap():
    """Regression: dense block + whitespace gap + sparse trailing caption
    must keep the caption. The pre-fix algorithm walked bottom-up looking
    for 16 consecutive ink-bearing rows, found the gap above the dense
    block, and cropped at the dense block's bottom — dropping the caption.
    """
    img = _blank(height=400)
    _draw_filled_band(img, 200, 299)   # dense block
    # rows 300..304: whitespace gap
    _draw_sparse_band(img, 305, 314)   # sparse caption (10 rows, 6 px each)
    # rows 315..399: trailing whitespace

    trimmed = _trim_trailing_white(img)

    # The bottom of the caption (row 314) must survive.
    assert trimmed.height >= 315, (
        f"trim cut into the caption: height={trimmed.height}, expected >= 315"
    )
    # And we should still trim away the trailing whitespace beyond the caption.
    assert trimmed.height < 400, "trim left trailing whitespace"


def test_trim_filters_single_pixel_dither_speckle():
    """A lone speckle in trailing whitespace must NOT extend the page —
    the density threshold filters it out."""
    img = _blank(height=400)
    _draw_filled_band(img, 100, 199)   # real content
    # rows 200..399: whitespace, plus a single stray pixel at (50, 380)
    ImageDraw.Draw(img).point((50, 380), fill=0)

    trimmed = _trim_trailing_white(img)

    # The speckle (1 pixel) shouldn't count as meaningful content.
    # Trim should land near row 199 (bottom of real content), not row 380.
    assert trimmed.height <= 220, (
        f"single-pixel speckle survived trim: height={trimmed.height}"
    )
    # And the real content must survive.
    assert trimmed.height >= 200, "trim cut into real content"


def test_trim_respects_floor_for_short_content():
    """An image with content above the 80-px floor stays at floor height."""
    img = _blank(height=200)
    _draw_filled_band(img, 10, 30)   # tiny content
    trimmed = _trim_trailing_white(img)
    assert trimmed.height == 80, (
        f"floor not enforced: height={trimmed.height}"
    )


def test_trim_returns_input_when_already_under_floor():
    """If the input is already shorter than the floor, trim is a no-op."""
    img = _blank(height=50)
    _draw_filled_band(img, 5, 15)
    trimmed = _trim_trailing_white(img)
    assert trimmed.height == 50


def test_trim_handles_all_white_input():
    """All-white input falls through to the any-ink fallback (which finds
    nothing) and bottoms out at the floor."""
    img = _blank(height=300)
    trimmed = _trim_trailing_white(img)
    assert trimmed.height == 80


def test_trim_preserves_content_at_bottom_edge():
    """Content that runs all the way to the bottom row must not be cut."""
    img = _blank(height=300)
    _draw_filled_band(img, 100, 299)
    trimmed = _trim_trailing_white(img)
    assert trimmed.height == 300, (
        f"bottom-edge content cut: height={trimmed.height}"
    )
