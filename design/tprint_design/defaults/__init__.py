"""Auto-injected stylesheet + @font-face block for thermal HTML.

The thermal-reset CSS lives as an importable text resource so the CLI's
`info` subcommand can also surface its location to the agent. Font URLs
are resolved at runtime against the bundled font directory.
"""
from __future__ import annotations

from importlib.resources import files
from pathlib import Path

_PACKAGE_ROOT = Path(__file__).parent.parent
_FONT_DIR = _PACKAGE_ROOT / "fonts"

_FONT_FACES: list[tuple[str, str, dict[str, str]]] = [
    ("IBM Plex Sans",   "IBMPlexSans-Medium.ttf",   {}),
    ("IBM Plex Sans",   "IBMPlexSans-Bold.ttf",     {"font-weight": "700"}),
    ("JetBrains Mono",  "JetBrainsMono-Regular.ttf", {}),
    ("Noto Sans SC",    "NotoSansSC-Regular.otf",   {}),
]


def thermal_reset_css() -> str:
    return (files("tprint_design.defaults") / "thermal_reset.css").read_text()


def font_face_block() -> str:
    parts: list[str] = []
    for family, filename, extra in _FONT_FACES:
        # Path.as_uri() handles platform-specific quoting (drive letters and
        # backslashes on Windows, percent-encoding for spaces) — naive
        # f"file://{path}" string concatenation produces invalid URLs on
        # Windows and breaks if the resolved path contains spaces.
        url = (_FONT_DIR / filename).resolve().as_uri()
        decls = "".join(f"{k}: {v}; " for k, v in extra.items())
        parts.append(
            f"@font-face {{ font-family: '{family}'; "
            f"src: url('{url}'); {decls}}}"
        )
    return "\n".join(parts)


def _injected_style() -> str:
    return f"<style>\n{font_face_block()}\n{thermal_reset_css()}\n</style>"


def inject_into(html: str) -> str:
    """Inject default style block into the HTML's <head>.

    Reset is prepended (inserted right after the opening <head> tag) so
    user styles declared later in the document override it on source-order
    ties. The reset's !important shadow rules still win over user CSS
    because !important beats source order. If the document has no <head>,
    wrap the input in a minimal HTML envelope that includes one.
    Idempotency is not guaranteed — calling twice will inject twice;
    callers compile from source HTML.
    """
    style = _injected_style()
    lower = html.lower()
    head_open_idx = lower.find("<head")
    if head_open_idx != -1:
        # Find the end of the opening tag (the first '>' after '<head').
        tag_end = lower.find(">", head_open_idx)
        if tag_end != -1:
            insert_at = tag_end + 1
            return html[:insert_at] + style + html[insert_at:]
    body_idx = lower.find("<body")
    if body_idx == -1:
        return (
            "<!doctype html><html><head>"
            f"{style}"
            "</head><body>"
            f"{html}"
            "</body></html>"
        )
    return (
        f"<!doctype html><html><head>{style}</head>"
        f"{html[body_idx:]}"
    )
