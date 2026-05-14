"""tprint-design entry point.

Subcommands are wired in via ``_build_parser``. Each subcommand
implementation lives in its own private function (``_cmd_<name>``) and
returns an exit code: 0 = success, 1 = lint errors, 2 = render/IO error.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from importlib.resources import files
from pathlib import Path

from printer_core.constants import (
    DPMM,
    LIVE_WIDTH_PX,
    MAX_LENGTH_MM_DEFAULT,
    PRINT_HEAD_WIDTH_PX,
)


def _load_guidelines_md() -> str:
    return (files("tprint_design") / "guidelines.md").read_text()


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="tprint-design")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_info = sub.add_parser("info", help="Show engine + design info")
    p_info.add_argument("--json", action="store_true",
                        help="Emit machine-readable JSON")

    p_init = sub.add_parser("init", help="Drop a starter HTML scaffold")
    p_init.add_argument("path", type=Path, help="Destination .html file")
    p_init.add_argument("--template", choices=[
        "blank", "note", "banner", "literary", "scroll",
    ], default="blank")
    p_init.add_argument("--force", action="store_true",
                        help="Overwrite existing file")

    p_compile = sub.add_parser("compile", help="Render HTML to thermal PNG")
    p_compile.add_argument("path", type=Path, help="Source .html file")
    p_compile.add_argument("--out", type=Path, default=None,
                           help="Override output PNG path")
    p_compile.add_argument("--no-lint", action="store_true",
                           help="Skip lint pass; exit 0 on render success")
    p_compile.add_argument("--max-length-mm", type=int, default=None,
                           help="Override Pi max_length_mm for lint")
    p_compile.add_argument("--width", type=int, default=576)

    p_lint = sub.add_parser("lint", help="Pre-render lint only (fast)")
    p_lint.add_argument("path", type=Path)
    p_lint.add_argument("--out", type=Path, default=None,
                        help="Write lint JSON to this path")

    return p


def _cmd_info(args: argparse.Namespace) -> int:
    md = _load_guidelines_md()
    if args.json:
        payload = {
            "live_width_px": LIVE_WIDTH_PX,
            "print_head_px": PRINT_HEAD_WIDTH_PX,
            "dpmm": DPMM,
            "max_length_mm_default": MAX_LENGTH_MM_DEFAULT,
            "fonts_available": [
                "IBM Plex Sans", "JetBrains Mono", "Noto Sans SC",
            ],
            "starter_templates": ["scroll", "note", "banner", "literary", "blank"],
            "rules_markdown": md,
        }
        print(json.dumps(payload, indent=2))
    else:
        print(md)
    return 0


def _cmd_init(args: argparse.Namespace) -> int:
    if args.path.exists() and not args.force:
        print(f"refusing to overwrite {args.path} (use --force)", file=sys.stderr)
        return 2
    src = files("tprint_design.templates") / f"{args.template}.html"
    args.path.write_text(src.read_text())
    print(f"wrote {args.path} (template: {args.template})")
    return 0


def _cmd_compile(args: argparse.Namespace) -> int:
    from PIL import Image

    from tprint_design.compile import compile_html
    from tprint_design.lint import lint_html_text

    try:
        result = compile_html(args.path, out_path=args.out, width=args.width)
    except Exception as exc:
        print(f"render error: {exc}", file=sys.stderr)
        return 2

    if args.no_lint:
        print(f"compiled {result.out_path} ({result.rendered_height_px} px)")
        return 0

    rgb = Image.open(result.rgb_path)
    one_bit = Image.open(result.out_path)
    rpt = lint_html_text(
        args.path.read_text(),
        rendered_rgb=rgb, rendered_one_bit=one_bit,
        render_ms=result.render_ms,
        blocked_external_requests=result.blocked_external_requests,
        max_length_mm_flag=args.max_length_mm,
    )
    lint_path = result.out_path.with_suffix(".lint.json")
    lint_path.write_text(json.dumps(rpt.to_dict(), indent=2))

    _print_lint_summary(rpt, result)
    return 0 if rpt.ok else 1


def _print_lint_summary(rpt, result) -> None:
    print(f"compiled {result.out_path} "
          f"({result.rendered_height_px} px, "
          f"~{result.estimated_paper_mm:.0f} mm of paper, "
          f"ink ratio {result.ink_pixel_ratio:.0%})")
    for f in rpt.errors:
        print(f"  ERROR  [{f.rule}] {f.message}")
    for w in rpt.warnings:
        print(f"  warn   [{w.rule}] {w.message}")


def _cmd_lint(args: argparse.Namespace) -> int:
    from tprint_design.lint import lint_html_file

    rpt = lint_html_file(args.path)
    if args.out:
        args.out.write_text(json.dumps(rpt.to_dict(), indent=2))
    for f in rpt.errors:
        print(f"  ERROR  [{f.rule}] {f.message}")
    for w in rpt.warnings:
        print(f"  warn   [{w.rule}] {w.message}")
    return 0 if rpt.ok else 1


_DISPATCH = {
    "info": _cmd_info, "init": _cmd_init,
    "compile": _cmd_compile, "lint": _cmd_lint,
}


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    return _DISPATCH[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
