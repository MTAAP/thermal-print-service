# Manual smoke tests for tprint-design

Run these before declaring v1 done. They cover ground that's hard to
unit-test: the actual printer, the agent loop, and clear-error paths.

## 1. Real-printer smoke (3 designs)

Pick three fixture designs that span the surface — a frame-heavy
literary piece, an ASCII-art piece, a banner with hand-tuned typography:

```bash
tprint-design init smoke-literary.html --template literary
tprint-design init smoke-banner.html  --template banner
# Hand-author smoke-ascii.html with a JetBrains Mono ASCII piece.

tprint-design compile smoke-literary.html
tprint-design compile smoke-banner.html
tprint-design compile smoke-ascii.html

tprint-design print smoke-literary.html
tprint-design print smoke-banner.html
tprint-design print smoke-ascii.html
```

Eyeball each printed page for:
- [ ] Dither artifacts (acceptable: granular texture; not acceptable: bands/stripes)
- [ ] Font fidelity (matches what the preview showed)
- [ ] No clipping at the gutters
- [ ] No surprise blank space at the tail
- [ ] Sensible auto-cut at the bottom

## 2. Agent loop dry-run

Drive the full workflow as an agent would:

```
get_design_guidelines (via MCP)
tprint-design init scratch.html --template blank
# edit scratch.html
tprint-design compile scratch.html
# Read scratch.png
# iterate 4 more times
tprint-design print scratch.html --dry-run
```

- [ ] Five iterations complete in well under a minute (warmup-aware).
- [ ] PNG is visible inline via Claude Code's Read tool.
- [ ] `lint.json` shape matches the spec.

## 3. Error paths

- [ ] `tprint-design compile broken.html` (with malformed HTML) — fails
      with exit 2 and a single-line actionable error on stderr.
- [ ] `tprint-design compile cdn.html` (with `<img src="https://...">`)
      — exits 1 with `external_resource` error in the lint report.
- [ ] `tprint-design compile hung.html` (with `<script>while(true){}</script>`)
      — fails with exit 2 and "render timeout" in the message within ~5 s.
- [ ] `tprint-design print x.html` with `PRINT_SERVICE_URL` unset — exits 2
      with a clear "PRINT_SERVICE_URL is unset" message.
