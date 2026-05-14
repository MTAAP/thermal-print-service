"""Playwright HTML->PNG wrapper.

Intentionally synchronous and one-shot: we spin a fresh browser per
compile so leaks and crashes can't accumulate across the agent's
iteration loop. Cost is ~1-2 s per compile, which is fine for the
proofing loop.
"""
from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright
from printer_core.constants import PRINT_HEAD_WIDTH_PX

from tprint_design.defaults import inject_into


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
    width: int = PRINT_HEAD_WIDTH_PX,
    timeout_ms: int = 5000,
) -> RenderResult:
    """Render the HTML to a width-constrained PNG via headless Chromium.

    External requests are blocked unless the URL scheme is ``file:``,
    ``data:``, or empty (relative). The returned ``blocked_external_requests``
    is the count of routed-and-aborted external attempts -- useful for
    lint reporting downstream.
    """
    final_html = inject_into(html)
    blocked = 0
    if out_path is None:
        out_path = Path(tempfile.mkstemp(suffix=".png")[1])

    def _route(route):
        nonlocal blocked
        url = route.request.url
        if url.startswith(("file:", "data:")) or not _is_external(url):
            route.continue_()
        else:
            blocked += 1
            route.abort()

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                context = browser.new_context(
                    viewport={"width": width, "height": 800},
                    device_scale_factor=1,
                    color_scheme="light",
                    forced_colors="none",
                )
                context.set_default_timeout(timeout_ms)
                page = context.new_page()
                page.route("**/*", _route)
                page.set_content(final_html, wait_until="networkidle")
                png_bytes = page.screenshot(
                    full_page=True, type="png", omit_background=False
                )
                out_path.write_bytes(png_bytes)
                # Read width/height from the saved file via Pillow lazily --
                # Playwright doesn't surface the screenshot dims directly.
                from PIL import Image
                with Image.open(out_path) as img:
                    final_w, final_h = img.size
                return RenderResult(
                    png_path=out_path,
                    width=final_w,
                    height=final_h,
                    duration_ms=int(page.evaluate("performance.now()")),
                    blocked_external_requests=blocked,
                )
            finally:
                browser.close()
    except PlaywrightTimeoutError as exc:
        raise RenderError(f"render timeout after {timeout_ms} ms: {exc}") from exc
    except PlaywrightError as exc:
        raise RenderError(f"playwright error: {exc}") from exc


def _is_external(url: str) -> bool:
    return url.startswith(("http:", "https:", "ws:", "wss:"))
