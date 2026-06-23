---
name: thermal-printer
description: Use when the conversation calls for printing something on the user's tailnet thermal receipt printer — a daily briefing, a quick note, a poem, a photo, a banner. Anything that becomes more useful or more delightful as physical paper.
---

# Thermal Printer

The user has an 80mm thermal receipt printer attached to a Raspberry Pi on his tailnet. This skill exposes it as a set of MCP tools so any agent can produce paper.

## When to reach for this

Print when the output is **better as paper than as a chat message**:

- The user asks you to print, fax, post, or stick something on the wall.
- The output is meant to outlast the conversation — a checklist they'll carry, a recipe they'll cook from, a quote for the desk, a photo for the fridge.
- The shape suits the medium — narrow, top-down, scannable. Daily briefings, quick notes ("Sam called"), receipts for non-receipt things, banners, dithered photos, ASCII art, tear-and-share notes.

Don't print as a default. Most chat answers are not improved by paper.

## Sizes at a glance

The defaults are the right pick 80 % of the time. Reach for the extremes only when the print is **the** thing on the page.

| Field | sm | md (default) | lg | xl | xxl | xxxl |
|---|---|---|---|---|---|---|
| `rich_text.size` | 14 px / ~1.75 mm | 18 px / ~2.25 mm | 28 px / ~3.5 mm | — | — | — |
| `large_text.size` | — | — | — | 48 px / 6 mm sub-banner | 80 px / 10 mm banner | 128 px / 16 mm huge banner |
| `qr.size` | 192 px / 24 mm inline | 320 px / 40 mm | 480 px / 60 mm prominent | — | — | — |
| `code.size` | 14 px compact | 16 px thermal-safe | 18 px emphasized | — | — | — |

`spacer.lines` is in body line-heights (1 line ≈ 3.25 mm). `feed.lines` is in paper-feed lines (~1.75 mm each) — use `feed` for pre-cut paper-feed control, `spacer` for in-document whitespace.

## Style guide — picking treatments

- **`header.style`**: `inverse_band` (default) is loud — use for date headers, "Sam called", "RECEIPT". `ornamental` flanks the title with ◆ glyphs — formal, literary. `minimal` puts the title above a hairline rule — understated, modern. `header.subtitle` adds a secondary line below the title in display medium.
- **`section_title.style`**: `underline` (default) is neutral. `inverse` paints a section-weight white-on-black band — call out a critical section. `rule_above` gives a "chapter break" feel — good for long-form readers.
- **`rule.style`**: `solid` (2 px, default) is the all-rounder. `dashed` reads as a perforation hint. `dotted` is the quietest. `double` is for "important" breaks. `wave` is decorative.
- **`ornament.pattern`**: `stars` (★), `diamonds` (◆), `leaves` (❀), `geometric` (■□), `waves` (～), `art_deco` (◆◇), `minimal_dots` (· · ·). Use sparingly — one ornament per print, not three. Seasoning, not the dish.
- **`paragraph.emphasis`**: whole-paragraph italic/bold. For mixed emphasis inside one block, reach for `rich_text`.
- **`pull_quote`**: use `attribution` for sourced quotes; leave it off for prose lifts.
- **Captions**: `qr.caption` and `image.caption` render centered below the visual. Use for short labels ("scan for menu", "1998, Lisbon"), not paragraphs.
- **Bullets vs numbered vs checklist**: `bullets` for unordered prose, `numbered` for sequenced steps, `checklist` for things meant to be ticked off on paper.

## What to print

The printer is a **general-purpose physical notification surface**. The medium is 80mm wide thermal paper, one column, top-down. The substrate is content-agnostic — you decide what goes on it.

Some shapes the surface accommodates well (not an exhaustive list — invent freely):

- **Daily briefing** — header, a few sections (`section_title` + `paragraph`/`checklist`), a QR for the full agenda, footer.
- **Quick note** — single short message, ~5cm of paper. "Package arrived." "Don't forget the passport."
- **Long-form reader** — drop caps, pull quotes, generous spacing. Meant to be read then rolled up like a scroll.
- **Banner / poster** — `large_text` at `xxxl`, ornaments. Disable `auto_cut` for chained banners.
- **Tear-and-share** — multi-section with `tear_here` markers between strips.
- **Photo** — single dithered image with optional caption. Atkinson dithering looks great for high-contrast subjects.
- **Receipt poetry / typography piece** — `large_text` + `ornament` + `pull_quote` + `spacer`. A daily haiku, a quote of the day.

## Tools

`print_document(document, idempotency_key?)` — primary tool. Compose a JSON document made of blocks; the Pi renders typesetting and prints. The `document` parameter's full schema is supplied at runtime (the MCP server fetches it from the printer service at boot), so the available block types and their fields are always current. For documents submitted this way, the Pi-side renderer is the single source of typographic truth — every glyph is composed in PIL, so output looks identical regardless of sender. (The HTML pipeline below uses a different render path with its own typography; reach for it only when the block schema's bounded surface is the limit.)

