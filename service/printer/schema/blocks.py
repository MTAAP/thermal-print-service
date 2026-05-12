from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

# ----- align allow-list (spec §6) -----
ALIGN_ALLOWED: set[str] = {
    "header", "section_title", "paragraph", "rich_text",
    "large_text", "pull_quote", "footer", "image",
}


class _Block(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _AlignableBlock(_Block):
    align: Literal["left", "center", "right"] = "left"


# ===== Text & structure =====


class HeaderBlock(_AlignableBlock):
    type: Literal["header"]
    text: str = Field(min_length=1, max_length=200, description="Title text.")
    subtitle: str | None = Field(
        default=None, max_length=200,
        description=(
            "Optional subtitle line rendered below the title in a smaller "
            "display weight."
        ),
    )
    style: Literal["inverse_band", "ornamental", "minimal"] = Field(
        default="inverse_band",
        description=(
            "inverse_band: white-on-black title band (loudest, default). "
            "ornamental: title flanked by decorative ornaments — formal, "
            "literary. minimal: title above a hairline rule — understated, "
            "modern."
        ),
    )


class SectionTitleBlock(_AlignableBlock):
    type: Literal["section_title"]
    text: str = Field(min_length=1, max_length=200, description="Title text.")
    style: Literal["underline", "inverse", "rule_above"] = Field(
        default="underline",
        description=(
            "underline: title above a 2 px rule (default, neutral). "
            "inverse: white-on-black band at section weight (loud divider). "
            "rule_above: thin rule above the title (chapter-style)."
        ),
    )


class ParagraphBlock(_AlignableBlock):
    type: Literal["paragraph"]
    text: str = Field(
        min_length=1, max_length=4000,
        description="Paragraph copy. Long text wraps.",
    )
    emphasis: Literal["italic", "bold"] | None = Field(
        default=None,
        description=(
            "Whole-paragraph emphasis. For mixed emphasis within a paragraph "
            "use rich_text (italic / bold runs)."
        ),
    )


class RichTextRun(_Block):
    text: str = Field(min_length=1, max_length=2000)
    bold: bool = False
    italic: bool = False
    inverse: bool = False
    underline: bool = False
    size: Literal["sm", "md", "lg"] = Field(
        default="md",
        description=(
            "sm: ~14 px footnote weight. md: 18 px body weight (default). "
            "lg: 28 px subhead weight. Mixed sizes share a baseline within "
            "a line."
        ),
    )


class RichTextBlock(_AlignableBlock):
    type: Literal["rich_text"]
    runs: list[RichTextRun] = Field(min_length=1, max_length=64)


class LargeTextBlock(_AlignableBlock):
    type: Literal["large_text"]
    text: str = Field(min_length=1, max_length=200)
    size: Literal["xl", "xxl", "xxxl"] = Field(
        default="xxl",
        description=(
            "xl: 48 px / ~6 mm cap-height (sub-banner). "
            "xxl: 80 px / ~10 mm (banner, default). "
            "xxxl: 128 px / ~16 mm (huge poster banner)."
        ),
    )


class CodeBlock(_Block):
    type: Literal["code"]
    text: str = Field(
        min_length=1, max_length=8000,
        description="Monospaced code/log content. Preserves newlines.",
    )
    size: Literal["sm", "md", "lg"] = Field(
        default="md",
        description=(
            "sm: 14 px (compact). md: 16 px (default, thermal-safe). "
            "lg: 18 px (emphasized)."
        ),
    )


class PullQuoteBlock(_AlignableBlock):
    type: Literal["pull_quote"]
    text: str = Field(
        min_length=1, max_length=2000,
        description="The quoted text.",
    )
    attribution: str | None = Field(
        default=None, max_length=200,
        description=(
            "Optional attribution line, rendered smaller below the quote "
            "with an em-dash prefix."
        ),
    )


class DropCapBlock(_Block):
    type: Literal["drop_cap"]
    first_letter: str = Field(
        min_length=1, max_length=3,
        description=(
            "Initial letter(s) rendered ~3 lines tall (typographic incipit). "
            "Use 1 char ('T') for a classic drop cap; 2–3 chars ('The') for "
            "a literary opener."
        ),
    )
    rest: str = Field(
        min_length=1, max_length=4000,
        description="Body of the paragraph that wraps around the drop cap.",
    )


class FooterBlock(_AlignableBlock):
    type: Literal["footer"]
    text: str = Field(
        min_length=1, max_length=200,
        description="Footer line, centered, in display bold.",
    )


# ===== Literary frame =====


class EpigraphBlock(_Block):
    type: Literal["epigraph"]
    text: str = Field(
        min_length=1, max_length=2000,
        description=(
            "Short quoted opening (chapter epigraph or piece opener). "
            "Quieter than pull_quote: italic, indented both sides, no bar."
        ),
    )
    attribution: str | None = Field(
        default=None, max_length=200,
        description=(
            "Optional source. Rendered right-aligned beneath the text in "
            "italic 13 px with an em-dash prefix."
        ),
    )


class BylineBlock(_Block):
    type: Literal["byline"]
    text: str = Field(
        min_length=1, max_length=100,
        description=(
            "Author credit rendered in italic 14 px. Agent decides "
            "wording ('Tim Kraus' / 'by Tim Kraus' / 'T. Kraus')."
        ),
    )


class DatelineBlock(_Block):
    type: Literal["dateline"]
    location: str = Field(
        min_length=1, max_length=60,
        description="Place name. Uppercased at render time.",
    )
    date: str = Field(
        min_length=1, max_length=60,
        description=(
            "Date string. Format is the agent's choice "
            "('May 12' / 'May 12, 2026' / '5/12/26'); renderer "
            "uppercases the result."
        ),
    )


class SalutationBlock(_Block):
    type: Literal["salutation"]
    text: str = Field(
        min_length=1, max_length=120,
        description=(
            "Opening salutation for correspondence ('Dear Sam,'). "
            "Rendered at body size with extra breathing room below."
        ),
    )


class SignatureBlock(_Block):
    type: Literal["signature"]
    name: str = Field(
        min_length=1, max_length=80,
        description=(
            "Signer's name. Rendered italic 18 px right-aligned with "
            "an em-dash prefix."
        ),
    )
    closing: str | None = Field(
        default=None, max_length=80,
        description=(
            "Optional closing line ('Yours,' / 'Warmly,'). Rendered on "
            "its own line above the name, also right-aligned italic."
        ),
    )


class ColophonBlock(_Block):
    type: Literal["colophon"]
    text: str = Field(
        min_length=1, max_length=500,
        description=(
            "End-matter production note. Italic 14 px centered in a "
            "narrow column."
        ),
    )


class AddressBlock(_Block):
    type: Literal["address"]
    lines: list[
        Annotated[str, StringConstraints(min_length=1, max_length=100)]
    ] = Field(
        min_length=1, max_length=8,
        description=(
            "1 to 8 lines, order preserved, rendered tightly (~22 px "
            "per line) in 16 px Plex Medium left-aligned."
        ),
    )


# ===== Lists & data =====


class ChecklistBlock(_Block):
    type: Literal["checklist"]
    items: list[str] = Field(
        min_length=1, max_length=64,
        description="Items rendered with an unchecked square box.",
    )


class BulletsBlock(_Block):
    type: Literal["bullets"]
    items: list[str] = Field(
        min_length=1, max_length=64,
        description="Bullet items.",
    )
    marker: Literal["•", "—", "▸"] = Field(
        default="•",
        description=(
            "Bullet marker glyph. • round bullet (default). — em-dash "
            "(literary). ▸ triangle (technical)."
        ),
    )


class NumberedBlock(_Block):
    type: Literal["numbered"]
    items: list[str] = Field(
        min_length=1, max_length=64,
        description="Items, numbered 1..N.",
    )


class KvPair(_Block):
    key: str = Field(
        min_length=1, max_length=100,
        description="Label (rendered proportional).",
    )
    value: str = Field(
        min_length=0, max_length=200,
        description="Value (rendered monospaced for alignment).",
    )


class KvBlock(_Block):
    type: Literal["kv"]
    pairs: list[KvPair] = Field(min_length=1, max_length=64)


class TableCompactBlock(_Block):
    type: Literal["table_compact"]
    rows: list[list[str]] = Field(min_length=1, max_length=64)
    headers: list[str] | None = None

    @model_validator(mode="after")
    def _column_count(self):
        cols = len(self.rows[0])
        if cols < 2 or cols > 3:
            raise ValueError("table_compact requires 2 or 3 columns")
        for r in self.rows:
            if len(r) != cols:
                raise ValueError("all rows must have the same column count")
        if self.headers is not None and len(self.headers) != cols:
            raise ValueError("headers must match column count")
        return self


# ===== Visual & decorative =====


class RuleBlock(_Block):
    type: Literal["rule"]
    style: Literal["solid", "dashed", "dotted", "double", "wave"] = Field(
        default="solid",
        description=(
            "Horizontal rule style. solid (2 px, default), dashed (perforation "
            "hint), dotted (quietest), double (important break), wave "
            "(decorative)."
        ),
    )


class OrnamentBlock(_Block):
    type: Literal["ornament"]
    pattern: Literal[
        "stars", "diamonds", "leaves", "geometric",
        "waves", "art_deco", "minimal_dots",
    ] = Field(
        default="stars",
        description=(
            "Decorative band. stars (★), diamonds (◆), leaves (❀), "
            "geometric (■□), waves (～), art_deco (◆◇), "
            "minimal_dots (· · ·). Use sparingly — one ornament per print."
        ),
    )


class SpacerBlock(_Block):
    type: Literal["spacer"]
    lines: int = Field(
        ge=1, le=10,
        description=(
            "Number of body-text line-heights of vertical white space "
            "(1 line ≈ 3.25 mm)."
        ),
    )


class GradientBandBlock(_Block):
    type: Literal["gradient_band"]
    direction: Literal["down", "up"] = Field(
        default="down",
        description=(
            "Fade direction. down: black at top fading to white. "
            "up: reversed."
        ),
    )


class ProgressBarBlock(_Block):
    type: Literal["progress_bar"]
    value: float = Field(
        ge=0.0, le=1.0,
        description="Filled fraction, 0.0–1.0.",
    )
    label: str | None = Field(
        default=None, max_length=80,
        description=(
            "Optional label rendered above the bar. Percentage is appended "
            "automatically."
        ),
    )


class SparklineBlock(_Block):
    type: Literal["sparkline"]
    values: list[float] = Field(
        min_length=2, max_length=200,
        description="Numeric series rendered as a small bar chart.",
    )
    label: str | None = Field(
        default=None, max_length=80,
        description="Optional label rendered above the sparkline.",
    )


# ===== Embedded objects =====


class QrBlock(_Block):
    type: Literal["qr"]
    data: str = Field(
        min_length=1, max_length=2000,
        description="Payload encoded into the QR (URL, text, etc.).",
    )
    caption: str | None = Field(
        default=None, max_length=120,
        description="Optional caption rendered below the QR, centered.",
    )
    size: Literal["sm", "md", "lg"] = Field(
        default="md",
        description=(
            "sm: 192 px / 24 mm (inline). md: 320 px / 40 mm (default). "
            "lg: 480 px / 60 mm (prominent)."
        ),
    )


class BarcodeBlock(_Block):
    type: Literal["barcode"]
    data: str = Field(
        min_length=1, max_length=200,
        description="Barcode payload (format-specific rules apply).",
    )
    format: Literal["CODE128", "EAN13", "EAN8", "UPCA"] = Field(
        default="CODE128",
        description=(
            "Barcode symbology. CODE128 is the general-purpose default."
        ),
    )


class ImageBlock(_AlignableBlock):
    type: Literal["image"]
    png_base64: str = Field(
        min_length=1,
        description=(
            "Base64-encoded PNG. Whitespace and newlines are tolerated."
        ),
    )
    width_px: int = Field(
        default=528, ge=1, le=528,
        description=(
            "Display width in pixels (max 528 = live area). Ignored if "
            "bleed=true."
        ),
    )
    bleed: bool = Field(
        default=False,
        description=(
            "When true, the image covers the full 576 px print head "
            "(edge to edge)."
        ),
    )
    dither: Literal["atkinson", "floyd_steinberg", "ordered", "none"] = Field(
        default="atkinson",
        description=(
            "atkinson: best for photos (default). floyd_steinberg: noisier, "
            "good for gradients. ordered: clean for solid regions. none: "
            "hard threshold."
        ),
    )
    caption: str | None = Field(
        default=None, max_length=120,
        description="Optional caption rendered below the image, centered.",
    )

    @model_validator(mode="after")
    def _bleed_no_align(self):
        # Bleed images cover the full print head — alignment is meaningless.
        if self.bleed and self.align != "left":
            raise ValueError("image with bleed=true must not specify align")
        return self


class AsciiArtBlock(_Block):
    type: Literal["ascii_art"]
    text: str = Field(
        min_length=1, max_length=8000,
        description="Pre-formatted monospaced art. Newlines preserved.",
    )
    font: Literal["default", "small"] = Field(
        default="default",
        description=(
            "default: Spleen 8×16 (~72 cols). small: Spleen 5×8 (~115 cols, "
            "for dense art)."
        ),
    )


# ===== Flow control =====


class TearHereBlock(_Block):
    type: Literal["tear_here"]
    label: str | None = Field(
        default=None, max_length=80,
        description="Optional label rendered above the tear line.",
    )


class CutBlock(_Block):
    type: Literal["cut"]


class FeedBlock(_Block):
    type: Literal["feed"]
    lines: int = Field(
        ge=1, le=20,
        description=(
            "Blank lines of paper to feed (each ≈ 1.75 mm). Use spacer for "
            "in-document whitespace; feed is for pre-cut paper-feed control."
        ),
    )


AnyBlock = (
    HeaderBlock | SectionTitleBlock | ParagraphBlock | RichTextBlock
    | LargeTextBlock | CodeBlock | PullQuoteBlock | DropCapBlock | FooterBlock
    | EpigraphBlock | BylineBlock | DatelineBlock | SalutationBlock
    | SignatureBlock | ColophonBlock | AddressBlock
    | ChecklistBlock | BulletsBlock | NumberedBlock | KvBlock | TableCompactBlock
    | RuleBlock | OrnamentBlock | SpacerBlock | GradientBandBlock
    | ProgressBarBlock | SparklineBlock
    | QrBlock | BarcodeBlock | ImageBlock | AsciiArtBlock
    | TearHereBlock | CutBlock | FeedBlock
)


def block_type_names() -> list[str]:
    return [
        "header", "section_title", "paragraph", "rich_text", "large_text", "code",
        "pull_quote", "drop_cap", "footer",
        "epigraph", "byline", "dateline", "salutation",
        "signature", "colophon", "address",
        "checklist", "bullets", "numbered",
        "kv", "table_compact", "rule", "ornament", "spacer", "gradient_band",
        "progress_bar", "sparkline", "qr", "barcode", "image", "ascii_art",
        "tear_here", "cut", "feed",
    ]
