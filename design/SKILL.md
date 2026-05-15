---
name: tprint-design
description: Use when composing intricate one-off thermal designs that the JSON block schema can't express — decorative borders, hand-tuned typography, multi-region layouts. Local CLI; the agent writes HTML, compiles to a thermal-ready 1-bit PNG, looks at it, iterates, then prints.
---

# tprint-design

A local CLI that compiles HTML+CSS into a thermal-ready 1-bit 576-px PNG
and runs a structured lint pass. Designed for the agent loop: write,
compile, read the rendered PNG inline, iterate, print only when ready.

## When to use this vs print_document

- `print_document` (JSON blocks): the default. Use it for any design the
  block schema covers. It is faster, validated, and renders on the Pi
  itself, so it works for any tailnet client — not just MCP.
- `tprint-design`: for intricate one-offs where blocks feel limiting.

## Workflow

```
tprint-design init my.html --template literary  # optional scaffold
# edit my.html with the Write tool
tprint-design compile my.html                   # → my.png + my.lint.json
# Read my.png — Claude Code shows the dithered output inline
# iterate
tprint-design print my.html                     # send to the Pi
```

`tprint-design info` prints the rulebook (live width, fonts, lint rules)
and `--json` emits it as a structured payload.

## Defaults that are auto-injected

- Body width 576 px with 24 px gutters (528 px live area).
- Black-on-white forced; system dark-mode ignored.
- @font-face for IBM Plex Sans / JetBrains Mono / Noto Sans SC.
- Anti-aliasing off, shadows off.

## Lint exit codes

- `0` — clean (warnings allowed).
- `1` — lint errors. `print` refuses; fix and recompile.
- `2` — render or IO error. Page failed to load, file missing, Pi unreachable.
