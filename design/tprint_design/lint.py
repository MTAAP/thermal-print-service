"""Lint engine for thermal HTML designs.

Two passes:
  - pre_render(html) — DOM/CSS checks via Playwright `page.evaluate`
  - post_render(image, stats) — pixel-level checks on the dithered PNG

Each rule is a callable returning ``Iterable[LintFinding]``. Rules are
registered into ``PRE_RENDER_RULES`` and ``POST_RENDER_RULES`` lists in
the modules below; this file only owns the data shape and the runner.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class LintSeverity(StrEnum):
    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True)
class LintFinding:
    rule: str
    severity: LintSeverity
    message: str
    selector: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "rule": self.rule,
            "severity": self.severity.value,
            "message": self.message,
        }
        if self.selector is not None:
            out["selector"] = self.selector
        return out


@dataclass
class LintReport:
    errors: list[LintFinding] = field(default_factory=list)
    warnings: list[LintFinding] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors

    def add(self, finding: LintFinding) -> None:
        bucket = (
            self.errors if finding.severity is LintSeverity.ERROR
            else self.warnings
        )
        bucket.append(finding)

    def extend(self, findings: list[LintFinding]) -> None:
        for f in findings:
            self.add(f)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "errors": [f.to_dict() for f in self.errors],
            "warnings": [w.to_dict() for w in self.warnings],
            "stats": self.stats,
        }
