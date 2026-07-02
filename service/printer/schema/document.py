from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

from printer.schema.blocks import AnyBlock


class Options(BaseModel):
    model_config = ConfigDict(extra="forbid")
    auto_cut: bool = True
    feed_lines_after: int = Field(default=2, ge=0, le=20)
    preserve_paper: bool = False
    max_length_mm: int | None = Field(default=2000, ge=10, le=80_000)
    not_before: datetime | None = Field(
        default=None,
        description=(
            "Hold this job until options.not_before; when set to a future "
            "ISO 8601 timestamp, the queue keeps it pending and dispatches "
            "only after the service clock is synchronized and now >= not_before."
        ),
    )
    expires_at: datetime | None = None

    @model_validator(mode="after")
    def _validate_printable_window(self) -> Options:
        if self.expires_at is None or self.not_before is None:
            return self
        expires_at = _normalize_for_compare(self.expires_at)
        not_before = _normalize_for_compare(self.not_before)
        if expires_at <= not_before:
            raise ValueError("options.expires_at must be after options.not_before")
        return self


class Document(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_type: str | None = None
    options: Options = Field(default_factory=Options)
    blocks: list[Annotated[AnyBlock, Field(discriminator="type")]] = Field(min_length=1)


def _normalize_for_compare(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)
