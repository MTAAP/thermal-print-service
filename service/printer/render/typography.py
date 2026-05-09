from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from printer.render.dither import atkinson_dither

# Spleen 12x24 is the body font: 12×24-cell bitmap, native pixel size 24.
# Bumped from Spleen 8x16 in v0.7.0 — 8x16 reads small at arm's length on
# 80mm thermal stock, and the 1.5× step to 12x24 lands at the next native
# Spleen size with no scaling artefacts. Glyphs are 12 px wide, so a 576 px
# head fits ~48 cols across the live width (528 px / 12 = 44).
SPLEEN_12X24_NATIVE_PX = 24

# Spleen 8x16 is retained for ascii_art ``font: "default"``, where char-grid
# width matters for layout — 8 px glyphs fit ~72 cols on a 576 px head, and
# common ASCII compositions are sized for that column count.
SPLEEN_8X16_NATIVE_PX = 16

# Spleen 5x8 is a 5×8-cell bitmap, native pixel size 8. Used for ascii_art
# ``font: "small"`` where Spleen 8x16 is too big to fit dense ASCII art
# compositions on a 576 px head (~72 cols at 8 px vs ~115 at 5 px).
SPLEEN_5X8_NATIVE_PX = 8


class FontRegistry:
    """Lazy-loaded font handles for the four families used by the renderer.

    - Body: Spleen 12x24 BDF (bitmap, 24 px native). Reading-size monospace
      for paragraph and list copy. Bitmap output goes straight to the 1-bit
      canvas, no dither pass.
    - Mono: Spleen 8x16 BDF (bitmap, 16 px native). Tighter monospace used
      where the glyph grid drives layout (ascii_art default).
    - Small: Spleen 5x8 BDF (bitmap, 8 px native). Same family at quarter
      size for dense ASCII art compositions.
    - Display: IBM Plex Sans Medium/Bold TTF (vector). Used through
      ``supersample_render`` — rendered at 2× target size, then
      Atkinson-dithered to 1-bit.
    - Code: JetBrains Mono Regular/Bold TTF (vector). Same supersample path
      when used inside display surfaces.
    """

    def __init__(self, font_dir: str | Path) -> None:
        self._d = Path(font_dir)
        self._body: ImageFont.FreeTypeFont | None = None
        self._mono: ImageFont.FreeTypeFont | None = None
        self._small: ImageFont.FreeTypeFont | None = None
        self._body_bdf = self._d / "spleen" / "spleen-12x24.bdf"
        self._mono_bdf = self._d / "spleen" / "spleen-8x16.bdf"
        self._small_bdf = self._d / "spleen" / "spleen-5x8.bdf"
        self._plex = {
            "medium": self._d / "plex" / "IBMPlexSans-Medium.ttf",
            "bold": self._d / "plex" / "IBMPlexSans-Bold.ttf",
        }
        self._jb = {
            "regular": self._d / "jetbrains-mono" / "JetBrainsMono-Regular.ttf",
            "bold": self._d / "jetbrains-mono" / "JetBrainsMono-Bold.ttf",
        }

    def body(self) -> ImageFont.FreeTypeFont:
        """Spleen 12x24 bitmap font at its native 24 px."""
        if self._body is not None:
            return self._body
        self._body = ImageFont.truetype(str(self._body_bdf), size=SPLEEN_12X24_NATIVE_PX)
        return self._body

    def mono(self) -> ImageFont.FreeTypeFont:
        """Spleen 8x16 bitmap font at its native 16 px."""
        if self._mono is not None:
            return self._mono
        self._mono = ImageFont.truetype(str(self._mono_bdf), size=SPLEEN_8X16_NATIVE_PX)
        return self._mono

    def small(self) -> ImageFont.FreeTypeFont:
        """Spleen 5x8 bitmap font at its native 8 px."""
        if self._small is not None:
            return self._small
        self._small = ImageFont.truetype(str(self._small_bdf), size=SPLEEN_5X8_NATIVE_PX)
        return self._small

    def display(self, *, weight: str, size_px: int = 32) -> ImageFont.FreeTypeFont:
        path = self._plex.get(weight)
        if path is None:
            raise ValueError(f"unknown plex weight {weight!r}")
        return ImageFont.truetype(str(path), size=size_px)

    def code(self, *, bold: bool = False, size_px: int = 18) -> ImageFont.FreeTypeFont:
        key = "bold" if bold else "regular"
        return ImageFont.truetype(str(self._jb[key]), size=size_px)


