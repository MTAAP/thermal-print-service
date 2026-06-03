"""Static thermal-design guidelines exposed via the MCP server.

Mirrored from design/tprint_design/guidelines.md. Update both files in
lockstep when the rules change.
"""
from __future__ import annotations

from printer_core.constants import (
    DPMM,
    LIVE_WIDTH_PX,
    MAX_LENGTH_MM_DEFAULT,
    PRINT_HEAD_WIDTH_PX,
)

# Re-export under the payload-key-shaped name so callers reading the
# MCP tool output and the local constant pair up at a glance.
PRINT_HEAD_PX = PRINT_HEAD_WIDTH_PX

FONTS_AVAILABLE = ["IBM Plex Sans", "JetBrains Mono", "Noto Sans SC"]
STARTER_TEMPLATES = ["banner", "blank", "literary", "note", "scroll"]

RULES_MARKDOWN = """\
# Thermal design guidelines

Live print area: **528 px** (24 px gutters on a 576 px head).
Density: **8 dots/mm** (1 mm = 8 px). Default max length: **2000 mm**.

## Rules of thumb

- Stay grayscale. No color. Anything with chroma trips a lint error.
- Body fonts >= 14 px. Below 12 px is a warning; below 9 px is an error.
- Use the bundled fonts (IBM Plex Sans, JetBrains Mono, Noto Sans SC)
  for guaranteed rendering.
- No shadows. text-shadow and box-shadow dither to noise.
- Local resources only. No CDN/https in src/href; the renderer blocks
  external network and lint flags it as an error.
- Width = 576 px. The thermal-reset stylesheet pins the body. Override
  with `body { padding: 0 }` to bleed; lint will warn.
- Watch ink density. A near-empty page (>95% white) probably means
  missing content.
- Inverse text (white on black) only at display sizes: >= 28 px AND
  bold. At body sizes the thermal head's lateral heat bleed erodes
  the white reversal until it's unreadable. Use bordered
  black-on-white for body-size emphasis instead.

## Workflow

1. `tprint-design init my.html` (optional starter scaffold).
2. Edit `my.html` (Write tool).
3. `tprint-design compile my.html` -> `my.png` + `my.preview.png` +
   `my.lint.json`.
4. `Read my.png` to see the dithered output. Read `my.lint.json` (or
   stdout summary) for warnings.
5. Iterate: edit -> compile -> look. No paper moves.
6. `tprint-design print my.html` (or `--dry-run` to validate).
"""


def payload() -> dict:
    return {
        "live_width_px": LIVE_WIDTH_PX,
        "print_head_px": PRINT_HEAD_PX,
        "dpmm": DPMM,
        "max_length_mm_default": MAX_LENGTH_MM_DEFAULT,
        "fonts_available": FONTS_AVAILABLE,
        "starter_templates": STARTER_TEMPLATES,
        "rules_markdown": RULES_MARKDOWN,
    }
