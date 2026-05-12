# Schema Changelog

Each removal/rename gets a one-line entry with the renderer version it landed in
and the migration hint surfaced in 400 responses.

## v0.9.0

Literary-frame block additions — seven new block types for letter, journal,
news-clipping, and scroll-style documents. All backwards-compatible (no
removals or renames).

**New block types:**

- **`epigraph`** — `text` (required, 1–2000), optional `attribution` (≤200).
  Plex Medium italic 16, indented 60 px on both sides; attribution rendered
  right-aligned beneath in italic 13 with em-dash prefix.
- **`byline`** — `text` (required, 1–100). Plex Medium italic 14, left.
- **`dateline`** — `location` (required, 1–60), `date` (required, 1–60).
  Plex Bold 14, both fields uppercased at render time, formatted
  `{LOCATION}, {DATE} ——`.
- **`salutation`** — `text` (required, 1–120). Plex Medium 18 (body size),
  left, extra bottom pad so the body sits a beat below.
- **`signature`** — `name` (required, 1–80), optional `closing` (≤80). Plex
  Medium italic 18, right-aligned; name prefixed with `— `, closing rendered
  on its own line above.
- **`colophon`** — `text` (required, 1–500). Plex Medium italic 14, centered
  in a 360 px column.
- **`address`** — `lines` (required list, 1–8 entries, each 1–100). Plex
  Medium 16, left, 22 px line step (tighter than body 26).

None of the new blocks accept `align` — each has an intrinsic placement
suited to its role. The `ALIGN_ALLOWED` set is unchanged.

## v0.8.0

Audit-fixes pass — schema additions, loosened floors, renderer changes for
previously dead enums, and a body-font swap. No removals or renames; all
existing inputs continue to parse.

**Schema additions / loosening (backwards-compatible):**

- **`CodeBlock.size`** — new enum `sm | md | lg`, default `md` (16 px). `sm`
  is 14 px (the prior fixed size), `lg` is 18 px. Migration: omit `size` to
  get the new thermal-safe default; existing payloads without `size` now
  render at 16 px instead of 14 px.
- **`ImageBlock.caption`** — new optional field (max 120 chars). Renders
  centered below the image; mirrors `QrBlock.caption`. Previously composing
  an image with a caption required a second `paragraph` block.
- **`OrnamentBlock.pattern`** — three patterns added: `waves`, `art_deco`,
  `minimal_dots`. Existing patterns (`stars`, `diamonds`, `leaves`,
  `geometric`) keep their names; the glyphs they render are now Unicode
  dingbats at display weight rather than ASCII tiles at body size.
- **`DropCapBlock.first_letter`** — max_length raised 1 → 3 to accept
  literary incipits like `"The"` and `"In"`. Single-char drop caps still work.
- **`RichTextBlock.runs`** — min_length lowered 2 → 1 so a single italic or
  inverse run is valid. Previously a one-run intent had to fall back to
  `paragraph` with `emphasis`.

**Schema field descriptions (new):**

Every styled / enum field now carries a `description=` that lands in the
JSON Schema delivered to the MCP tool catalog: `header.style`,
`header.subtitle`, `section_title.style`, `paragraph.emphasis`,
`rich_text.size`, `large_text.size`, `code.size`, `pull_quote.attribution`,
`drop_cap.first_letter`, `bullets.marker`, `rule.style`, `ornament.pattern`,
`spacer.lines`, `gradient_band.direction`, `progress_bar.label`,
`sparkline.label`, `qr.size`, `qr.caption`, `barcode.format`, `image.dither`,
`image.bleed`, `image.caption`, `ascii_art.font`, `tear_here.label`,
`feed.lines`, and `kv.{key,value}`. No behavior change — purely
agent-discoverability.

**Renderer changes (the schema was honest already, the renderer caught up):**

- **`header.subtitle`**, **`header.ornamental`**, **`header.minimal`** were
  previously silent no-ops (schema accepted, renderer ignored). Now distinct:
  `inverse_band` (default) keeps the loud white-on-black band; `ornamental`
  flanks the title with ◆ glyphs at display weight; `minimal` puts the title
  above a hairline rule. `subtitle` renders below the title in display medium.
- **`section_title.inverse`** and **`section_title.rule_above`** were
  similarly silent. Now `inverse` paints a section-weight band and
  `rule_above` puts a hairline rule above the title.
- **`qr.caption`** was accepted into the schema and silently dropped; now
  renders centered below the QR.
