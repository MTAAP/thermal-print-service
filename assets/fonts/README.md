# Vendored Fonts

These fonts are bundled with the print service so the renderer is self-contained.

| Font | Files | Upstream | License |
|---|---|---|---|
| Spleen 8x16 | `spleen/spleen-8x16.bdf` + `spleen/LICENSE` | https://github.com/fcambus/spleen | BSD-2-Clause |
| Spleen 5x8 | `spleen/spleen-5x8.bdf` + `spleen/LICENSE` | https://github.com/fcambus/spleen | BSD-2-Clause |
| IBM Plex Sans Medium / Bold | `plex/IBMPlexSans-{Medium,Bold}.ttf` | https://github.com/IBM/plex | OFL-1.1 |
| JetBrains Mono Regular / Bold | `jetbrains-mono/JetBrainsMono-{Regular,Bold}.ttf` | https://github.com/JetBrains/JetBrainsMono | OFL-1.1 |
| Noto Sans SC Regular / Bold | `noto-sans-sc/NotoSansSC-{Regular,Bold}.ttf` | https://github.com/googlefonts/noto-cjk | OFL-1.1 |

## Upstream URLs Actually Used

| File | URL |
|---|---|
| `spleen/spleen-8x16.bdf` | https://raw.githubusercontent.com/Tecate/bitmap-fonts/master/bitmap/spleen/spleen-8x16.bdf |
| `spleen/spleen-5x8.bdf` | https://raw.githubusercontent.com/Tecate/bitmap-fonts/master/bitmap/spleen/spleen-5x8.bdf |
| `plex/IBMPlexSans-Medium.ttf` | https://github.com/IBM/plex/raw/master/packages/plex-sans/fonts/complete/ttf/IBMPlexSans-Medium.ttf |
| `plex/IBMPlexSans-Bold.ttf` | https://github.com/IBM/plex/raw/master/packages/plex-sans/fonts/complete/ttf/IBMPlexSans-Bold.ttf |
| `jetbrains-mono/JetBrainsMono-Regular.ttf` | https://github.com/JetBrains/JetBrainsMono/raw/master/fonts/ttf/JetBrainsMono-Regular.ttf |
| `jetbrains-mono/JetBrainsMono-Bold.ttf` | https://github.com/JetBrains/JetBrainsMono/raw/master/fonts/ttf/JetBrainsMono-Bold.ttf |
| `noto-sans-sc/NotoSansSC-Regular.ttf` | https://github.com/googlefonts/noto-cjk/raw/main/Sans/SubsetOTF/SC/NotoSansSC-Regular.otf |
| `noto-sans-sc/NotoSansSC-Bold.ttf` | https://github.com/googlefonts/noto-cjk/raw/main/Sans/SubsetOTF/SC/NotoSansSC-Bold.otf |

Note: the IBM Plex Sans spec URLs pointed to `IBM-Plex-Sans/fonts/complete/ttf/` (404 — old repo layout).
The correct path after the repo was reorganized into a monorepo is `packages/plex-sans/fonts/complete/ttf/`.

## Roles

- **Body** (paragraph, checklist, kv, bullets, numbered, ascii_art default): Spleen 8x16, bitmap, pixel-perfect at 1-bit. ~72 cols across the 576 px head. Replaced Cozette 13 px in v0.6.0 — Cozette renders crisp but reads small at arm's length.
- **Small** (`ascii_art` `font: "small"`): Spleen 5x8, bitmap, ~115 cols.
- **Display** (header, section_title, large_text, pull_quote, footer): IBM Plex Sans Medium/Bold, vector, rendered through `supersample_render` at 2× target size and Atkinson-dithered to 1-bit.
- **Drop cap**: IBM Plex Sans Bold at 56 px through `supersample_render` with `factor=4, dither="ordered"` so large solid regions stay saturated where Atkinson would shed too much error.
- **Code** (code blocks, kv values where monospace alignment matters): JetBrains Mono Regular/Bold, vector, supersampled 2×→Atkinson.
- **CJK Fallback** (Chinese, Japanese, Korean characters): Noto Sans SC Regular/Bold, vector, used automatically when CJK characters are detected. Mixed Latin/CJK text is segmented and rendered with the appropriate font for each segment.
