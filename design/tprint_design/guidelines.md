# Thermal design guidelines

Live print area: **528 px** (24 px gutters on a 576 px head).
Density: **8 dots/mm** (1 mm = 8 px). Default max length: **2000 mm**.

## Rules of thumb

- **Stay grayscale.** No color. Anything with chroma trips a lint error.
- **Body fonts ≥ 14 px.** Below 12 px is a warning; below 9 px is an error.
- **Use the bundled fonts** for guaranteed rendering: IBM Plex Sans,
  JetBrains Mono, Noto Sans SC.
- **No shadows.** `text-shadow` and `box-shadow` dither to noise.
- **Local resources only.** No CDN/`https://` in `src`/`href`. The
  renderer blocks external network and lint flags it as an error.
- **Width = 576 px.** The thermal-reset stylesheet pins the body.
  Override with `body { padding: 0 }` to bleed; lint will warn.
- **Watch ink density.** A near-empty page (>95% white) probably means
  missing content — lint warns.
- **Inverse text (white on black) only at display sizes.** Safe at
  ≥ 28 px **and** bold weight. At body sizes (14–22 px) the print head's
  lateral heat bleed darkens the surrounding "white" pixels until the
  reverse is illegible. For body-size emphasis, use bordered
  black-on-white instead (a thick `border-left` reads as a quote bar;
  `border: 3px double` reads as a button). This rule is observational —
  the lint can't catch it because the failure happens at the print
  head, not the renderer.

## Workflow

1. `tprint-design init my.html` (optional; drops a starter scaffold).
2. Edit `my.html` (Write tool).
3. `tprint-design compile my.html` — produces `my.png` (final) +
   `my.preview.png` (grayscale) + `my.lint.json` (structured report).
4. `Read my.png` — Claude Code surfaces it as an image. Look at the
   dithered output. Read `my.lint.json` (or stdout summary) for warnings.
5. Iterate: edit → compile → look. No paper moves.
6. `tprint-design print my.html` — recompiles + posts to the Pi.
   `--dry-run` validates without printing.

## Fonts (bundled)

- `'IBM Plex Sans'` — body sans (Medium + Bold weights).
- `'JetBrains Mono'` — code/mono.
- `'Noto Sans SC'` — Chinese fallback.