- **`rich_text` size `sm` 12 → 14 px** and **`pull_quote.attribution` 12 →
  14 px**, matching the existing thermal-safe stroke floor (the same one
  that bumped footer 14 → 16 in earlier work).
- **`spacer.lines`** unit corrected: was 14 px per line (below body
  line-height), now `BODY_LINE_H` (26 px) so "1 line" matches one line of
  body. `feed.lines` stays at 14 px — `feed` is paper-feed-line semantic,
  distinct from in-document whitespace.
- **`progress_bar` / `sparkline` / `tear_here` labels** were drawn via raw
  `d.text()` at the body font, causing collision with the bar/dashes.
  Labels now render via `render_body_line` (supersampled) with a full
  body-line-height label band reserved above.
- **`rule` widths normalized to 2 px** across all five styles. Prior
  width-1 dashed/dotted/double/wave rules were nearly invisible compared
  to width-2 `solid`.

**Body font swap (visual change, no schema impact):**

Prose blocks (`paragraph`, `bullets`, `numbered`, `checklist`,
`drop_cap.rest`, `kv` keys) switch from JetBrains Mono Bold 18 to **IBM
Plex Sans Medium 18**, supersampled through the same Atkinson path.
Long-form documents (briefings, scrolls, recipe cards) now read 'literary'
rather than 'computer-y'. Monospace is retained where the glyph grid is
structural: `code`, `kv` values, `table_compact` cells, and bullet marker
glyphs.

`kv` is now a two-font split: prose keys (proportional) + mono values.
Within each row both cells are bottom-aligned within `BODY_LINE_H` so the
two faces share an apparent baseline despite different bbox metrics.

The constant `BODY_GLYPH_PX = 11` is removed (no callers — proportional
prose has no uniform glyph width; the only consumer, `numbered` prefix
column width, now measures the actual rendered prefix).

## v0.1.0 (initial)

- Initial schema landed; 27 block types declared, 13 rendered (Phase 3 minimum).
  Remaining 14 land in Phase 5; their renderers raise NotImplementedError until
  then, and the document renderer substitutes a placeholder per spec §11.
- No removals or renames; all migration_hint values are null.

## v0.5.0

- All 27 block types declared in v0.1.0 are now rendered. The "[unsupported block]"
  placeholder fallback should never trigger in normal use.
- Renderer pipeline: 14 new renderers landed (large_text, bullets, numbered,
  pull_quote, ornament, gradient_band, progress_bar, sparkline, rich_text, code,
  drop_cap, barcode, ascii_art, table_compact).
- Schema unchanged from v0.1.0; this is a renderer-only MINOR bump per spec §6.
- Known v1 limitations (deferred to a follow-up):
  - `cut` block currently renders a 1-px marker but does not produce a physical
    mid-document cut; v1 ships as one continuous print per POST. Multi-chunk
    PNG cache + multi-call transport refactor planned.
  - `rich_text` `italic` and `underline` flags are accepted by the schema but
    not visually distinguished by the renderer (only `bold` and `inverse` honored).
  - `ascii_art` `font: "small"` reuses Cozette with tighter line height; no
    smaller bitmap font is bundled.

## v0.5.1

- Fix: printer-offline failures (USB unplugged, missing `/dev/usb/lp0`,
  permission errors at open-time) are now correctly treated as retryable,
  not `unknown_partial`. The transport adapter introduces a
  `PrinterUnavailable` exception that is plain `Exception` (not `OSError`),
  so the worker's `IOError` branch (which writes `unknown_partial`) no
  longer catches "could not open device" failures. Spec §11 retry semantics
  now match: USB-disconnected printer → job stays in queue, retried every
  `retry_interval_s`, until `max_retry_age_s` (24 h default) elapses.
- IOError raised *during* `print_image` (cable yanked mid-stream) still
  maps to `unknown_partial` per spec — the boundary is "did any byte hit
  the printer?" not "did anything go wrong?".

## v0.7.2

CJK fallback rendering (no public schema change).

- **Body, display, and code text now fall back to Noto Sans SC Bold
  for codepoints missing from their primary font.** A single per-codepoint
  cmap-coverage check inside ``supersample_render`` segments the input
  into runs by which font owns each codepoint, renders each run at the
  supersample size, then composites baseline-aligned via
  ``font.getmetrics()`` before the existing downsample + Atkinson-dither
  pass. Pure-Latin text bypasses the composite path even when the
  fallback is available, so the fast path stays fast.
