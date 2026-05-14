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


_DISPATCH = {"info": _cmd_info}


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    return _DISPATCH[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
