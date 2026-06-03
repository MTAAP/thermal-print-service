"""Pre-render lint pass — DOM/CSS checks via headless Chromium.

We run a single Playwright `evaluate` that walks every element and
returns a structured payload of findings. Doing the walk in JS rather
than over many Python round-trips keeps the pass fast (~50 ms after
warmup).
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

from tprint_design.defaults import font_dir_uri, inject_into
from tprint_design.lint import LintFinding, LintSeverity
from tprint_design.render import _is_allowed_subresource

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

  // Walk every stylesheet rule, recursing into @media / @supports /
  // @import.styleSheet so nested rules surface. Catches three classes:
  //   1. External resources embedded in CSS (@import, @font-face src,
  //      background-image, etc.) — blocked at runtime but invisible to
  //      the tag walk above.
  //   2. Shadow declarations on a selector other than inline style. The
  //      reset's `* { text-shadow: none !important }` masks computed
  //      style, so the el.style scan below can't see them either; we
  //      have to inspect the rule's own declaration block.
  //   3. Same checks inside @media (...) blocks, which the prior loop
  //      missed because CSSMediaRule.style is undefined — recursion is
  //      required to reach the inner rules.
  const cssUrlRe = /url\(\s*['"]?([^'")\s]+)['"]?\s*\)/g;
  function walkRules(rules, sheetHref) {
    for (const rule of rules) {
      if (rule.type === CSSRule.IMPORT_RULE) {
        if (rule.href && isExternal(rule.href)) {
          findings.push({
            rule: 'external_resource',
            severity: 'error',
            message: `@import loads ${rule.href} — external network is blocked`,
          });
        }
        // Recurse into the imported stylesheet if accessible. cssRules
        // access throws SecurityError when the imported sheet is
        // cross-origin to the page — caught and surfaced below via the
        // route-handler's blocked-URL list rather than silently skipped.
        if (rule.styleSheet) {
          try {
            walkRules(rule.styleSheet.cssRules || [], rule.href || sheetHref);
          } catch (e) {
            // Inaccessible imported stylesheet; route handler will
            // separately surface any blocked subresource fetches.
          }
        }
        continue;
      }
      if (rule.type === CSSRule.MEDIA_RULE || rule.type === CSSRule.SUPPORTS_RULE) {
        // Nested rules live in rule.cssRules; recurse.
        try {
          walkRules(rule.cssRules || [], sheetHref);
        } catch (e) { /* same-origin invariant; ignore */ }
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
      // Shadow checks. rule.style.textShadow / boxShadow give the parsed
      // value (or '' if unset). 'none' values — including the reset's own
      // universal-selector !important rule — are filtered out so the
      // reset can't self-flag.
      const sel = rule.selectorText || '';
      if (rule.style) {
        const ts = rule.style.textShadow;
        if (ts && ts !== 'none') {
          findings.push({
            rule: 'text_shadow',
            severity: 'warning',
            message: `${sel || 'rule'} sets text-shadow: ${ts} — dithers to noise`,
            selector: sel || undefined,
          });
        }
        const bs = rule.style.boxShadow;
        if (bs && bs !== 'none') {
          findings.push({
            rule: 'box_shadow',
            severity: 'warning',
            message: `${sel || 'rule'} sets box-shadow: ${bs} — dithers to noise`,
            selector: sel || undefined,
          });
        }
      }
    }
  }
  for (const sheet of document.styleSheets) {
    let rules;
    try {
      rules = sheet.cssRules || sheet.rules || [];
    } catch (e) {
      // CORS-blocked cross-origin stylesheet — the <link> tag itself was
      // already flagged above, so skipping the rule walk is fine.
      continue;
    }
    walkRules(rules, sheet.href);
  }

  // Per-element computed-style checks
  function rgbSum(s) {
    // getComputedStyle returns "rgb(R, G, B)" or "rgba(R, G, B, A)"
    const m = s && s.match(/^rgba?\((\d+),\s*(\d+),\s*(\d+)/);
    return m ? (+m[1] + +m[2] + +m[3]) : null;
  }
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
    // Inverse text legibility (white-on-black at body sizes).
    // The thermal head's lateral heat bleed erodes the white reverse at
    // sizes below ~28 px and at non-bold weights. The dithered PNG looks
    // fine on screen — the failure happens at the print head. Only the
    // *intent* (light-on-dark CSS) is detectable in the lint pass; we
    // can't catch the physical failure but we can warn on the intent.
    //
    // Heuristic: element has explicit dark background (rgb sum < 60 out
    // of 765, i.e. near-black) AND light text (rgb sum > 600, i.e. near-
    // white) AND font-size < 28 OR weight < 700. Inheritance is NOT
    // walked — only direct background-color of the element itself — so
    // a <span> inside a black <div> won't trigger this. That's a known
    // limitation; the common-case (block-level inverse band) is caught.
    if (fs) {
      const bgSum = rgbSum(cs.backgroundColor);
      const fgSum = rgbSum(cs.color);
      const fw = parseInt(cs.fontWeight, 10) || 400;
      if (bgSum !== null && bgSum < 60 && fgSum !== null && fgSum > 600
          && (fs < 28 || fw < 700)) {
        findings.push({
          rule: 'inverse_text_too_small',
          severity: 'warning',
          message: (
            `${el.tagName.toLowerCase()} renders white-on-black at ` +
            `${fs}px / weight ${fw} — thermal head heat bleed erodes ` +
            `the white reverse below 28 px / bold. Use bordered ` +
            `black-on-white instead.`
          ),
          selector: el.tagName.toLowerCase(),
        });
      }
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


def pre_render_lint(
    html: str,
    *,
    source_path: Path | None = None,
    timeout_ms: int = 5000,
) -> list[LintFinding]:
    """Run pre-render lint on the HTML.

    ``source_path`` mirrors ``render_html_to_png``'s argument: when given,
    relative refs in the source HTML resolve against the source dir, so
    the lint sees the same resolved URL set the renderer will. Without it,
    relative refs would fail to load and the stylesheet/url() walks would
    silently miss external CDN refs hidden behind a relative-looking path.

    Security posture mirrors ``render_html_to_png``: page JS is disabled
    and the route filter is a strict allowlist (data:, render dir, source
    dir). External-resource detection works at the URL-string level in JS
    (``el.src``, ``rule.cssText``) regardless of whether the fetch went
    through, so blocking the fetch doesn't hide the finding.
    """
    final_html = inject_into(html, source_path=source_path)
    fonts_uri = font_dir_uri()
    source_dir_uri: str | None = None
    source_dir_real: Path | None = None
    if source_path is not None:
        source_dir_real = source_path.resolve().parent
        source_dir_uri = source_dir_real.as_uri() + "/"

    blocked_urls: list[str] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            context = browser.new_context(
                viewport={"width": 576, "height": 800},
                java_script_enabled=False,
            )
            context.set_default_timeout(timeout_ms)
            page = context.new_page()
            with tempfile.TemporaryDirectory() as render_td:
                render_dir = Path(render_td).resolve()
                render_html = render_dir / "page.html"
                render_html.write_text(final_html, encoding="utf-8")
                render_dir_uri = render_dir.as_uri() + "/"

                def _route(route):
                    # Same allowlist decision as render_html_to_png (single
                    # source of truth): a symlink under the source dir that
                    # resolves outside it must be blocked in the lint pass too,
                    # or `tprint-design lint` would fetch the outside file even
                    # though the renderer blocks it.
                    if _is_allowed_subresource(
                        route.request.url,
                        render_dir_uri=render_dir_uri,
                        fonts_uri=fonts_uri,
                        source_dir_uri=source_dir_uri,
                        source_dir_real=source_dir_real,
                    ):
                        route.continue_()
                        return
                    blocked_urls.append(route.request.url)
                    route.abort()

                page.route("**/*", _route)
                page.goto(render_html.as_uri(), wait_until="networkidle")
                raw = page.evaluate(_WALK_JS)
        finally:
            browser.close()

    findings = [
        LintFinding(
            rule=item["rule"],
            severity=LintSeverity(item["severity"]),
            message=item["message"],
            selector=item.get("selector"),
        )
        for item in raw
    ]
    # Fallback: any URL the route handler blocked but the JS walker did
    # NOT surface (e.g. @import nested inside a cross-origin sidecar
    # stylesheet whose cssRules access throws) gets one finding here.
    # The route-handler list is the ground truth — if it was blocked,
    # the page tried to fetch external content.
    already_reported_external = {
        url
        for f in findings
        if f.rule == "external_resource"
        for url in [_extract_url(f.message)]
        if url
    }
    seen_blocked: set[str] = set()
    for url in blocked_urls:
        if url in seen_blocked or url in already_reported_external:
            continue
        seen_blocked.add(url)
        findings.append(LintFinding(
            rule="external_resource",
            severity=LintSeverity.ERROR,
            message=(
                f"blocked external request to {url} "
                f"(detected by route handler; not surfaced via CSS walk — "
                f"likely inside a cross-origin sidecar stylesheet or a "
                f"nested @import)"
            ),
            selector=None,
        ))
    return findings


def _extract_url(message: str) -> str | None:
    """Pull a URL substring out of a finding message for dedup. The walker
    consistently embeds URLs as ``http://`` or ``https://`` substrings.
    """
    for scheme in ("https://", "http://", "wss://", "ws://"):
        idx = message.find(scheme)
        if idx == -1:
            continue
        rest = message[idx:]
        end = len(rest)
        for stop in (" ", " ", "—", "—"):
            stop_idx = rest.find(stop)
            if stop_idx != -1 and stop_idx < end:
                end = stop_idx
        return rest[:end].rstrip()
    return None
