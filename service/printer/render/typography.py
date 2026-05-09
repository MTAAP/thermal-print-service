from __future__ import annotations

from pathlib import Path
from typing import Callable

from PIL import Image, ImageDraw, ImageFont

from printer.render.dither import atkinson_dither


def is_cjk_char(char: str) -> bool:
    """Return True if the character is in a CJK Unicode range.

    Covers:
    - CJK Unified Ideographs (U+4E00–U+9FFF) - main Chinese/Japanese/Korean
    - CJK Unified Ideographs Extension A (U+3400–U+4DBF) - rare characters
    - CJK Unified Ideographs Extension B+ (U+20000–U+2A6DF) - very rare
    - CJK Compatibility Ideographs (U+F900–U+FAFF)
    - CJK Radicals/Strokes (U+2E80–U+2FDF)
    - CJK Symbols and Punctuation (U+3000–U+303F)
    - Hiragana (U+3040–U+309F)
    - Katakana (U+30A0–U+30FF)
    - Bopomofo (U+3100–U+312F)
    - Hangul Syllables (U+AC00–U+D7AF)
    - Halfwidth/Fullwidth Forms (U+FF00–U+FFEF)
    """
    cp = ord(char)
    return (
        0x4E00 <= cp <= 0x9FFF  # CJK Unified Ideographs
        or 0x3400 <= cp <= 0x4DBF  # CJK Extension A
        or 0x20000 <= cp <= 0x2A6DF  # CJK Extension B
        or 0xF900 <= cp <= 0xFAFF  # CJK Compatibility
        or 0x2E80 <= cp <= 0x2FDF  # Radicals/Strokes
        or 0x3000 <= cp <= 0x303F  # CJK Symbols and Punctuation
        or 0x3040 <= cp <= 0x309F  # Hiragana
        or 0x30A0 <= cp <= 0x30FF  # Katakana
        or 0x3100 <= cp <= 0x312F  # Bopomofo
        or 0xAC00 <= cp <= 0xD7AF  # Hangul
        or 0xFF00 <= cp <= 0xFFEF  # Halfwidth/Fullwidth Forms
    )


def contains_cjk(text: str) -> bool:
    """Return True if text contains any CJK characters."""
    return any(is_cjk_char(c) for c in text)


def segment_by_script(text: str) -> list[tuple[str, bool]]:
    """Split text into segments of (substring, is_cjk).

    Consecutive characters of the same script type are grouped together.
    Returns a list of (text_segment, is_cjk_segment) tuples.
    """
    if not text:
        return []

    segments: list[tuple[str, bool]] = []
    current_segment: list[str] = []
    current_is_cjk: bool | None = None

    for char in text:
        char_is_cjk = is_cjk_char(char)
        if current_is_cjk is None:
            current_is_cjk = char_is_cjk
        elif char_is_cjk != current_is_cjk:
            segments.append(("".join(current_segment), current_is_cjk))
            current_segment = []
            current_is_cjk = char_is_cjk
        current_segment.append(char)

    if current_segment:
        segments.append(("".join(current_segment), current_is_cjk or False))

    return segments

# Spleen 8x16 is the body font: 8×16-cell bitmap, native pixel size 16.
# Replaced Cozette 13 px in v0.6.0 — Cozette renders dense and crisp but
# requires concentration at arm's length, while Spleen 8x16 is the
# canonical terminal-readable size on thermal output. Glyphs are 8 px
# wide, so a 576 px head fits ~72 cols.
SPLEEN_8X16_NATIVE_PX = 16

# Spleen 5x8 is a 5×8-cell bitmap, native pixel size 8. Used for ascii_art
# ``font: "small"`` where Spleen 8x16 is too big to fit common ASCII art
# compositions on a 576 px head (~72 cols at 8 px vs ~115 at 5 px).
SPLEEN_5X8_NATIVE_PX = 8


