"""Auto-injected stylesheet + @font-face block for thermal HTML.

The thermal-reset CSS lives as an importable text resource so the CLI's
`info` subcommand can also surface its location to the agent. Font URLs
are resolved at runtime against the bundled font directory.
"""
from __future__ import annotations

import re
from importlib.resources import files
from pathlib import Path
from urllib.parse import urljoin

_PACKAGE_ROOT = Path(__file__).parent.parent
_FONT_DIR = _PACKAGE_ROOT / "fonts"

# Capture the href of a user-declared <base href="...">. The `\b` after `base`
# keeps the deprecated `<basefont>` element from matching, and capturing the
# href lets _build_head_block tell an absolute base (respect it) from a
# relative one (resolve it against the source dir).
_USER_BASE_HREF_RE = re.compile(
    r"<base\b[^>]*?\bhref\s*=\s*[\"']([^\"']*)[\"']", re.IGNORECASE
)
# Absolute = has a URL scheme (file:, https:) or is protocol-relative (//host).
_ABSOLUTE_URL_RE = re.compile(r"^[a-z][a-z0-9+.-]*:|^//", re.IGNORECASE)

_FONT_FACES: list[tuple[str, str, dict[str, str]]] = [
    ("IBM Plex Sans",   "IBMPlexSans-Medium.ttf",   {}),
    ("IBM Plex Sans",   "IBMPlexSans-Bold.ttf",     {"font-weight": "700"}),
    ("JetBrains Mono",  "JetBrainsMono-Regular.ttf", {}),
    ("Noto Sans SC",    "NotoSansSC-Regular.otf",   {}),
]


def thermal_reset_css() -> str:
    return (files("tprint_design.defaults") / "thermal_reset.css").read_text()


def font_dir_uri() -> str:
    """URI prefix for the bundled font directory.

    The render route filter strict-allowlists this prefix so the
    @font-face URLs (which resolve to absolute file:// paths under the
    package's assets/fonts/ symlinks) can fetch while arbitrary other
    file:// paths stay blocked.
    """
    return _FONT_DIR.resolve().as_uri() + "/"


def font_face_block() -> str:
    parts: list[str] = []
    for family, filename, extra in _FONT_FACES:
        # Path.as_uri() handles platform-specific quoting (drive letters and
        # backslashes on Windows, percent-encoding for spaces) — naive
        # f"file://{path}" string concatenation produces invalid URLs on
        # Windows and breaks if the resolved path contains spaces.
        # Intentionally NOT calling .resolve(): the fonts dir contains
        # per-file symlinks into assets/fonts/, and the renderer's route
        # filter strict-allowlists the fonts dir (symlink) prefix only.
        # Chromium follows symlinks transparently at the FS layer, so the
        # actual font load still works.
        url = (_FONT_DIR / filename).absolute().as_uri()
        decls = "".join(f"{k}: {v}; " for k, v in extra.items())
        parts.append(
            f"@font-face {{ font-family: '{family}'; "
            f"src: url('{url}'); {decls}}}"
        )
    return "\n".join(parts)


def _injected_style() -> str:
    return f"<style>\n{font_face_block()}\n{thermal_reset_css()}\n</style>"


def inject_into(html: str, source_path: Path | None = None) -> str:
    """Inject default style block into the HTML's <head>.

    Reset is prepended (inserted right after the opening <head> tag) so
    user styles declared later in the document override it on source-order
    ties. The reset's !important shadow rules still win over user CSS
    because !important beats source order.

    When ``source_path`` is provided, a ``<base href="file:///source-dir/">``
    tag is also prepended so relative refs (``./logo.png``,
    ``href="styles.css"``) in the source HTML resolve against the source
    file's directory rather than against the temp-file path the renderer
    actually loads. An absolute user ``<base>`` is respected as-is; a relative
    user ``<base>`` is resolved against the source dir (it would otherwise
    resolve against the temp render dir and silently drop its assets).

    If the document has no <head>, wrap the input in a minimal HTML
    envelope that includes one. Idempotency is not guaranteed — calling
    twice will inject twice; callers compile from source HTML.
    """
    head_block = _build_head_block(html, source_path)
    lower = html.lower()
    head_open_idx = lower.find("<head")
    if head_open_idx != -1:
        # Find the end of the opening tag (the first '>' after '<head').
        tag_end = lower.find(">", head_open_idx)
        if tag_end != -1:
            insert_at = tag_end + 1
            return html[:insert_at] + head_block + html[insert_at:]
    body_idx = lower.find("<body")
    if body_idx == -1:
        return (
            "<!doctype html><html><head>"
            f"{head_block}"
            "</head><body>"
            f"{html}"
            "</body></html>"
        )
    return (
        f"<!doctype html><html><head>{head_block}</head>"
        f"{html[body_idx:]}"
    )


def _build_head_block(html: str, source_path: Path | None) -> str:
    """Compose the head injection: optional <base> first, then style block.

    <base> must precede any element that uses URLs to take effect on them,
    so it leads. The font-face block uses absolute file:// URLs and the
    reset uses no URLs, so neither is affected by the base href — but
    placing <base> first keeps the order intuitive and future-proofs
    against URL-bearing additions to the injected styles.
    """
    style = _injected_style()
    if source_path is None:
        return style
    # Trailing slash is load-bearing: `<base href="file:///foo">` resolves
    # `./bar` to `file:///bar` (treating `foo` as a filename), while
    # `file:///foo/` resolves it to `file:///foo/bar`.
    base_uri = source_path.resolve().parent.as_uri() + "/"
    user_base = _user_base_href(html)
    if user_base is None:
        # No usable user <base>: inject the absolute source-dir base.
        return f'<base href="{base_uri}">{style}'
    if _ABSOLUTE_URL_RE.match(user_base):
        # The user pinned an absolute base; respect it, inject nothing.
        return style
    # A relative user base (e.g. `<base href="./assets/">`) would resolve
    # against the temp render dir the renderer loads, not the source file —
    # its assets would 404 from a path the render-dir allowlist permits,
    # silently dropping them with no blocked-fetch error. Resolve it against
    # the source dir and inject that as the leading <base> (the first <base>
    # wins) so the user's intended path still works.
    return f'<base href="{urljoin(base_uri, user_base)}">{style}'


def _user_base_href(html: str) -> str | None:
    m = _USER_BASE_HREF_RE.search(html)
    return m.group(1).strip() if m else None