def supersample_render(
    *,
    text: str,
    font: ImageFont.FreeTypeFont,
    target_size_px: int,
    max_width_px: int,
    color: int = 0,
    factor: int = 2,
    dither: str = "atkinson",
) -> Image.Image:
    """Render TTF text at ``factor``× target size to greyscale, then dither
    to 1-bit.

    ``font`` should be a TTF font handle. ``target_size_px`` is the desired
    output pixel size; the renderer re-instantiates the font at
    ``target_size_px * factor`` for the supersample pass, then downsamples
    via Lanczos and dithers.

    ``factor=2, dither="atkinson"`` is the default for body display text —
    it preserves the lighter-weight character of Plex Sans Medium/Bold.
    Heavier surfaces (drop caps, code blocks) benefit from
    ``factor=4, dither="ordered"`` because:

    - 4× supersample carries more luminance into each output pixel, so the
      Lanczos pass produces a richer mid-grey before the threshold.
    - Ordered (Bayer 8x8) dither preserves large solid regions where
      Atkinson would shed too much error and thin them.

    ``max_width_px`` caps horizontal extent; long text is scaled to fit
    preserving aspect ratio.
    """
    try:
        big_font = ImageFont.truetype(font.path, size=target_size_px * factor)
    except Exception:
        big_font = font

    bbox = big_font.getbbox(text)
    w_big = max(1, int(bbox[2] - bbox[0]))
    h_big = max(1, int(bbox[3] - bbox[1]))
    big_img = Image.new("L", (w_big, h_big), 255)
    d = ImageDraw.Draw(big_img)
    d.text((-bbox[0], -bbox[1]), text, font=big_font, fill=color)

    # Downsample to 1× target.
    target_w = max(1, w_big // factor)
    target_h = max(1, h_big // factor)
    img1x = big_img.resize((target_w, target_h), Image.Resampling.LANCZOS)

    # Cap horizontal width if the text overflows.
    if img1x.width > max_width_px:
        scale = max_width_px / img1x.width
        img1x = img1x.resize(
            (max_width_px, max(1, int(img1x.height * scale))),
            Image.Resampling.LANCZOS,
        )

    if dither == "ordered":
        from printer.render.dither import ordered_dither
        return ordered_dither(img1x)
    return atkinson_dither(img1x)


# Synthetic italic shear angle. ~12° matches typical "oblique" faces and is
# the conventional default when a font has no real italic cut. Larger angles
# look melodramatic at receipt sizes; smaller angles read as a misalignment.
_ITALIC_SHEAR = 0.21  # tan(12°) ≈ 0.2126


def apply_italic(img: Image.Image, shear: float = _ITALIC_SHEAR) -> Image.Image:
    """Synthetic-slant a 1-bit image. Bottom row stays anchored, top row
    shifts right by ``shear * (height - 1)``. Output canvas is wider by that
    amount; the original height is preserved.
    """
    if img.height <= 0 or img.width <= 0:
        return img
    extra = int(round(shear * (img.height - 1)))
    if extra <= 0:
        return img
    new_w = img.width + extra
    # PIL's "1"-mode AFFINE transform is grainy because it can't anti-alias on
    # binary input. Convert to greyscale, shear with bicubic resampling, then
    # threshold back to 1-bit. Edge antialiasing is lost on the thermal head
    # anyway (8 dots/mm, no subpixel) so the threshold is fine.
    grey = img.convert("L")
    sheared = grey.transform(
        (new_w, img.height),
        Image.AFFINE,
        (1, shear, -shear * (img.height - 1), 0, 1, 0),
        resample=Image.BICUBIC,
        fillcolor=255,
    )
    return sheared.point(lambda v: 0 if v < 128 else 255).convert("1")


def apply_underline(img: Image.Image, *, gap: int = 1, thickness: int = 1) -> Image.Image:
    """Draw a horizontal rule under a 1-bit fragment. Output is taller by
    ``gap + thickness``; width is unchanged. The rule is axis-aligned even
    on italics — slanted underlines under thermal-print sizes read as
    smudges, not styling.
    """
    if img.width <= 0 or img.height <= 0:
        return img
    extra = gap + thickness
    canvas = Image.new("1", (img.width, img.height + extra), 1)
    canvas.paste(img, (0, 0))
    d = ImageDraw.Draw(canvas)
    y = img.height + gap
    d.rectangle([0, y, img.width - 1, y + thickness - 1], fill=0)
    return canvas
