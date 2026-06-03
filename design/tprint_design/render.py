"""Playwright HTML->PNG wrapper.

Intentionally synchronous and one-shot: we spin a fresh browser per
compile so leaks and crashes can't accumulate across the agent's
iteration loop. Cost is ~1-2 s per compile, which is fine for the
proofing loop.

Security posture: page-level JavaScript is disabled and subresource
fetches are strict-allowlisted to the render dir, the source dir, and
``data:`` URIs. The HTML pipeline trusts the author's CSS but never
their scripts, and treats arbitrary ``file://`` paths outside the
source dir as exfil channels (the rendered PNG is read back by the
agent — anything the page can load can leave through the screenshot).
"""
from __future__ import annotations

import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright
from printer_core.constants import PRINT_HEAD_WIDTH_PX

from tprint_design.defaults import font_dir_uri, inject_into


class RenderError(RuntimeError):
    pass


@dataclass(frozen=True)
class RenderResult:
    png_path: Path
    width: int
    height: int
    duration_ms: int
    blocked_external_requests: int


def render_html_to_png(
    html: str,
    *,
    out_path: Path | None = None,
    source_path: Path | None = None,
    width: int = PRINT_HEAD_WIDTH_PX,
    timeout_ms: int = 5000,
) -> RenderResult:
    """Render the HTML to a width-constrained PNG via headless Chromium.

    When ``source_path`` is provided, ``<base href="file:///source-dir/">``
    is injected so relative refs in the source HTML (``./logo.png``,
    stylesheet ``url(./bg.png)``) resolve against the source file's
    directory. Without it, page origin would be the temp render directory
    and any relative ref in the source would 404.

    The injected HTML is written to a temp file and loaded via
    ``page.goto(file://...)`` rather than ``page.set_content`` because
    Chromium silently blocks ``file://`` resource fetches from an
    ``about:blank`` document — so even with a correct base href, the
    image loads would fail.

    Subresource fetches are strict-allowlisted: only ``data:`` URIs, the
    render dir, and the source dir are reachable. Everything else
    (``http(s)``, ``ws``, ``blob:``, arbitrary ``file://`` paths) is
    aborted and counted in ``blocked_external_requests`` for lint to
    surface. Page JS is disabled — ``<script>`` tags don't execute, so a
    page can't dynamically load arbitrary URLs. The Playwright
    ``page.evaluate`` channel is unaffected, so callers (e.g. the
    pre-render lint) can still introspect the DOM/CSSOM.
    """
    final_html = inject_into(html, source_path=source_path)
    fonts_uri = font_dir_uri()
    blocked = 0
    cleanup_on_failure: Path | None = None
    if out_path is None:
        # mkstemp returns (fd, path) and hands ownership of the fd to us;
        # discarding it leaks file descriptors when this is called in a
        # long-running agent loop. Close it before we overwrite the file
        # via write_bytes() below.
        fd, tmp_path = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        out_path = Path(tmp_path)
        cleanup_on_failure = out_path

    source_dir_uri: str | None = None
    if source_path is not None:
        source_dir_uri = source_path.resolve().parent.as_uri() + "/"

    try:
        with tempfile.TemporaryDirectory() as render_td:
            render_dir = Path(render_td).resolve()
            render_html_path = render_dir / "page.html"
            render_html_path.write_text(final_html, encoding="utf-8")
            render_dir_uri = render_dir.as_uri() + "/"
            page_uri = render_html_path.as_uri()

            def _route(route):
                nonlocal blocked
                url = route.request.url
                # Allowlist: data:, the render dir (where page.html lives),
                # the bundled-fonts dir (so @font-face URLs reach), and the
                # source dir (so <base href> resolves ./ refs). Everything
                # else — arbitrary file://, http(s), ws, blob: — is blocked
                # to neuter the screenshot-exfil channel.
                if (
                    url.startswith("data:")
                    or url.startswith(render_dir_uri)
                    or url.startswith(fonts_uri)
                ):
                    route.continue_()
                    return
                if source_dir_uri is not None and url.startswith(source_dir_uri):
                    route.continue_()
                    return
                blocked += 1
                route.abort()

            start_ns = time.monotonic_ns()
            with sync_playwright() as p:
                # --disable-lcd-text forces grayscale font antialiasing in the
                # content area instead of subpixel (LCD) antialiasing. Without it,
                # Chromium emits red/blue subpixel fringes around glyphs on Linux
                # which would trip the color_used lint downstream even though the
                # source HTML is pure black-on-white.
                browser = p.chromium.launch(
                    headless=True,
                    args=["--disable-lcd-text", "--font-render-hinting=none"],
                )
                try:
                    context = browser.new_context(
                        viewport={"width": width, "height": 800},
                        device_scale_factor=1,
                        color_scheme="light",
                        forced_colors="none",
                        java_script_enabled=False,
                    )
                    context.set_default_timeout(timeout_ms)
                    page = context.new_page()
                    page.route("**/*", _route)
                    page.goto(page_uri, wait_until="networkidle")
                    png_bytes = page.screenshot(
                        full_page=True, type="png", omit_background=False
                    )
                finally:
                    browser.close()
            out_path.write_bytes(png_bytes)
            # Read width/height from the saved file via Pillow — Playwright
            # doesn't surface the screenshot dims directly.
            from PIL import Image
            with Image.open(out_path) as img:
                final_w, final_h = img.size
            return RenderResult(
                png_path=out_path,
                width=final_w,
                height=final_h,
                duration_ms=int((time.monotonic_ns() - start_ns) / 1_000_000),
                blocked_external_requests=blocked,
            )
    except PlaywrightTimeoutError as exc:
        if cleanup_on_failure is not None:
            cleanup_on_failure.unlink(missing_ok=True)
        raise RenderError(f"render timeout after {timeout_ms} ms: {exc}") from exc
    except PlaywrightError as exc:
        if cleanup_on_failure is not None:
            cleanup_on_failure.unlink(missing_ok=True)
        raise RenderError(f"playwright error: {exc}") from exc
    except Exception:
        if cleanup_on_failure is not None:
            cleanup_on_failure.unlink(missing_ok=True)
        raise