- **Atom-aware wrap.** ``wrap_body_text`` replaces ``textwrap.wrap`` in
  paragraphs and list blocks. Atoms are Latin words (broken at
  whitespace), individual non-primary-cmap codepoints (so Chinese,
  Japanese, Korean and other spaceless scripts wrap mid-run), and
  whitespace runs. Atoms wider than the line cap (long URLs, file
  paths, hashes) split at codepoint boundaries.
- **drop_cap wrap rebuilt** on the same atom primitive with a per-line
  width callback so the indented-then-full-width two-phase wrap composes
  with mixed-script content.
- **Body line height bumped 24 → 26 px** to fit the worst-case mixed
  line height (Noto SC Bold's larger ascent at 18 px).
- **New asset:** ``assets/fonts/noto-sans-sc/NotoSansSC-{Regular,Bold}.otf``
  (SubsetOTF, ~8 MB each, OFL-1.1) plus LICENSE. Activates automatically
  when present; absence falls back to the v0.7.1 behavior (.notdef
  glyphs for non-Latin codepoints).
- **New runtime dep:** ``fonttools>=4.50`` for one-time cmap inspection
  per font path. Cached as ``frozenset[int]`` via ``functools.lru_cache``.

## v0.7.1

Renderer follow-up to v0.7.0 (no public schema change).

- **Body font: Spleen 12x24 → JetBrains Mono Bold @ 18 px.** v0.7.0
  bumped to Spleen 12x24 to fix legibility, but the bitmap font has
  ~1-px strokes and thermal heads under-print thin lines, so it still
  printed pale. JetBrains Mono Bold rendered through the supersample +
  Atkinson-dither path (the same pipeline display headers use) lays
  down a heavier, blacker stroke that survives the head's heat
  transfer. Same monospace character; ~48 cols fit across the live
  width. Drop-cap size scales 80 → 72 px to keep the 3-body-line wrap.
- **Refactor: every body-text caller goes through ``render_body_line``.**
  Paragraph, drop_cap, bullets, checklist, numbered, kv, and
  table_compact now render each line via the supersample helper
  instead of a direct ``ImageDraw.text()`` call. kv collapses to a
  single-font two-column layout because the body and value columns
  share the same JetBrains Mono Bold handle.
- **Drop: Spleen 12x24 BDF.** No longer used; removed from
  ``assets/fonts/spleen/``.

## v0.7.0

Renderer bump (no public schema change).

- **Body font: Spleen 8x16 → Spleen 12x24.** Paragraph and list copy now
  render at 24 px native instead of 16 px (~1.5× larger), the next size
  up in the Spleen distribution. Reading a morning brief at arm's length
  is the forcing function — 8x16 reads small on 80mm thermal stock.
  ~44 cols fit across the live width (528 px) instead of ~66. Drop-cap
  size scales 56 → 80 px to keep the 3-line wrap rhythm. ascii_art
  ``font: "default"`` keeps Spleen 8x16 (now exposed via `fonts.mono()`)
  because char-grid art is sized for fixed column counts.
- **Fix: bullets/checklist/numbered/kv now wrap long items.** Before
  this change every list block drew each item as a single un-wrapped
  ``ImageDraw.text()`` call — text past the live width was silently
  truncated at the canvas edge. Items now wrap at the body grid width
  with a hanging indent that matches the marker / box / prefix offset,
  matching how `paragraph` already wraps. Vertical extent grows with
  the wrapped line count.

## v0.6.0

Renderer + behavior bump (no public schema change). Closes the four
documented v0.5.x renderer gaps.

- **Behavior: `cut` block produces a real hardware cut.** Pre-v0.6.0 the
  block rendered a 1-px marker and the entire document went to the
  printer as one continuous strip. The renderer now splits the document
  into N chunks at every `cut` block; the worker prints each chunk and
  fires the cutter between them. Empty segments (leading cut, trailing
  cut, adjacent cuts) collapse — the printer never receives a no-op
  chunk just to fire the cutter on blank paper. **Precedence:** a
  trailing `cut` block forces a hardware cut on the final chunk even if
  `options.auto_cut: false`. The explicit cut block is treated as the
  user's intent at that position.
- **Behavior: multi-chunk failure is non-retryable once any chunk
  printed.** If chunk 0 prints successfully and chunk 1 raises (for any
  reason, including the normally-retryable `PrinterUnavailable`), the
  job lands in `unknown_partial`. Retrying would re-print the chunks
  already on paper and the user would get duplicate output. The
  zero-chunks-printed path retains the existing retry semantics.
- **Behavior: empty-content documents return 400.** A document
  containing only `cut` blocks (or no blocks) renders to zero chunks;
  the HTTP layer rejects it instead of queuing a no-op job.
- **Renderer: `rich_text` italic and underline.** `italic: true` runs
  are rendered with synthetic-slant (~12° shear via PIL `AFFINE`).
  `underline: true` runs gain an axis-aligned 1-px rule below the
  fragment. Composition order is italic → underline → inverse. The
  `rich_text` line layout switches from a fixed 22 px line height to
  per-line max-height with bottom-aligned baselines, so mixed-size runs
  share a footing and `size: lg` plus underline no longer spills into
  the next line.
- **Renderer: `ascii_art` `font: "small"` uses a real small bitmap
  font.** Spleen 5x8 (BSD-2-Clause, Frederic Cambus) is vendored under
  `assets/fonts/spleen/`; `FontRegistry` exposes it via `small()`.
  ~115 columns fit across the 576 px head, vs Cozette's ~46.
- **Cache: chunked PNG layout.** Rendered jobs are cached as
  `<job>__<index>.png` (one per chunk). Reads transparently fall back
  to the legacy single-PNG layout (`<job>.png`) so jobs cached before
  the upgrade still drain. The fallback can be removed in v0.7.0 once
  the cache TTL has expired all pre-v0.6.0 entries.
- **HTTP: dry-run preview now includes `X-Chunk-Count`.** The body is
  still a single concatenated PNG (cut markers visible as 1-px lines)
  so the preview shows where cuts will happen.
- **Tests: lifespan-aware HTTP client + DRY font-dir fixture.** Adds
  `asgi-lifespan` as a dev dep and a `lifespan_client` helper in
  conftest so tests that need the worker drained (e.g. metric
  increments) can use a single `async with` block instead of manually
  cycling `worker.start()/stop()`. Render-test files no longer pin
  `FONT_DIR = "/Users/.../"`; the path lives in `conftest.DEFAULT_FONT_DIR`
  and is exposed via `font_dir` and `fonts` fixtures.

## v0.5.2

Codex review pass — five fixes, no public schema change.

- **Fix (P1): Per-job options now persist across restart.** `JobRecord`
  gains `auto_cut`, `feed_lines_after`, and `expires_at` fields, populated
  on `accepted`. `cmd_run` rebuilds the in-memory `options_store` from the
  log via `options_from_replay()`. Pre-fix, a crash/restart caused queued
  jobs to fall back to `(True, 2, None)` — losing `auto_cut=False`, custom
  feed lines, and (worst) `expires_at`, so expired jobs could print after
  a restart. Pre-v0.5.2 records have `auto_cut=None` and the recovery
  helper skips them, preserving exact pre-fix behavior for old jobs.
- **Fix (P1): Naive `expires_at` no longer wedges the worker.** Comparing
  a tz-aware "now" with a naive ISO timestamp raised `TypeError`, which
  bypassed the worker's `except ValueError` and bubbled to the
  unexpected-exception branch — the job was logged as a transient retry
  but never re-enqueued. Now naive `expires_at` is treated as UTC
  (defensive; the API should still reject naive at submission time) and
  both `ValueError` and `TypeError` are caught.
- **Fix (P1): `/jobs/{id}/reprint` enforces `max_queue_depth`.** The
  reprint endpoint bypassed the cap that `/print` and `/print/raw` apply,
  so repeated reprints could exhaust queue capacity even when normal
  submissions were blocked. Both reprint branches (cached PNG and JSON
  re-render) now hit the same depth check.
- **Fix (P2): Render-time client errors return 400, not 500.** Schema-
  valid input that failed at render time because of bad user content
  (malformed PNG bytes inside an `image` block, invalid characters for an
  EAN13 `barcode`) was wrapped as a 500. Renderers now raise
  `RenderInputError`; the HTTP layer maps it to a structured 400 with
  `block_index` and `field` populated. Other render exceptions remain
  500. The structured-400 contract is now consistent across schema
  validation and render-input failures.
- **Fix (P2): Test fixtures use a repo-relative font path.** Replaces a
  hard-coded absolute home-directory path so the suite is portable
  across CI and other developer machines.
