from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from printer.render.dither import atkinson_dither

# Body grid for paragraph and list copy. JetBrains Mono Bold @ 18 px is
# rendered through ``supersample_render`` (2× supersample → Atkinson
# dither), which lays down a heavier stroke than a 1-px bitmap font and
# survives the thermal head's tendency to under-print thin lines.
# Monospace at ~11 px per glyph, so the live width (528 px) fits ~48 cols.
BODY_TARGET_SIZE_PX = 18
BODY_GLYPH_PX = 11
# Worst-case line height across body fonts: JB Mono Bold is 24 px at the
# body target size; Noto Sans SC Bold (the CJK fallback) is 26 px. Lock
# 26 px as the body line step so mixed-script lines never overlap.
BODY_LINE_H = 26

# Spleen 8x16 is the mono font for ascii_art ``font: "default"``, where
# char-grid width drives layout — 8 px glyphs fit ~72 cols on a 576 px head
# and common ASCII compositions are sized for that column count.
SPLEEN_8X16_NATIVE_PX = 16

# Spleen 5x8 is a 5×8-cell bitmap, native pixel size 8. Used for ascii_art
# ``font: "small"`` where Spleen 8x16 is too big to fit dense ASCII art
# compositions on a 576 px head (~72 cols at 8 px vs ~115 at 5 px).
SPLEEN_5X8_NATIVE_PX = 8


@lru_cache(maxsize=16)
def _font_cmap_keys(font_path: str) -> frozenset[int]:
    """Return the set of codepoints supported by a TTF/OTF font.

    Cached per absolute font path. Used to decide whether a primary font
    covers each codepoint or whether the fallback font should be used.
    BDF fonts (``mono()``, ``small()``) cannot be inspected this way and
    must not be passed in — they are not used through ``supersample_render``.
    """
    from fontTools.ttLib import TTFont
    return frozenset(TTFont(font_path).getBestCmap().keys())


class FontRegistry:
    """Lazy-loaded font handles for the font families used by the renderer.

    - Body: JetBrains Mono Bold TTF (vector). Reading-size monospace for
      paragraph and list copy, rendered via ``supersample_render`` so
      strokes stay heavy on thermal output.
    - Mono: Spleen 8x16 BDF (bitmap, 16 px native). Tighter monospace
      used where the glyph grid drives layout (ascii_art default).
    - Small: Spleen 5x8 BDF (bitmap, 8 px native). Quarter-size bitmap for
      dense ASCII art compositions.
    - Display: IBM Plex Sans Medium/Bold TTF (vector). Used through
      ``supersample_render`` — rendered at 2× target size, then
      Atkinson-dithered to 1-bit.
    - Code: JetBrains Mono Regular/Bold TTF (vector). Same supersample path
      when used inside display surfaces. ``body()`` returns the same handle
      as ``code(bold=True, size_px=BODY_TARGET_SIZE_PX)``.
    - CJK: Noto Sans SC Regular/Bold OTF (vector). Fallback for codepoints
      missing from the primary font's cmap. Hands off to
      ``supersample_render`` automatically when present.
    """

    def __init__(self, font_dir: str | Path) -> None:
        self._d = Path(font_dir)
        self._body: ImageFont.FreeTypeFont | None = None
        self._mono: ImageFont.FreeTypeFont | None = None
        self._small: ImageFont.FreeTypeFont | None = None
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
        self._noto_sc = {
            "regular": self._d / "noto-sans-sc" / "NotoSansSC-Regular.otf",
            "bold": self._d / "noto-sans-sc" / "NotoSansSC-Bold.otf",
        }

    def body(self) -> ImageFont.FreeTypeFont:
        """JetBrains Mono Bold at the body target size (vector)."""
        if self._body is not None:
            return self._body
        self._body = ImageFont.truetype(str(self._jb["bold"]), size=BODY_TARGET_SIZE_PX)
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

    def cjk(
        self, *, bold: bool = True, size_px: int = BODY_TARGET_SIZE_PX,
    ) -> ImageFont.FreeTypeFont:
        """Noto Sans SC at the requested size — fallback for non-Latin glyphs."""
        key = "bold" if bold else "regular"
        return ImageFont.truetype(str(self._noto_sc[key]), size=size_px)

    def has_cjk_font(self) -> bool:
        return self._noto_sc["regular"].exists() and self._noto_sc["bold"].exists()

    def body_atom_width(self, atom: str) -> int:
        """Pixel width of an atom under the body grid, picking the body
        primary or CJK fallback font based on per-codepoint coverage. Used
        by wrap helpers that need to measure atoms before rendering."""
        primary_keys = _font_cmap_keys(str(self.body().path))
        font = self.body()
        if not all(ord(c) in primary_keys for c in atom) and self.has_cjk_font():
            font = self.cjk(bold=True)
        return int(font.getbbox(atom)[2])


