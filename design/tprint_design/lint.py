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
from pathlib import Path
from typing import Any

from PIL import Image
from printer_core.constants import DPMM
from printer_core.ink import ink_ratio


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


def lint_html_text(
    html: str,
    *,
    source_path: Path | None = None,
    rendered_rgb: Image.Image | None = None,
    rendered_one_bit: Image.Image | None = None,
    render_ms: int | None = None,
    blocked_external_requests: int | None = None,
    max_length_mm_flag: int | None = None,
) -> LintReport:
    # Function-local imports: lint_pre and lint_post both import LintFinding
    # / LintSeverity from this module, so a top-level import here would
    # produce a circular ImportError. Keeping these local resolves the cycle
    # without scattering bottom-of-file imports paired with E402 suppressions.
    from tprint_design.lint_post import post_render_lint
    from tprint_design.lint_pre import pre_render_lint
    from tprint_design.pi_info import effective_max_length_mm

    rpt = LintReport()
    rpt.extend(pre_render_lint(html, source_path=source_path))
    if rendered_rgb is not None and rendered_one_bit is not None:
        cap = effective_max_length_mm(flag_value=max_length_mm_flag)
        rpt.extend(post_render_lint(
            rgb=rendered_rgb, one_bit=rendered_one_bit,
            effective_max_length_mm=cap,
        ))
        rpt.stats.update({
            "rendered_height_px": rendered_one_bit.height,
            "estimated_paper_mm": rendered_one_bit.height / DPMM,
            "ink_pixel_ratio": ink_ratio(rendered_one_bit),
        })
    if render_ms is not None:
        rpt.stats["render_ms"] = render_ms
    if blocked_external_requests is not None:
        rpt.stats["blocked_external_requests"] = blocked_external_requests
    return rpt


def lint_html_file(path: Path, **kwargs: Any) -> LintReport:
    p = Path(path)
    # Default source_path to the file we just read so relative refs in the
    # source resolve correctly during the lint pass. An explicit caller
    # override still wins.
    kwargs.setdefault("source_path", p)
    return lint_html_text(p.read_text(), **kwargs)
