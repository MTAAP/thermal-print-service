from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

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
    text: str = Field(min_length=1, max_length=200)
    subtitle: str | None = Field(default=None, max_length=200)
    style: Literal["inverse_band", "ornamental", "minimal"] = "inverse_band"


class SectionTitleBlock(_AlignableBlock):
    type: Literal["section_title"]
    text: str = Field(min_length=1, max_length=200)
    style: Literal["underline", "inverse", "rule_above"] = "underline"


class ParagraphBlock(_AlignableBlock):
    type: Literal["paragraph"]
    text: str = Field(min_length=1, max_length=4000)
    emphasis: Literal["italic", "bold"] | None = None


class RichTextRun(_Block):
    text: str = Field(min_length=1, max_length=2000)
    bold: bool = False
    italic: bool = False
    inverse: bool = False
    underline: bool = False
    size: Literal["sm", "md", "lg"] = "md"


class RichTextBlock(_AlignableBlock):
    type: Literal["rich_text"]
    runs: list[RichTextRun] = Field(min_length=2, max_length=64)


class LargeTextBlock(_AlignableBlock):
    type: Literal["large_text"]
    text: str = Field(min_length=1, max_length=200)
    size: Literal["xl", "xxl", "xxxl"] = "xxl"


class CodeBlock(_Block):
    type: Literal["code"]
    text: str = Field(min_length=1, max_length=8000)


class PullQuoteBlock(_AlignableBlock):
    type: Literal["pull_quote"]
    text: str = Field(min_length=1, max_length=2000)
    attribution: str | None = Field(default=None, max_length=200)


class DropCapBlock(_Block):
    type: Literal["drop_cap"]
    first_letter: str = Field(min_length=1, max_length=1)
    rest: str = Field(min_length=1, max_length=4000)


class FooterBlock(_AlignableBlock):
    type: Literal["footer"]
    text: str = Field(min_length=1, max_length=200)


# ===== Lists & data =====


class ChecklistBlock(_Block):
    type: Literal["checklist"]
    items: list[str] = Field(min_length=1, max_length=64)


class BulletsBlock(_Block):
    type: Literal["bullets"]
    items: list[str] = Field(min_length=1, max_length=64)
    marker: Literal["•", "—", "▸"] = "•"


class NumberedBlock(_Block):
    type: Literal["numbered"]
    items: list[str] = Field(min_length=1, max_length=64)


class KvPair(_Block):
    key: str = Field(min_length=1, max_length=100)
    value: str = Field(min_length=0, max_length=200)


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
    style: Literal["solid", "dashed", "dotted", "double", "wave"] = "solid"


class OrnamentBlock(_Block):
    type: Literal["ornament"]
    pattern: Literal["stars", "diamonds", "leaves", "geometric"] = "stars"


class SpacerBlock(_Block):
    type: Literal["spacer"]
    lines: int = Field(ge=1, le=10)


class GradientBandBlock(_Block):
    type: Literal["gradient_band"]
    direction: Literal["down", "up"] = "down"


class ProgressBarBlock(_Block):
    type: Literal["progress_bar"]
    value: float = Field(ge=0.0, le=1.0)
    label: str | None = Field(default=None, max_length=80)


class SparklineBlock(_Block):
    type: Literal["sparkline"]
    values: list[float] = Field(min_length=2, max_length=200)
    label: str | None = Field(default=None, max_length=80)


# ===== Embedded objects =====


class QrBlock(_Block):
    type: Literal["qr"]
    data: str = Field(min_length=1, max_length=2000)
    caption: str | None = Field(default=None, max_length=120)
    size: Literal["sm", "md", "lg"] = "md"


class BarcodeBlock(_Block):
    type: Literal["barcode"]
    data: str = Field(min_length=1, max_length=200)
    format: Literal["CODE128", "EAN13", "EAN8", "UPCA"] = "CODE128"


class ImageBlock(_AlignableBlock):
    type: Literal["image"]
    png_base64: str = Field(min_length=1)
    width_px: int = Field(default=528, ge=1, le=528)
    bleed: bool = False
    dither: Literal["atkinson", "floyd_steinberg", "ordered", "none"] = "atkinson"

    @model_validator(mode="after")
    def _bleed_no_align(self):
        # Bleed images cover the full print head — alignment is meaningless.
        if self.bleed and self.align != "left":
            raise ValueError("image with bleed=true must not specify align")
        return self


class AsciiArtBlock(_Block):
    type: Literal["ascii_art"]
    text: str = Field(min_length=1, max_length=8000)
    font: Literal["default", "small"] = "default"


# ===== Flow control =====


class TearHereBlock(_Block):
    type: Literal["tear_here"]
    label: str | None = Field(default=None, max_length=80)


class CutBlock(_Block):
    type: Literal["cut"]


class FeedBlock(_Block):
    type: Literal["feed"]
    lines: int = Field(ge=1, le=20)


AnyBlock = (
    HeaderBlock | SectionTitleBlock | ParagraphBlock | RichTextBlock
    | LargeTextBlock | CodeBlock | PullQuoteBlock | DropCapBlock | FooterBlock
    | ChecklistBlock | BulletsBlock | NumberedBlock | KvBlock | TableCompactBlock
    | RuleBlock | OrnamentBlock | SpacerBlock | GradientBandBlock
    | ProgressBarBlock | SparklineBlock
    | QrBlock | BarcodeBlock | ImageBlock | AsciiArtBlock
    | TearHereBlock | CutBlock | FeedBlock
)


def block_type_names() -> list[str]:
    return [
        "header", "section_title", "paragraph", "rich_text", "large_text", "code",
        "pull_quote", "drop_cap", "footer", "checklist", "bullets", "numbered",
        "kv", "table_compact", "rule", "ornament", "spacer", "gradient_band",
        "progress_bar", "sparkline", "qr", "barcode", "image", "ascii_art",
        "tear_here", "cut", "feed",
    ]