`print_image(png_base64, idempotency_key?)` — escape hatch for pixel-controlled output (custom dithers, generative art, ASCII pieces the block schema can't express). PNG must be exactly 576px wide.

`get_status()` — printer health: connected, paper present, cover closed, queue depth, clock sync, uptime. Use before printing if you want to confirm readiness, or to diagnose a stuck job.

`list_recent_jobs(limit?)` — recent prints with id, status, sender, document_type. Useful for "what just printed?" or finding a job to reprint.

`reprint_job(id, force_json?)` — replay a previous print. Default uses the cached PNG byte-for-byte (the cat-knocked-the-paper case). `force_json=true` re-renders from JSON at the current renderer version (useful when typography has improved).

`print_test()` — bundled hello-world page exercising every block type. Good for hardware verification after a move.

`get_design_guidelines()` — return the thermal-design rulebook (live print width, DPMM, fonts, lint summary, full `tprint-design` CLI workflow). Call this once at the start of an HTML-design session. The CLI itself is a separate install (not bundled with the MCP server because it pulls Playwright + a ~200 MB Chromium binary); if `tprint-design` isn't on PATH, see the **Optional: install the design CLI** section in `mcp-server/README.md` for the one-block setup.

## Sending to friends (Printer Pals)

The printer can also push to **someone else's** printer over the Printer Pals hub.

**Quick text — just say it.** `message_friend(to, text, title?, idempotency_key?)` sends a plain note: `to` is a list of handles, `text` is the body, `title` is an optional bold heading. It builds the document for you from **common-core blocks** (`header` + `paragraph`) that every renderer version accepts, so you do **not** need `get_friend_schema` first. This is the right tool for "tell alice X", "send bob a reminder", and most agent-to-friend messages.

**Rich documents — compose, then send.** For lists, QR codes, images, or any structured layout, use `send_to_friend`, and the **call order matters**:

1. `list_friends()` — who you can send to. Returns one entry per friend: `handle`, display name, `renderer_version` (a schema fingerprint — friends on the same version share a block schema), and whether they're `online`.
2. `get_friend_schema(handle)` — the recipient's block catalog (`renderer_version`, `blocks_schema`, `block_types`) **before** you compose. Different printers run different renderer versions, so a block your printer accepts may not exist on theirs. Pull the schema first to compose a document that recipient will accept. If a friend exists but their Pi hasn't reported capabilities yet, this returns nulls/empties — fall back to the common-core blocks (`header`, `paragraph`, `rule`, `footer`) or wait for their printer to come online.
3. `send_to_friend(to, document, idempotency_key?)` — `to` is a list of handles; `document` is a normal block document (same shape as `print_document`). Raw-PNG sends are the web composer's job, not this tool.

Both `message_friend` and `send_to_friend` return a **per-recipient results array** — one entry per handle in `to`, so a multi-recipient send can partially succeed. For any entry with status `incompatible`, read `result.detail`: it names the offending field plus `valid_values`. Fix that field for that recipient and retry. Calling `get_friend_schema(handle)` first is how you avoid `incompatible` in the first place (it can't happen with `message_friend` — common-core blocks are universal). Don't blindly re-send the same document — read the detail and self-heal, same discipline as the `print_document` error contract above.

Two env vars configure the hub: `HUB_URL` (the hub's base URL) and `HUB_API_TOKEN` (your per-person API token). The friend tools always list even when unconfigured, but a call fails loudly at call time if `HUB_API_TOKEN` is unset (you'll get a crisp "HUB_API_TOKEN not set" rather than an unauthenticated request). The default `HUB_URL` is `https://printer-pals-hub.invalid` — a deliberate loud-fail placeholder (an unresolvable `.invalid` name), mirroring the `PRINT_SERVICE_URL` convention. **Public-repo hygiene:** never paste a real hub URL or token into docs, commits, or chat; set them in your MCP `env` block only.

## When to reach for HTML design vs JSON blocks

- **JSON blocks** (`print_document`): default. The block schema covers
  ~90% of cases — daily briefings, notes, lists, banners, photos.
  Validated, predictable, fast.

- **HTML design** (`tprint-design` CLI on the user's machine): for
  intricate one-off pieces where the block schema feels limiting —
  custom decorative borders, multi-section layouts inside a single
  segment, hand-tuned typography experiments, generative compositions.

  Workflow:
  1. Call `get_design_guidelines` to load the rulebook.
  2. Use `Write` to create `<name>.html`. Start from a template
     (`tprint-design init <name>.html --template <kind>`).
  3. `tprint-design compile <name>.html` (via Bash).
  4. `Read <name>.png` — look at the dithered output.
  5. Iterate: edit HTML → recompile → re-read.
  6. `tprint-design print <name>.html` when satisfied (or `--dry-run`
     to validate at the Pi without paper).

  Honor lint errors. Warnings are advisory but usually right. The CLI
  blocks `print` if any lint errors are present.

## Composition principles

- **One column, narrow, top-down.** The schema is intentionally flat — no nested layouts, no columns, no inline images-within-paragraphs. If a layout needs columns or tables, it doesn't belong on 80mm paper.
- **Senders own content; the Pi owns presentation.** You decide *what* to print. The renderer decides *how* — typography, spacing, dithering. Don't over-specify; pick the right blocks and trust the renderer.
- **Visual rhythm matters.** Open with a `header`, end with a `footer`, separate sections with `rule` or `section_title`. Use `spacer` to breathe. The output should look like someone cared.
- **Length is a choice, not a default.** The default cap is 2 meters of paper. For long-form scrolls, set `options.max_length_mm: null` deliberately. For banners and chained outputs, set `options.auto_cut: false`.

## Literary blocks — the frame

For documents that are letters, journals, scrolls, or news-style snippets, the literary-frame blocks carry the typographic voice of each role. Pick them deliberately:

- **`epigraph`** — short quoted opener under a header. Italic, indented both sides, optional attribution. Quieter than `pull_quote` (which is loud and pulled-from-the-middle).
- **`byline`** — author credit between the title and the body. Italic 14 px, left-aligned.
- **`dateline`** — journalistic place-and-date opener ("ANYTOWN, MAY 12 ——"). Auto-uppercased. Sits at the top of a dispatch.
- **`salutation`** — letter opener ("Dear Sam,"). Body size, extra breathing room below.
- **`signature`** — right-aligned italic sign-off with optional `closing` ("Yours,") above the `name`.
- **`colophon`** — end-matter production note. Centered italic 14 in a narrow column.
- **`address`** — letterhead lines, tight spacing, left-aligned.

None of these accept `align`; the placement is baked in. For loose freeform sign-offs, use `paragraph` with `emphasis: italic` instead.

## Error contract

`print_document` returns `{ok: false, status: 400, details: {errors: [...]}}` for schema violations. Each error includes:

- `block_index` — which block was wrong
- `field` — which field
- `message` — plain-English description
- `valid_values` — for enums
- `migration_hint` — if a field renamed between renderer versions

Read that body and self-heal. Don't retry the same broken document expecting different results.

`503 queue_full` means back off and try again in a minute.
`409` means the same idempotency key was reused with a different payload.
`410 Gone` from `reprint_job` means the cache aged out.

## Idempotency

If the user might re-ask for the same print (cron-style triggers, "did that go through?"), set `idempotency_key` to a stable value scoped to the intent (e.g., `daily-briefing-2026-05-09`). Same key + same payload returns the original 202 with `duplicate: true`. Same key + different payload is a 409.

## Examples

A morning briefing:

```json
{
  "document": {
    "document_type": "briefing",
    "blocks": [
      {"type": "header", "text": "Friday, May 9", "style": "inverse_band"},
      {"type": "paragraph", "text": "06:30 · Anytown · 14°C", "align": "center"},
      {"type": "rule", "style": "dashed"},
      {"type": "section_title", "text": "TODAY"},
      {"type": "checklist", "items": ["Draft Q3 report", "Reply to support ticket"]},
      {"type": "footer", "text": "have a good one"}
    ]
  },
  "idempotency_key": "briefing-2026-05-09"
}
```

A quick note:

```json
{
  "document": {
    "document_type": "quick_note",
    "blocks": [
      {"type": "header", "text": "Sam called", "style": "minimal"},
      {"type": "paragraph", "text": "Wants to know about dinner. 19:00 ok?"}
    ]
  }
}
```

A banner:

```json
{
  "document": {
    "document_type": "banner",
    "options": {"auto_cut": false},
    "blocks": [
      {"type": "spacer", "lines": 3},
      {"type": "large_text", "text": "WELCOME HOME", "size": "xxxl", "align": "center"},
      {"type": "ornament", "pattern": "stars"},
      {"type": "spacer", "lines": 3}
    ]
  }
}
```

A literary scroll:

```json
{
  "document": {
    "document_type": "scroll",
    "blocks": [
      {"type": "header", "text": "Field Notes", "subtitle": "vol. III · spring"},
      {"type": "byline", "text": "by tim kraus"},
      {"type": "epigraph", "text": "It is the constraint of paper, not the screen, that makes the words slow down.", "attribution": "field notebook"},
      {"type": "drop_cap", "first_letter": "The", "rest": "morning fog refused to lift, even past nine. We took the lower path and watched the gulls patrol the breakwater for nearly an hour."},
      {"type": "signature", "name": "T.", "closing": "yours from the coast,"},
      {"type": "colophon", "text": "Printed on 80 mm thermal, Anytown, spring 2026."}
    ]
  }
}
```