def iter_atoms(text: str, *, fonts: FontRegistry) -> Iterator[str]:
    """Yield wrap-atoms: Latin words, individual non-Latin chars, and
    whitespace runs.

    Latin words break only at whitespace. Codepoints outside the body
    font's cmap (CJK and other non-Latin scripts) break per character so
    spaceless scripts can wrap mid-run.
    """
    primary_keys = _font_cmap_keys(str(fonts.body().path))
    word: list[str] = []
    space: list[str] = []
    for ch in text:
        if ch.isspace():
            if word:
                yield "".join(word)
                word = []
            space.append(ch)
        elif ord(ch) in primary_keys:
            if space:
                yield "".join(space)
                space = []
            word.append(ch)
        else:
            if word:
                yield "".join(word)
                word = []
            if space:
                yield "".join(space)
                space = []
            yield ch
    if word:
        yield "".join(word)
    if space:
        yield "".join(space)


def wrap_body_text(text: str, *, fonts: FontRegistry, max_width_px: int) -> list[str]:
    """Wrap text into lines that fit within ``max_width_px`` when rendered
    through ``render_body_line``.

    Latin words are atomic; CJK and other non-Latin codepoints break per
    character so long Chinese/Japanese runs (which have no inter-word
    whitespace) wrap correctly. Whitespace at line breaks is dropped.
    """
    lines: list[str] = []
    current: list[str] = []
    current_w = 0
    has_text = False  # whether the current line contains any non-whitespace

    def fits(atom: str) -> bool:
        return current_w + fonts.body_atom_width(atom) <= max_width_px

    def push_atom(atom: str) -> None:
        nonlocal current, current_w, has_text
        current.append(atom)
        current_w += fonts.body_atom_width(atom)
        has_text = True

    def break_line() -> None:
        nonlocal current, current_w, has_text
        line = "".join(current).rstrip()
        if line:
            lines.append(line)
        current = []
        current_w = 0
        has_text = False

    for atom in iter_atoms(text, fonts=fonts):
        if atom.isspace():
            if has_text:
                push_atom(atom)
            continue
        if has_text and not fits(atom):
            break_line()
        # An atom may itself exceed the line width (long URL, file path,
        # hash). Slice it into chunks that fit, breaking at codepoint
        # boundaries; the chunks land on consecutive lines.
        if fonts.body_atom_width(atom) > max_width_px:
            chunk_chars: list[str] = []
            for ch in atom:
                trial = "".join(chunk_chars) + ch
                if fonts.body_atom_width(trial) > max_width_px and chunk_chars:
                    push_atom("".join(chunk_chars))
                    break_line()
                    chunk_chars = [ch]
                else:
                    chunk_chars.append(ch)
            if chunk_chars:
                push_atom("".join(chunk_chars))
        else:
            push_atom(atom)

    if current:
        line = "".join(current).rstrip()
        if line:
            lines.append(line)

    return lines or [text]


