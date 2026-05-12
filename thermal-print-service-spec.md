# Thermal Print Service — Project Spec

**Owner:** Maintainer
**Status:** Living implementation spec
**Last updated:** 2026-05-09
**Scope:** Printer-service substrate only. Sender composition logic (what gets printed, when, by whom) is explicitly out of scope and belongs in each sender's spec.

## 1. Vision

A thermal receipt printer on the desk that any agent or service can print to over the tailnet. A **general-purpose physical notification surface**: anything that can produce structured content can produce paper. The day-one forcing function is a daily morning briefing, but the service makes no assumptions about what gets printed — that's each sender's concern.

I want the output to be *beautiful*: typographically considered, visually consistent across senders, and — when the moment calls for it — playful. Posters. Pull quotes. Dithered photos. Long-form essays meant to roll up like a scroll. Tear-and-share notes. Receipt poetry. The constraint of 80mm-wide thermal paper is the medium, not the limit.

Secondary goal: make this the easiest substrate to add new ambient print jobs to over time. Adding a new sender should be one HTTP call away.

## 2. Non-goals

- Not a POS receipt system. No cash drawer, no transaction logging.
- Not a public service. Tailnet-only, no public-internet exposure.
- Not high-throughput. Designed for ~1–20 print jobs per day, not hundreds per hour.
- Not multi-user. Single user (me), single printer, multiple senders.
- Not a beautiful screen UI project. The "frontend" is paper.
- Not trying to reimplement HTML. The block schema stays flat and small; if a layout needs columns, tables, or wrapping, it doesn't belong on 80mm paper.

## 3. Hardware

| Component | Choice | Notes |
|---|---|---|
| Printer | NetumScan 80mm, USB+Ethernet, ESC/POS | 576 dots/line, 220mm/s, auto-cutter, EPSON command set confirmed on self-test. Calibrated at 8.0 dots/mm on 2026-05-09. |
| Compute | Raspberry Pi Zero 2 W | Quad-core, 512MB, built-in 2.4GHz WiFi + BT 4.2 |
| Connection | Pi → printer via USB (OTG cable) | Printer's Ethernet unused; Pi is the only network endpoint |
| Power | 2× wall plugs: 12V brick (printer) + USB-C 5V (Pi) | Single dual-outlet, fully portable |
| Network | WiFi (home + travel hotspot) | No Ethernet drop required |
| Mounting | 3M VHB, Pi attached to printer body | Single physical unit |

The whole assembly is a self-contained appliance. Plug in, connect to WiFi once, lives on the tailnet from then on.

## 4. Architecture

```
┌─────────────────────────────────────────────────────────────┐
│ Senders (any agent / service / script on the tailnet)       │
│   - OpenClaw cron (deterministic, scheduled briefings)      │
│   - Claude Desktop / Code via MCP server (creative, ad-hoc) │
│   - n8n workflows (calendar API, GitHub events, etc.)       │
│   - iOS Shortcut, curl, anything that speaks HTTP           │
└──────────────────────────┬──────────────────────────────────┘
                           │ Tailscale (HTTPS)
                           │ POST /print  (JSON document)
                           ▼
┌─────────────────────────────────────────────────────────────┐
│ Pi Zero 2 W: "print.tailnet"                                │
│   ┌─────────────────────────────────────────────────────┐   │
│   │ FastAPI app (systemd unit, runs as `printer` user)  │   │
│   │                                                     │   │
│   │ Endpoints:                                          │   │
│   │   POST /print          → accept JSON document       │   │
│   │   POST /print/raw      → accept raw PNG (escape)    │   │
│   │   GET  /healthz        → printer status             │   │
│   │   GET  /jobs           → recent job log + reprint   │   │
│   │   GET  /schema         → self-documenting schema    │   │
│   │   POST /test           → hello-world print          │   │
│   │                                                     │   │
│   │ Pipeline:                                           │   │
│   │   1. validate JSON against block schema             │   │
│   │   2. render blocks → PIL image (576px wide)         │   │
│   │   3. persist job + enqueue wakeup (durable FIFO)    │   │
│   │   4. worker → python-escpos → USB → printer         │   │
│   │   5. log result, expose via /jobs                   │   │
│   └─────────────────────────────────────────────────────┘   │
│                           │ python-escpos / USB             │
│                           ▼                                 │
│                      [NetumScan]                            │
└─────────────────────────────────────────────────────────────┘
```

### Why this split

- **Pi owns presentation.** Every block type has a single render implementation on the Pi. Every sender benefits from the same typography, spacing, and visual rhythm. Visual consistency is free.
- **Senders own content.** Agents reason about *what* to print, never *how*. A small/cheap LLM can produce valid JSON; producing well-typeset PNGs would require pixel-level reasoning or expensive Pillow code execution per agent.
- **Schema is the contract.** Adding a new block type is a Pi-side change that all senders immediately benefit from. Adding a new sender is one HTTP call against an existing schema.

### Rendering pipeline

The renderer is the single source of typographic truth. Every text block, every glyph, every decorative element is composed in PIL and sent to the printer as raster image data. The printer's native text mode and codepage handling are intentionally unused.

