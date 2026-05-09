from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from printer.schema.blocks import AnyBlock


class Options(BaseModel):
    model_config = ConfigDict(extra="forbid")
    auto_cut: bool = True
    feed_lines_after: int = Field(default=2, ge=0, le=20)
    preserve_paper: bool = False
    max_length_mm: int | None = Field(default=2000, ge=10, le=80_000)
    expires_at: datetime | None = None


class Document(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_type: str | None = None
    options: Options = Field(default_factory=Options)
    blocks: list[Annotated[AnyBlock, Field(discriminator="type")]] = Field(min_length=1)