def _render_single_font(
    *, text, font, target_size_px, max_width_px, color, factor, dither,
):
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

    target_w = max(1, w_big // factor)
    target_h = max(1, h_big // factor)
    img1x = big_img.resize((target_w, target_h), Image.Resampling.LANCZOS)
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


def supersample_render(
    *,
    text: str,
    font: ImageFont.FreeTypeFont,
    target_size_px: int,
    max_width_px: int,
    fallback_font: ImageFont.FreeTypeFont | None = None,
    color: int = 0,
    factor: int = 2,
    dither: str = "atkinson",
) -> Image.Image:
    """Render TTF text at ``factor``× target size to greyscale, then dither
    to 1-bit.

    ``font`` is the primary TTF/OTF handle. ``target_size_px`` is the desired
    output pixel size; the renderer re-instantiates the font at
    ``target_size_px * factor`` for the supersample pass, then downsamples
    via Lanczos and dithers.

    ``fallback_font`` is an optional second TTF/OTF used for codepoints
    missing from the primary's cmap (typically the CJK font). When set, the
    text is split into runs by per-codepoint coverage and each run is
    rendered with its own font; runs are baseline-aligned via
    ``font.getmetrics()`` and composited before the downsample/dither pass.
    Pure-Latin text bypasses the composite path even when the fallback is
    provided.

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
    if fallback_font is None:
        return _render_single_font(
            text=text, font=font, target_size_px=target_size_px,
            max_width_px=max_width_px, color=color, factor=factor, dither=dither,
        )

    primary_keys = _font_cmap_keys(str(font.path))
    if all(ord(c) in primary_keys for c in text):
        return _render_single_font(
            text=text, font=font, target_size_px=target_size_px,
            max_width_px=max_width_px, color=color, factor=factor, dither=dither,
        )

    # Composite path: walk codepoints, group into runs by which font owns
    # each, render each run at supersample size, composite baseline-aligned,
    # then downsample + dither.
    big_size = target_size_px * factor
    big_primary = ImageFont.truetype(font.path, size=big_size)
    big_fallback = ImageFont.truetype(fallback_font.path, size=big_size)

    runs: list[tuple[str, ImageFont.FreeTypeFont]] = []
    run_text: list[str] = []
    run_font: ImageFont.FreeTypeFont | None = None
    for ch in text:
        f = big_primary if ord(ch) in primary_keys else big_fallback
        if f is run_font:
            run_text.append(ch)
        else:
            if run_text:
                runs.append(("".join(run_text), run_font))  # type: ignore[arg-type]
            run_text = [ch]
            run_font = f
    if run_text:
        runs.append(("".join(run_text), run_font))  # type: ignore[arg-type]

    # Render each run onto its own line-metrics canvas, baseline at row=ascent.
    seg_imgs: list[tuple[Image.Image, int]] = []  # (img, ascent)
    max_ascent = 0
    max_descent = 0
    for seg_text, seg_font in runs:
        ascent, descent = seg_font.getmetrics()
        seg_w = max(1, int(seg_font.getbbox(seg_text)[2]))
        seg_h = ascent + descent
        seg_img = Image.new("L", (seg_w, seg_h), 255)
        ImageDraw.Draw(seg_img).text((0, 0), seg_text, font=seg_font, fill=color)
        seg_imgs.append((seg_img, ascent))
        if ascent > max_ascent:
            max_ascent = ascent
        if descent > max_descent:
            max_descent = descent

    canvas_h = max_ascent + max_descent
    canvas_w = sum(s.width for s, _ in seg_imgs)
    canvas = Image.new("L", (canvas_w, canvas_h), 255)
    x = 0
    for seg_img, ascent in seg_imgs:
        canvas.paste(seg_img, (x, max_ascent - ascent))
        x += seg_img.width

    target_w = max(1, canvas_w // factor)
    target_h = max(1, canvas_h // factor)
    img1x = canvas.resize((target_w, target_h), Image.Resampling.LANCZOS)
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


def render_body_line(text: str, *, fonts: FontRegistry, max_width_px: int) -> Image.Image:
    """Render a single line of body copy through the supersample + dither
    path. Empty input is rendered as a single space so callers always get a
    paste-able image whose height matches the body grid. Codepoints outside
    JetBrains Mono Bold's cmap fall back to Noto Sans SC Bold automatically
    when the CJK font is bundled.
    """
    fallback = fonts.cjk(bold=True) if fonts.has_cjk_font() else None
    return supersample_render(
        text=text or " ",
        font=fonts.body(),
        fallback_font=fallback,
        target_size_px=BODY_TARGET_SIZE_PX,
        max_width_px=max_width_px,
    )


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
        Image.Transform.AFFINE,
        (1, shear, -shear * (img.height - 1), 0, 1, 0),
        resample=Image.Resampling.BICUBIC,
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