class FontRegistry:
    """Lazy-loaded font handles for the font families used by the renderer.

    - Body: Spleen 8x16 BDF (bitmap, 16 px native). Bitmap font — output
      goes straight to the 1-bit canvas, no dither pass.
    - Small: Spleen 5x8 BDF (bitmap, 8 px native). Same family at half size
      for dense ASCII art compositions.
    - Display: IBM Plex Sans Medium/Bold TTF (vector). Used through
      ``supersample_render`` — rendered at 2× target size, then
      Atkinson-dithered to 1-bit.
    - Code: JetBrains Mono Regular/Bold TTF (vector). Same supersample path
      when used inside display surfaces.
    - CJK: Noto Sans SC Regular/Bold TTF (vector). Fallback for Chinese,
      Japanese, Korean characters. Same supersample path as display fonts.
    """

    def __init__(self, font_dir: str | Path) -> None:
        self._d = Path(font_dir)
        self._body: ImageFont.FreeTypeFont | None = None
        self._small: ImageFont.FreeTypeFont | None = None
        self._body_bdf = self._d / "spleen" / "spleen-8x16.bdf"
        self._small_bdf = self._d / "spleen" / "spleen-5x8.bdf"
        self._plex = {
            "medium": self._d / "plex" / "IBMPlexSans-Medium.ttf",
            "bold": self._d / "plex" / "IBMPlexSans-Bold.ttf",
        }
        self._jb = {
            "regular": self._d / "jetbrains-mono" / "JetBrainsMono-Regular.ttf",
            "bold": self._d / "jetbrains-mono" / "JetBrainsMono-Bold.ttf",
        }
        self._noto_sc = {
            "regular": self._d / "noto-sans-sc" / "NotoSansSC-Regular.ttf",
            "bold": self._d / "noto-sans-sc" / "NotoSansSC-Bold.ttf",
        }

    def body(self) -> ImageFont.FreeTypeFont:
        """Spleen 8x16 bitmap font at its native 16 px."""
        if self._body is not None:
            return self._body
        self._body = ImageFont.truetype(str(self._body_bdf), size=SPLEEN_8X16_NATIVE_PX)
        return self._body

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

    def cjk(self, *, bold: bool = False, size_px: int = 16) -> ImageFont.FreeTypeFont:
        """Noto Sans SC for CJK (Chinese/Japanese/Korean) characters."""
        key = "bold" if bold else "regular"
        return ImageFont.truetype(str(self._noto_sc[key]), size=size_px)

    def has_cjk_font(self) -> bool:
        """Return True if CJK font files are available."""
        return (
            self._noto_sc["regular"].exists()
            and self._noto_sc["bold"].exists()
        )


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