**Why this commit:**
- One typography system shared by every sender, regardless of locale or character set. Umlauts, emoji, decorative quotes, mathematical symbols — all pixels, never codepage-dependent.
- The renderer is deterministic and self-contained: same JSON in → same PNG out (modulo `renderer_version`). Reprint, preview, and audit all become trivial.
- Pi owns the look. No leakage of printer-firmware bitmap fonts into the visual signature.

**Pixel grid:**
- 576 px wide (the print head's full dot count). Always.
- **Live area: 528 px**, with **24 px gutters** on each side. One global grid; every block respects it.
- mm is a derived quantity, never a renderer concern. Conversion happens at exactly three named points: `max_length_mm` enforcement, `estimated_paper_mm` in `POST /print` responses, `paper_used_mm` in `/jobs`. All three use a single `DPMM` constant pinned during Phase 1 calibration.

**Font stack:**

| Role | Font | Notes |
|---|---|---|
| Prose body (paragraph, bullets, numbered, checklist items, drop_cap.rest, kv keys) | **IBM Plex Sans Medium 18px** | Vector, rendered through the same supersample + Atkinson path as display text. Proportional face — reads 'literary' rather than 'computer-y'. Replaced the JetBrains Mono Bold body in v0.8.0. |
| Mono body (kv values, table_compact cells, bullet marker glyphs) | **JetBrains Mono Bold 18px** | Same supersample path. Retained where the glyph grid is structural (column alignment, marker visual weight). |
| Display (header, section_title, large_text, drop_cap, pull_quote) | **IBM Plex Sans Medium / Bold** | Vector. Rendered at 2× target size, then Atkinson-dithered to 1-bit to avoid antialias→threshold muddiness. |
| Code (code blocks, kv values where monospace alignment matters) | **JetBrains Mono Regular / Bold** | Vector. Same 2×→Atkinson treatment. |
| CJK fallback | **Noto Sans SC Regular / Bold** | Used for codepoints missing from the primary font. Wrapping is atom-aware: Latin words break at whitespace, non-primary-cmap codepoints can break per character. |

**Atkinson downsampling for vector text:** PIL renders vector glyphs to 8-bit greyscale at 2× the target raster size, then a single Atkinson dither pass produces the 1-bit output. This avoids the "muddy at small sizes" failure mode of naive PIL→threshold and gives display headlines a clean weighted edge.

### Why USB tethering (not Ethernet)

The printer has Ethernet, but with a Pi physically next to it, USB is cleaner:

- One network endpoint to manage (the Pi), not two.
- Printer never needs an IP, DHCP reservation, or LAN exposure.
- Whole appliance is portable: move it to the kitchen, plug into any outlet, reconnect WiFi, done.

## 5. Service contract

### `POST /print` — primary endpoint

```
Headers:
  Content-Type: application/json
  X-Idempotency-Key: 2026-05-09-morning   (optional, dedupes for 24h within sender scope)
  X-Sender: openclaw-cron                  (optional, for /jobs log)

Body: a Document (see §6)

Responses:
  202 Accepted
    {
      "id": "...",
      "queued_at": "...",
      "estimated_paper_mm": 187,
      "renderer_version": "1.4.2",
      "duplicate": false
    }
  400 Bad Request
    {
      "errors": [
        {
          "block_index": 3,
          "field": "align",
          "message": "unknown value 'justified'",
          "valid_values": ["left", "center", "right"],
          "migration_hint": null
        }
      ]
    }
  409 Conflict
    Same idempotency scope/key reused with a different payload hash.
  503 Service Unavailable
    { "reason": "queue_full" }
  413 Payload Too Large
    { "reason": "max_request_bytes" | "max_rendered_height_px" | "max_raw_height_px" | "max_decoded_image_pixels" }
```

The 400 error shape is contractual: every validator error includes `valid_values` for enum violations, and a `migration_hint` (string or null) for fields whose semantics moved between renderer versions. Senders get self-service recovery info; no out-of-band lookup required.

`202 Accepted` is only returned after the request has been validated, rendered, and durably written to the on-disk job log. The in-process queue is only a wakeup path for the worker; it is rebuilt from the job log on service start. Hardware state does not affect admission once the Pi service is reachable: printer disconnects, paper-out, and cover-open are worker/retry states, not `POST /print` rejection reasons.

Idempotency scope is `(X-Sender || "anonymous", X-Idempotency-Key)`. A byte-identical retry within the 24h idempotency TTL returns the original `202` shape with the same `id`, `queued_at`, and `"duplicate": true`; reuse of the same scoped key with a different payload hash returns `409`. Senders that rely on idempotency should set `X-Sender`; otherwise all missing-sender requests share the `anonymous` scope.

### `POST /print/raw` — escape hatch

For when an agent legitimately needs pixel control (photo prints, generative art, ASCII pieces the schema can't express). Accepts `Content-Type: image/png`, must decode as PNG, and must be exactly 576px wide. Same headers, same idempotency behavior, same durable acceptance rule, but no block-schema validation.

Raw PNGs still pass resource guards before acceptance: `max_request_bytes`, `max_raw_height_px`, and `max_decoded_image_pixels` are service config values. Malformed PNGs return `400`; oversized PNGs return `413`.

### `GET /schema`

Returns the **current** block schema as JSON — there is no schema version. The schema is a single living contract, refactored in lockstep with senders (§6, "Schema evolution"). Self-documenting: agents and the MCP server introspect at runtime; senders pinned at build-time stay in lockstep with the renderer or fail loudly via the 400 contract above.

Response: `{ "blocks": [...], "renderer_version": "1.4.2", "changelog_url": "..." }`

### `GET /healthz`

```json
{
  "printer_connected": true,
  "paper_present": true,
  "cover_closed": true,
  "clock_synchronized": true,
  "queue_depth": 0,
  "last_print_at": "2026-05-09T06:30:14Z",
  "last_error": null,
  "oldest_pending_age_s": null,
  "uptime_s": 184302
}
```

`printer_connected`, `paper_present`, and `cover_closed` are `true`, `false`, or `null` when this printer/transport cannot report the signal reliably. Phase 1 pins the actual status capability; unsupported hardware states are surfaced as `null` and worker failures collapse to `printer_unavailable`.

### `GET /jobs?limit=20`

Recent job log: `id`, `sender`, `document_type`, `queued_at`, `printed_at`, `status`, `paper_used_mm`, `renderer_version` (the renderer that produced the original output), `reprint_mode` (`"png_cached"` if the rendered PNG is still in the 7-day cache; `"json_rerender"` if it'll be re-rendered from stored JSON).

Each entry exposes a `reprint_url` pointing to `POST /jobs/{id}/reprint`. By default reprint uses `png_cached` when available (byte-exact replay — for the "cat knocked the paper" case). Append `?force=json` to re-render from JSON at the **current** renderer version (useful when typography has improved since the original print and you want to see the new look). If the cached PNG is evicted between listing and reprint, the service falls back to JSON re-render; if both JSON and PNG are gone, it returns `410 Gone`.

**Storage policy:**
- **JSON document** kept long-term, ring-buffer eviction at 10k jobs or 100MB (whichever first).
- **Rendered PNG** cached for 7 days, LRU evicted at a 100MB ceiling. Reprints older than 7 days fall back to JSON re-render automatically.
- **Active jobs and 24h idempotency records** are excluded from ring-buffer eviction. Eviction only applies to terminal jobs older than their idempotency TTL.
- Both caps are tunable via service config.

Disk-wear rule: acceptance writes the JSON job record and rendered PNG once, and terminal status writes once. Retry events are append-only JSONL records; log pruning drops oldest terminal-job history while preserving pending work.

### `POST /test`

Prints a fixed "hello, hardware works" page including a sample of each block type. Useful after physical moves and when debugging new block additions.

### Concurrency & queue model

The service runs a single FIFO worker draining a durable on-disk FIFO job log through an in-process wakeup queue. The printer is a single physical resource; concurrent `POST /print` requests are accepted in parallel by the HTTP layer only after they reserve queue capacity, render successfully, and persist the job. Jobs print in persisted arrival order. There is no coalescing — N separate POSTs produce N separate print jobs, each with its own `/jobs` entry and its own `auto_cut`. Composing a multi-section single print is the sender's job, via `cut` blocks within one document (§8).

Admission order is: payload-size guard, idempotency conflict/duplicate check, schema/PNG validation, queue-cap reservation, render under the single render semaphore, durable write, then `202`. Failures before the durable write return `400`, `409`, `413`, or `503 queue_full` and do not create a job. This keeps bursty HTTP load from spawning unbounded concurrent PIL renders on the Pi Zero 2 W, and duplicate idempotent retries avoid paying render cost.

**Two senses of "batching":**

| Sense | Where it lives | Behavior |
|---|---|---|
| Composition batching — one POST containing multiple logical sub-jobs | Sender, via `cut` blocks inside one document (§8) | Supported. Renderer treats it as one job; printer cuts mid-stream. |
| Queue-level coalescing — service merges N separate POSTs into one print | Would be a service-level feature | **Not done.** Each POST is a discrete job; arrivals print back-to-back, each with its own `auto_cut`. |

**Expiry at dequeue.** When a job reaches the head of the queue, the worker checks `options.expires_at` against the Pi's synchronized UTC clock. If it's past, the job is dropped with `status: "expired"` (not printed) and the worker moves to the next one. The check repeats on every retry attempt while a job is stuck at the head (e.g., during a paper-out wait per §11), so a job whose deadline passes mid-retry is dropped at the next 5-minute tick rather than waiting indefinitely. Expiry never reorders the queue. `expires_at: null` means no sender deadline.

**Retry ceiling.** Hardware-unavailable jobs with no sender deadline retry for `max_retry_age: 24h` by default, then become `status: "retry_timeout"`. This is a service self-protection ceiling, not an `expires_at` value; only sender deadlines produce `status: "expired"`.

**Queue cap.** Default `max_queue_depth: 100`. Overflow returns `503 Service Unavailable` with `{ "reason": "queue_full" }`. Senders should treat this as a backoff-and-retry signal. The cap is tunable via service config and counts persisted pending/retry jobs, not terminal history.

## 6. Document & block schema

### Document envelope

```json
{
  "document_type": "briefing",   // free-form label, used for /jobs grouping
  "options": {
    "auto_cut": true,            // hardware cut at end (default true)
    "feed_lines_after": 2,       // blank lines before cut (default 2)
    "preserve_paper": false,     // tighter spacing throughout (default false)
    "max_length_mm": 2000,       // safety cap, default 2000mm; null = unlimited
    "expires_at": null           // ISO timestamp; if set, queued job is dropped (not printed) past this time
  },
  "blocks": [ ... ]
}
```

**`expires_at`** lets time-sensitive senders express their own TTL. A daily-briefing sender can set it to 09:00 on the day it's relevant — if the printer was offline overnight and the queue still holds the job at 09:01, the service drops it and logs `expired` in `/jobs` rather than printing yesterday's content this morning. Default is `null` (no expiry).

### Block types

Each block has a `type` field; remaining fields depend on the type. The `align: "left" | "center" | "right"` field (default `left`) is declared per-block-type and accepted only by blocks whose alignment semantics are unambiguous text-on-page placement: `header`, `section_title`, `paragraph`, `rich_text`, `large_text`, `pull_quote`, `footer`, `image`. All other blocks reject `align` at validation — they either have internal alignment (`kv` and `table_compact` align by column; `progress_bar` and `sparkline` are width-fitted), are generated at a fixed centered size (`qr`, `barcode`), preserve internal whitespace where block-level alignment is ambiguous (`code`, `drop_cap`, `ascii_art`), or fit the full live area by definition (`rule`, `gradient_band`, `ornament`, `spacer`, `cut`, `tear_here`, `feed`).

#### Text & structure

| Type | Purpose | Key fields |
|---|---|---|
| `header` | Title band at top of document | `text`, optional `subtitle`, `style: "inverse_band" \| "ornamental" \| "minimal"` |
| `section_title` | Mid-document section heading | `text`, optional `style: "underline" \| "inverse" \| "rule_above"` |
| `paragraph` | Body text, auto-wrapped to width | `text`, optional `emphasis: "italic" \| "bold"` |
| `rich_text` | Multi-run mixed-emphasis text | `runs: [{text, bold?, italic?, inverse?, underline?, size?}]` (≥1 run; a single italic run is legitimate. `paragraph` with `emphasis` is still simpler for whole-paragraph emphasis.) |
| `large_text` | Banner-sized text for posters | `text`, `size: "xl" \| "xxl" \| "xxxl"` |
| `code` | Monospace block, preserves whitespace | `text` |
| `pull_quote` | Indented quote with vertical bar | `text`, optional `attribution` |
| `drop_cap` | First letter oversized, body wraps around | `first_letter`, `rest` |
| `footer` | Italic centered text at end | `text` |

#### Lists & data

| Type | Purpose | Key fields |
|---|---|---|
| `checklist` | Todo-style with `□` boxes | `items: string[]` |
| `bullets` | Plain bulleted list | `items: string[]`, optional `marker: "•" \| "—" \| "▸"` |
| `numbered` | Ordered list | `items: string[]` |
| `kv` | Aligned key-value pairs | `pairs: [{key, value}]` |
| `table_compact` | 2–3 column compact data | `rows: string[][]`, optional `headers` |

#### Visual & decorative

| Type | Purpose | Key fields |
|---|---|---|
| `rule` | Horizontal divider | `style: "solid" \| "dashed" \| "dotted" \| "double" \| "wave"` |
| `ornament` | Decorative pattern strip | `pattern: "stars" \| "diamonds" \| "leaves" \| "geometric"` |
| `spacer` | Vertical whitespace | `lines: number` (1–10) |
| `gradient_band` | Solid-to-stippled visual rhythm element | `direction: "down" \| "up"` |
| `progress_bar` | Visual progress indicator | `value: 0–1`, optional `label` |
| `sparkline` | Tiny inline chart for a numeric series | `values: number[]`, optional `label` |

#### Embedded objects

| Type | Purpose | Key fields |
|---|---|---|
| `qr` | QR code, PIL-rendered into the job raster | `data`, optional `caption`, `size: "sm" \| "md" \| "lg"` |
| `barcode` | Barcode, PIL-rendered into the job raster | `data`, `format: "CODE128" \| "EAN13" \| ...` |
| `image` | Embedded raster image | `png_base64`, optional `width_px` (1–528, default 528) for live-area placement, optional `bleed: true` to use the full 576 px print head, optional `dither: "atkinson" \| "floyd_steinberg" \| "ordered" \| "none"` (default `atkinson`) |
| `ascii_art` | Preformatted text art | `text`, optional `font: "default" \| "small"` |

#### Flow control

| Type | Purpose | Key fields |
|---|---|---|
| `tear_here` | Manual tear marker (no hardware cut) | optional `label` ("↓ for Sam ↓") |
| `cut` | Forces a hardware cut mid-document | (none) — used for multi-doc batches |
| `feed` | Forces extra paper feed | `lines: number` |

The schema is intentionally **flat and additive**. No nested layouts, no columns, no inline images-within-paragraphs. Resist the urge — thermal paper is one column, narrow, top-down, and the schema should reflect that.

### Schema evolution

The schema is a **single living contract**, not a versioned external API. There is no `X-Schema-Version` header, no `version` field in `/schema`, and no soft-deprecation alias period.

**Why:** This is a single-tenant appliance with controlled senders (OpenClaw cron, MCP server, n8n, iOS Shortcut, ad-hoc curl). Refactoring the schema in lockstep with its callers is more honest about the situation than pretending it's a versioned public API.

**Evolution rules:**

- **Adding a block type, field, or enum value:** ship it. Always safe, no ceremony. New surface area appears in `/schema` automatically.
- **Removing or renaming:** refactor every sender in the same change. Pi-side validator emits the structured 400 (with `valid_values` and `migration_hint`) for any straggler. The error response is the contract — senders self-heal or fail loudly.
- **Renderer behavior changes** that don't affect schema shape (typography tweaks, layout improvements) are tracked by `renderer_version`, not schema state — they're orthogonal.

`renderer_version` is SemVer from the service package. Any change that can alter rendered pixels increments at least PATCH; additive schema changes increment MINOR; removals/renames increment MAJOR and must have a `SCHEMA_CHANGELOG.md` migration hint. Build-time senders may cache `/schema` for ergonomics, but the Pi validator is authoritative at request time.

**Discipline:** maintain `SCHEMA_CHANGELOG.md` in the Pi service repo. Each removal/rename gets a one-line entry with the renderer version it landed in and the migration hint. The 400 response's `migration_hint` text is sourced from the changelog so the two never drift.

**Knock-on for the MCP server:** the MCP server reads `GET /schema` at boot and derives its tool surface from current schema. Claude through MCP can never request a removed block — it isn't in the tool catalog. Direct curl/n8n callers fail loudly with the 400 contract. Both paths self-heal.

## 7. Document patterns the schema must accommodate

The block schema is the substrate. These document patterns aren't features of the printer service — they're **pressure tests**: shapes the schema must be able to express elegantly, so any sender can compose them. The renderer doesn't enforce them; `document_type` is a free-form label senders use for `/jobs` grouping.

### Daily briefing (the forcing function)

Compact, scannable, ~20–30cm of paper. One header, 3–5 sections, checklist + paragraphs + a QR for the full agenda. Composition logic lives in the sender (e.g., OpenClaw); only the resulting shape concerns the service.

```json
{
  "document_type": "briefing",
  "blocks": [
    {"type": "header", "text": "Friday, May 9", "style": "inverse_band"},
    {"type": "paragraph", "text": "06:30 · Anytown · 14°C", "align": "center"},
    {"type": "rule", "style": "dashed"},
    {"type": "section_title", "text": "TODAY"},
    {"type": "checklist", "items": ["Draft Q3 report", "Reply to support ticket"]},
    {"type": "section_title", "text": "AVIATION"},
    {"type": "paragraph", "text": "Industry newsletter published a guidance update..."},
    {"type": "qr", "data": "https://example.com/agenda/...", "caption": "full agenda"},
    {"type": "footer", "text": "have a good one ☕"}
  ]
}
```

### Quick note

Single short message, fast print, ~5cm of paper. For "Sam called", "package arrived", "remember to bring passport". Optimized for low-friction ad-hoc printing from any agent.

### Long-form reader

Marathon-length document for actual reading. Drop caps, pull quotes, dithered images, generous spacing. Could easily run 1–2 meters of paper for a full essay or article. `options.preserve_paper: false`. The "scroll mode" — meant to be read, then rolled up.

### Banner / poster

Big text, decorative, vertical orientation. `large_text` blocks at `xxxl`, ornamental dividers, minimal content. For birthdays, motivational quotes for the wall, "WELCOME HOME" stretched across a meter of paper. `options.auto_cut: false` so you can chain multiple banners or trim manually.

### Tear-and-share

Multi-section document with `tear_here` markers between sections. Top section for me, bottom section for someone else in the household. Or recipe + shopping list as one print. Or: itinerary + boarding pass QR + hotel address, each in its own tearable strip.

### Photo print

Single dithered image with optional caption. Atkinson dithering on the NetumScan looks unexpectedly gorgeous — it's the thermal-printer equivalent of a Polaroid aesthetic. Use case: print of the day from my Leica scans, postcard-style note to leave for someone.

### Receipt poem / typography piece

Centered, decorative, typographically rich. Mix of `large_text`, `ornament`, `pull_quote`, `spacer`. The "I made this on purpose" document. Could be a daily haiku from the news agent, a quote-of-the-day, or an invitation.

### Calendar / week-at-a-glance

`kv` blocks for each day, inline `sparkline` for weather trend, `progress_bar` for week-completion. Vertical layout suits the medium naturally. Print on Sunday night, tape to the fridge.

### Generative art

Pure `image` or `ascii_art` blocks. Mandalas, perlin noise, ASCII fractals, pixel-art animals. The "printer goes brrr" mode. Pairs well with `/print/raw` for full pixel control.

## 8. Long-form & funky printing

Receipt printers are physically capable of essentially unbounded length — paper rolls are typically 80m. The constraint is taste, not hardware. The system should embrace this.

**Length policy:**

- Default `max_length_mm: 2000` (2m) as a safety against runaway prints.
- Senders can raise the cap to `null` (unlimited) explicitly when they mean it.
- `/print` response includes `estimated_paper_mm` so senders know what they're committing to before paper is consumed.
- A planned "preview mode" (`?dry_run=true`) returns the rendered PNG without printing, for testing long jobs.
- Even with `max_length_mm: null`, service-level `max_rendered_height_px` and render-timeout guards remain in force unless deliberately raised in config.

**Cut control:**

- `auto_cut: false` for banners and chained prints — leaves paper continuous.
- `cut` block in the middle of a document for multi-document batches in one POST.
- `tear_here` for human-tear lines (drawn as scissors icon + dashed rule), no hardware cut — useful when the tear is informational ("rip here for Sam"), not separating jobs.

**Paper conservation:**

- `preserve_paper: true` tightens line height, removes default top/bottom margins, compresses spacers. For when you genuinely just want the data and not the typography.
- Default is `false` — typography wins by default. Paper is cheap.

**Dithering:**

- All embedded images run through Atkinson dithering by default unless overridden.
- The renderer auto-scales images to the target width (default 528 px live width; override via `image.width_px`, range 1–528) preserving aspect ratio. Images respect the block's `align` for left/center/right placement within the live area. Full-head 576 px output requires `bleed: true`; bleed images fill the print head and do not use `align`.
- Dithered output on this printer (DPI per §3, pinned in Phase 1) looks great for portraits, terrible for tiny detail. Senders should send images that work at low fidelity (high contrast, clear subjects).

## 9. Sender content sources — out of scope

What gets printed, when, and from which sources is **explicitly out of scope for this spec**. The service is content-agnostic: it accepts valid documents, renders them, prints them. Each sender (OpenClaw cron, MCP server, n8n workflow, ad-hoc agent, iOS Shortcut) defines its own composition logic in its own spec. The only constraint the service places on senders is the document/block schema in §6.

## 10. Stack & dependencies

**Pi service:**
- Python 3.11+
- FastAPI + uvicorn
- pydantic (schema validation, auto-generates `/schema`)
- python-escpos (USB transport)
- Pillow (block rendering, vector-text 2× → Atkinson dither pipeline)
- qrcode + python-barcode (for `qr` and `barcode` blocks)
- systemd unit, runs as non-root `printer` user
- Tailscale (already installed)

**Fonts (bundled with the service, not system-installed):**
- **JetBrains Mono** (TTF, Regular + Bold) — body text, code blocks, and monospace value alignment
- **IBM Plex Sans** (TTF, Medium + Bold) — display
- **Noto Sans SC** (OTF, Regular + Bold) — CJK fallback
- **Spleen** (BDF, 8x16 + 5x8) — ASCII art grid fonts

**Sender side:**
- A shared "block builder" Python module for ergonomic JSON construction is a useful nice-to-have but lives in the sender's codebase, not this service's.
- The MCP server (separate process, wrapping the HTTP API as agent tools) is in scope for this spec — it's the agentic-sender adapter and ships alongside the service.

## 11. Failure modes

| Failure | Behavior |
|---|---|
| Pi offline (WiFi flake) | Sender retries with backoff; gives up after 30min, logs failure |
| Queue full (`max_queue_depth` exceeded) | `503` with `{ "reason": "queue_full" }`; sender backs off and retries |
| Printer USB disconnected | Accepted jobs stay in durable queue and retry every 5min; `/healthz` returns `printer_connected: false` or `null` if unsupported |
| Paper out | Job stays in queue, retried every 5min until `options.expires_at` (status `expired`) or, if unset, until `max_retry_age` (status `retry_timeout`) |
| Cover open mid-print | Same as paper-out when detectable; otherwise collapses to `printer_unavailable` retry behavior |
| Duplicate cron fire | Same scoped key + same payload returns original `202` with `duplicate: true`; same scoped key + different payload returns `409` |
| Idempotency key collision across senders | No collision if senders set `X-Sender`; missing senders share `anonymous`, so callers using idempotency must set sender |
| Sender crashes mid-build | No partial print: full JSON must arrive before render starts |
| Validation error | 400 with structured error per offending block; nothing prints |
| Malformed or oversized `/print/raw` PNG | Malformed PNG returns 400; width/height/byte cap violations return 413; nothing is queued |
| Job exceeds `max_length_mm` | 400 before any paper is consumed |
| Render exceeds memory/time/height guard | Request fails before durable acceptance; response is 413 for configured size guards or 503 if the render worker is unhealthy |
| Service restart after 202 | Durable job log is replayed; pending/retry jobs keep original order |
| Crash or USB failure after bytes were sent | Job is marked `unknown_partial` and is not auto-reprinted, because the service cannot know how much paper was consumed |
| Cache eviction race during reprint | Falls back from cached PNG to JSON re-render; if both artifacts are gone, returns `410 Gone` |
| Pi clock unsynchronized | `/healthz.clock_synchronized` is false; worker does not expire jobs on `expires_at` until time sync returns, avoiding false stale drops |
| Renderer bug for new block type | Caught in CI via `/test` endpoint sample; fallback to "[unsupported block]" placeholder rather than failing the whole job |

## 12. Phased rollout

This spec ships in six phases. Sender integrations (OpenClaw briefing, agentic news, calendar API, iOS Shortcut) live on their own roadmap and depend on this service but ship out of band.

**Phase 1 — Hardware bring-up + DPI calibration (this week)**
- Receive printer, hold-FEED self-test, confirm USB enumeration on Pi
- Bare `python-escpos` "hello world" via USB
- Print a calibration page (known pixel-height ruler) and measure with calipers; pin `DPMM` and `LIVE_WIDTH_MM` constants
- Print a test PNG end-to-end via `/print/raw` only
- Exercise USB status-back for connected, paper-out, and cover-open states; record unsupported signals as `null` in `/healthz`

**Phase 2 — Pi service core (weekend 1)**
- FastAPI app with `/print/raw`, `/healthz`, `/test`, `/jobs`
- Systemd unit, Tailscale binding, time-sync dependency, durable job log, idempotency + queue + retry
- `/jobs` log, `POST /jobs/{id}/reprint` for cached PNG replay, PNG cache infrastructure
- Manual curl test from laptop on tailnet

**Phase 3 — Block schema & renderer (weekend 2)**
- pydantic schema for Document + minimum block set (header, paragraph, checklist, rule, footer, qr, image, kv, section_title, spacer)
- Body/display/code font stack wired in; vector 2× → Atkinson dither helper landed
- 528 px live area + 24 px gutter constants enforced by every block renderer
- `/print` endpoint, `/schema` endpoint with structured 400 contract (`valid_values`, `migration_hint`), `?force=json` reprint for JSON jobs
- Pi Zero 2 W render benchmark for a default-cap 2m document and representative photo; set `max_rendered_height_px`, raw PNG byte cap, and render timeout from measured headroom
- Block sample suite printable via `/test`
- `SCHEMA_CHANGELOG.md` initialized

**Phase 4 — MCP server**
- Reads `/schema` at boot; derives tool surface from current schema
- Wraps HTTP API as agent tools (e.g., `print_document(blocks)`, `print_image(png)`, `get_status()`)
- `SKILL.md` documenting when/why Claude should reach for these tools
- Available to Claude Desktop, Claude Code, and any other agentic surface on the tailnet

**Phase 5 — Creative blocks**
- `large_text`, `pull_quote`, `drop_cap`, `ornament`, `tear_here`, `gradient_band`, `progress_bar`, `sparkline`, `barcode`, `ascii_art`, `bullets`, `numbered`, `table_compact`, `rich_text` (multi-run mixed emphasis)
- Each block lands with a sample in the `/test` page so regressions show up on first physical print

**Phase 6 — Nice-to-haves**
- `?dry_run=true` preview mode (returns rendered PNG without printing, for testing long jobs and previewing typography changes)
- Service config knobs for cache caps, retention thresholds
- Operational metrics endpoint (queue depth time-series, paper-out frequency)

**Out of scope for this spec — sender integrations:**
OpenClaw daily briefing, agentic news summarization, calendar API integration, iOS Shortcut, n8n flows. Each ships on its own timeline against this service's HTTP API. Their composition logic, schedules, and content rules belong in their own specs.

## 13. Agent interfaces (the layered approach)

```
┌──────────────────────────────────────────────────────────┐
│ Layer 3: Agent-native ergonomics (thin wrappers)         │
│   - MCP server  → Claude Desktop, Claude Code, OpenClaw  │
│   - Skill (SKILL.md) → teaches agents when to print      │
│   - Optional CLI (`briefing-print`) for shell composition│
│   - n8n native HTTP node (no custom node, just docs)     │
└──────────────────────┬───────────────────────────────────┘
                       │ all call the same thing
                       ▼
┌──────────────────────────────────────────────────────────┐
│ Layer 2: HTTP API (the contract — source of truth)       │
│   POST /print, /print/raw, /jobs/{id}/reprint            │
│   GET /healthz, /jobs, /schema; POST /test               │
└──────────────────────┬───────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────┐
│ Layer 1: Hardware (Pi + python-escpos + USB + printer)   │
└──────────────────────────────────────────────────────────┘
```

The HTTP API is the immovable contract. Everything else is a thin adapter. This split lets each interface evolve independently and lets us add new sender types without touching the renderer.

**Deterministic path** (cron, scheduled): sender → HTTP directly. No agent reasoning at print time, just at content-generation time. Reliable, observable, idempotent.

**Creative path** (ad-hoc, agentic): Claude in any surface → MCP tool → HTTP. Agent decides *to print* in real time based on conversation. Discoverable, type-safe, low friction.

**MCP server is schema-derived.** On boot, it reads `GET /schema` from the running printer service and constructs its tool surface from current block types and their fields. This means: (1) Claude can never request a removed block type, since it isn't in the tool catalog; (2) new block types added to the renderer become callable from any agentic surface as soon as the MCP server restarts; (3) the MCP server has zero hand-maintained schema knowledge — the printer service is the single source of truth.

## 14. Open questions

The big architectural questions are resolved (see v0.3 decisions and v0.4 changes at the bottom of this doc). What remains is genuinely empirical — answers come from hardware or from real usage:

- **Atkinson dither parameters for vector display fonts at 2× → 1-bit.** Off-the-shelf Atkinson is the starting point; threshold offset and serpentine-vs-non may need tuning per font size. Decide by printing display samples in Phase 3 and picking by eye.
- **Auth model on tailnet.** Currently zero auth — anything on the tailnet can hit `/print`. Acceptable for a single-user device, but if the tailnet ever has guest devices a shared bearer token (`X-Print-Token`) is the obvious minimal addition. Defer until a real reason to reach for it appears.
- **PNG cache + JSON ring-buffer caps.** 100MB / 7 days / 10k jobs are reasonable defaults for a Pi Zero 2 W's SD card; revisit once real usage patterns show whether briefings/photos/banners dominate the disk budget and whether SD-card write volume needs lower caps.
- **Decoded-image pixel cap.** `max_decoded_image_pixels` defaults to 10M pixels; revisit after real photo/banner usage on the target Pi.

## v0.3 decisions (resolved from v0.2 open questions)

| Was open in v0.2 | Resolution in v0.3 |
|---|---|
| Font choice | Current implementation uses IBM Plex Sans Medium prose body (paragraph/lists/drop_cap.rest/kv keys), JetBrains Mono Bold mono body (kv values/table cells/bullet markers), IBM Plex Sans Medium/Bold display, JetBrains Mono Regular/Bold code, Noto Sans SC fallback, and Spleen ASCII-art bitmap fonts (§4 Rendering pipeline, §10 Stack) |
| Codepage fallback vs render-as-image | Always render as image. Pi owns typography end-to-end (§4 Rendering pipeline) |
| Header `inverse_band` style + global body grid | 528 px live area inside 24 px gutters; band is margin-aligned. Edge-to-edge bleed reserved for explicit opt-in (§4 Rendering pipeline) |
| Schema versioning aggressiveness | Single living schema, no version pin header, structured 400 with `valid_values` + `migration_hint`, `SCHEMA_CHANGELOG.md` (§5, §6 Schema evolution) |
| `/jobs` storage: PNG vs JSON | Both, asymmetric retention: JSON long-term, PNG 7-day cache. `?force=json` to re-render at current renderer (§5 `/jobs`) |
| Streaming endpoint | Deferred. `max_length_mm: null` opt-in suffices (§5, §8) |
| Weekend briefing behavior | **Out of scope** — sender concern, not service concern (§9) |

## v0.4 changes

- Concurrency & queue model made explicit: durable FIFO job log with a single worker, no queue-level coalescing, expiry checked at dequeue, `max_queue_depth: 100` default with `503 queue_full` overflow (§5 Concurrency & queue model, §11).
- `image` and `image_dithered` collapsed: single `image` block with optional `dither` field (default `atkinson`); the dedicated dithered block was redundant since all embedded images run through Atkinson by default (§6, §8).
- `text` block renamed to `rich_text` and now requires `runs.length >= 2`. Use `paragraph` for single-emphasis text; `rich_text` is strictly multi-run (§6).
- `align` is now declared per-block-type rather than universally accepted-then-ignored. Honored by `header`, `section_title`, `paragraph`, `rich_text`, `large_text`, `pull_quote`, `footer`, `image`. All other blocks reject `align` at validation (§6).
- `image` block: ambiguous "optional dimensions" replaced with optional `width_px` (1–528, default 528 = live-width) for placement; full-head 576 px output requires `bleed: true` (§6, §8).
- Architecture diagram hostname label updated from `briefing-printer.tailnet` to `print.tailnet` post-rename (§4).
- Self-review pass: phase count corrected to six; §13 endpoint list now includes `/print/raw`; expiry-at-dequeue clarified to repeat on every retry while head-of-queue is stuck; `id` standardized across `POST /print` response and `/jobs` list (§5, §12, §13).
- Independent design-review fixes: `202` now means durable acceptance, hardware-unavailable states moved out of request admission, idempotency scope/TTL behavior specified, raw/render resource guards added, QR/barcode rendering aligned with all-raster determinism, and `?force=json` moved from Phase 6 into the renderer phase where it is required (§5, §6, §11, §12).

## 15. Success criteria

**Service-level (this spec):**
- Mean time from `POST /print` (202 Accepted) to paper cut is under 60 seconds for a typical briefing-length document.
- Zero missed prints attributable to service-side infrastructure (Pi crashed, queue lost a job, validator rejected a valid document) over a 30-day window.
- Adding a new sender takes one HTTP call: no service-side change required for any document expressible in the schema.
- Reprint from PNG cache produces byte-identical output to the original print, every time, within the cache window.

**Adoption-level (signals the substrate is working):**
- At least three independent senders are in regular use within 8 weeks of Phase 4 (MCP server) going live.
- An agent (not the maintainer) decides on its own to print something, correctly, within 3 months of the MCP server going live.
- At least one print job exists *purely for delight* — a banner, a poem, a photo — independent of utility. The substrate has earned its place when the printer surprises its user.
