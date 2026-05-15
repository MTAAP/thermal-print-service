"""Pre-render lint pass — DOM/CSS checks via headless Chromium.

We run a single Playwright `evaluate` that walks every element and
returns a structured payload of findings. Doing the walk in JS rather
than over many Python round-trips keeps the pass fast (~50 ms after
warmup).
"""
from __future__ import annotations

from playwright.sync_api import sync_playwright

from tprint_design.defaults import inject_into
from tprint_design.lint import LintFinding, LintSeverity

_WALK_JS = r"""
() => {
  const findings = [];
  const isExternal = (url) => /^(https?|wss?):/i.test(url);

  // External resources via tag attributes (img/script/link/iframe/...)
  for (const tag of ['img', 'script', 'link', 'iframe', 'video', 'audio']) {
    for (const el of document.querySelectorAll(tag)) {
      const url = el.src || el.href;
      if (url && isExternal(url)) {
        findings.push({
          rule: 'external_resource',
          severity: 'error',
          message: `${tag} loads ${url} — external network is blocked`,
          selector: el.tagName.toLowerCase(),
        });
      }
    }
  }

  // External resources embedded in CSS: @import, @font-face src, and any
  // url(...) reference in style rules (background-image, list-style, etc.).
  // These are blocked at runtime but the tag walk above can't see them, so
  // without this scan a user gets a "lint clean" report and a render that
  // silently falls back to system fonts or missing assets.
  const cssUrlRe = /url\(\s*['"]?([^'")\s]+)['"]?\s*\)/g;
  for (const sheet of document.styleSheets) {
    let rules;
    try {
      rules = sheet.cssRules || sheet.rules || [];
    } catch (e) {
      // CORS-blocked cross-origin stylesheet — the <link> tag itself was
      // already flagged above, so skipping the rule walk is fine.
      continue;
    }
    for (const rule of rules) {
      if (rule.type === CSSRule.IMPORT_RULE && rule.href && isExternal(rule.href)) {
        findings.push({
          rule: 'external_resource',
          severity: 'error',
          message: `@import loads ${rule.href} — external network is blocked`,
        });
        continue;
      }
      const text = rule.cssText || '';
      for (const match of text.matchAll(cssUrlRe)) {
        const url = match[1];
        if (isExternal(url)) {
          findings.push({
            rule: 'external_resource',
            severity: 'error',
            message: `CSS rule loads ${url} — external network is blocked`,
          });
        }
      }
    }
  }

  // Per-element computed-style checks
  for (const el of document.querySelectorAll('body, body *')) {
    const cs = getComputedStyle(el);
    const fs = parseFloat(cs.fontSize);
    if (fs && fs < 9) {
      findings.push({
        rule: 'font_size_too_small',
        severity: 'error',
        message: `${el.tagName.toLowerCase()} computed font-size ${fs}px (< 9 px)`,
        selector: el.tagName.toLowerCase(),
      });
    } else if (fs && fs < 12) {
      findings.push({
        rule: 'font_size_small',
        severity: 'warning',
        message: `${el.tagName.toLowerCase()} computed font-size ${fs}px (recommended >= 14 px)`,
        selector: el.tagName.toLowerCase(),
      });
    }
    // text-shadow / box-shadow: scan inline style attribute, not computed
    // style. The thermal CSS reset declares
    //   * { text-shadow: none !important; box-shadow: none !important; }
    // which beats any inline rule that does not also use !important, so
    // computed-style would always be 'none'. We want the lint to fire
    // when the design author *tried* to use a shadow — they intended a
    // visual effect that the reset will silently strip — so we read the
    // inline style attribute directly.
    const inline = el.style;
    if (inline.textShadow && inline.textShadow !== 'none') {
      findings.push({
        rule: 'text_shadow',
        severity: 'warning',
        message: `${el.tagName.toLowerCase()} uses text-shadow — dithers to noise`,
        selector: el.tagName.toLowerCase(),
      });
    }
    if (inline.boxShadow && inline.boxShadow !== 'none') {
      findings.push({
        rule: 'box_shadow',
        severity: 'warning',
        message: `${el.tagName.toLowerCase()} uses box-shadow — dithers to noise`,
        selector: el.tagName.toLowerCase(),
      });
    }
  }

  // Body width
  const bodyWidth = document.body.getBoundingClientRect().width;
  if (Math.abs(bodyWidth - 576) > 1) {
    findings.push({
      rule: 'body_width',
      severity: 'warning',
      message: `body width is ${bodyWidth}px (expected 576px)`,
    });
  }

  return findings;
}
"""


def pre_render_lint(html: str, *, timeout_ms: int = 5000) -> list[LintFinding]:
    final_html = inject_into(html)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            context = browser.new_context(viewport={"width": 576, "height": 800})
            context.set_default_timeout(timeout_ms)
            page = context.new_page()
            page.route("**/*", lambda route: (
                route.continue_()
                if route.request.url.startswith(("file:", "data:"))
                or not route.request.url.startswith(("http:", "https:", "ws:", "wss:"))
                else route.abort()
            ))
            page.set_content(final_html, wait_until="networkidle")
            raw = page.evaluate(_WALK_JS)
        finally:
            browser.close()
    return [
        LintFinding(
            rule=item["rule"],
            severity=LintSeverity(item["severity"]),
            message=item["message"],
            selector=item.get("selector"),
        )
        for item in raw
    ]