def supersample_render_mixed(
    *,
    text: str,
    latin_font: ImageFont.FreeTypeFont,
    cjk_font: ImageFont.FreeTypeFont,
    target_size_px: int,
    max_width_px: int,
    color: int = 0,
    factor: int = 2,
    dither: str = "atkinson",
) -> Image.Image:
    """Render mixed Latin/CJK text using appropriate fonts for each segment.

    Text is segmented by script: Latin characters use ``latin_font``,
    CJK characters use ``cjk_font``. Each segment is rendered and the
    results are horizontally concatenated.

    Parameters are the same as ``supersample_render``, with the addition
    of separate font handles for each script type.
    """
    segments = segment_by_script(text)
    if not segments:
        # Empty text — return a minimal 1-bit image
        return Image.new("1", (1, 1), 1)

    # If there's only one segment and no CJK, use the simple path
    if len(segments) == 1 and not segments[0][1]:
        return supersample_render(
            text=text,
            font=latin_font,
            target_size_px=target_size_px,
            max_width_px=max_width_px,
            color=color,
            factor=factor,
            dither=dither,
        )

    # Render each segment separately at supersample size
    rendered_segments: list[Image.Image] = []
    for segment_text, is_cjk in segments:
        font = cjk_font if is_cjk else latin_font
        try:
            big_font = ImageFont.truetype(font.path, size=target_size_px * factor)
        except Exception:
            big_font = font

        bbox = big_font.getbbox(segment_text)
        w_big = max(1, int(bbox[2] - bbox[0]))
        h_big = max(1, int(bbox[3] - bbox[1]))
        big_img = Image.new("L", (w_big, h_big), 255)
        d = ImageDraw.Draw(big_img)
        d.text((-bbox[0], -bbox[1]), segment_text, font=big_font, fill=color)

        # Downsample to 1× target
        target_w = max(1, w_big // factor)
        target_h = max(1, h_big // factor)
        img1x = big_img.resize((target_w, target_h), Image.Resampling.LANCZOS)
        rendered_segments.append(img1x)

    # Combine segments horizontally, aligning baselines
    # Use the tallest segment height as the canvas height
    max_h = max(seg.height for seg in rendered_segments)
    total_w = sum(seg.width for seg in rendered_segments)

    # Create combined greyscale image
    combined = Image.new("L", (total_w, max_h), 255)
    x_offset = 0
    for seg in rendered_segments:
        # Vertically center each segment (baseline alignment approximation)
        y_offset = max_h - seg.height
        combined.paste(seg, (x_offset, y_offset))
        x_offset += seg.width

    # Cap horizontal width if needed
    if combined.width > max_width_px:
        scale = max_width_px / combined.width
        combined = combined.resize(
            (max_width_px, max(1, int(combined.height * scale))),
            Image.Resampling.LANCZOS,
        )

    # Dither to 1-bit
    if dither == "ordered":
        from printer.render.dither import ordered_dither
        return ordered_dither(combined)
    return atkinson_dither(combined)


def render_body_text_mixed(
    *,
    text: str,
    body_font: ImageFont.FreeTypeFont,
    cjk_font: ImageFont.FreeTypeFont,
    body_height_px: int = SPLEEN_8X16_NATIVE_PX,
) -> Image.Image:
    """Render body text with mixed Latin (bitmap) and CJK (vector) fonts.

    Latin characters are rendered directly with the bitmap body font.
    CJK characters are rendered with the CJK font at a matching size,
    supersampled 2× and Atkinson-dithered.

    Returns a 1-bit image of the rendered text.
    """
    segments = segment_by_script(text)
    if not segments:
        return Image.new("1", (1, body_height_px), 1)

    # If no CJK, render directly with body font
    if all(not is_cjk for _, is_cjk in segments):
        bbox = body_font.getbbox(text)
        w = max(1, int(bbox[2] - bbox[0]))
        h = max(1, int(bbox[3] - bbox[1]))
        img = Image.new("1", (w, h), 1)
        d = ImageDraw.Draw(img)
        d.text((-bbox[0], -bbox[1]), text, font=body_font, fill=0)
        return img

    # Mixed rendering: render each segment with appropriate font
    rendered_segments: list[Image.Image] = []
    for segment_text, is_cjk in segments:
        if is_cjk:
            # Render CJK with vector font, supersampled
            factor = 2
            try:
                big_font = ImageFont.truetype(cjk_font.path, size=body_height_px * factor)
            except Exception:
                big_font = cjk_font

            bbox = big_font.getbbox(segment_text)
            w_big = max(1, int(bbox[2] - bbox[0]))
            h_big = max(1, int(bbox[3] - bbox[1]))
            big_img = Image.new("L", (w_big, h_big), 255)
            d = ImageDraw.Draw(big_img)
            d.text((-bbox[0], -bbox[1]), segment_text, font=big_font, fill=0)

            # Downsample and dither
            target_w = max(1, w_big // factor)
            target_h = max(1, h_big // factor)
            img1x = big_img.resize((target_w, target_h), Image.Resampling.LANCZOS)
            seg_img = atkinson_dither(img1x)
        else:
            # Render Latin with bitmap font directly to 1-bit
            bbox = body_font.getbbox(segment_text)
            w = max(1, int(bbox[2] - bbox[0]))
            h = max(1, int(bbox[3] - bbox[1]))
            seg_img = Image.new("1", (w, h), 1)
            d = ImageDraw.Draw(seg_img)
            d.text((-bbox[0], -bbox[1]), segment_text, font=body_font, fill=0)

        rendered_segments.append(seg_img)

    # Combine segments horizontally with baseline alignment
    max_h = max(seg.height for seg in rendered_segments)
    total_w = sum(seg.width for seg in rendered_segments)

    combined = Image.new("1", (total_w, max_h), 1)
    x_offset = 0
    for seg in rendered_segments:
        # Bottom-align segments for baseline approximation
        y_offset = max_h - seg.height
        combined.paste(seg, (x_offset, y_offset))
        x_offset += seg.width

    return combined


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
