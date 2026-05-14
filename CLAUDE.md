# CLAUDE.md — Thermal Print Service

Tailnet-attached thermal receipt printer. JSON-in, paper-out HTTP service running on a Pi Zero 2 W tethered over USB to a NetumScan 80mm ESC/POS printer, plus an MCP adapter for agent surfaces.

## Authoritative docs (read before changing behavior)

- [`thermal-print-service-spec.md`](thermal-print-service-spec.md) — living implementation spec (architecture, service contract, block schema, phased rollout). The schema and renderer code must match this file; if they diverge, the spec wins or the spec gets updated.
- [`SCHEMA_CHANGELOG.md`](SCHEMA_CHANGELOG.md) — every schema removal/rename/notable change, keyed to the renderer version. Adding or modifying a block type goes here.
- [`README.md`](README.md) — Pi install + laptop sync flow.
- [`mcp-server/SKILL.md`](mcp-server/SKILL.md) — when an agent should reach for the MCP server.

## Layout

| Path | What |
|---|---|
| `service/` | FastAPI service that runs on the Pi. Owns rendering, queueing, durability. `printer-svc` CLI entry point. |
| `mcp-server/` | MCP adapter wrapping the HTTP API as agent tools (Claude Code, Claude Desktop, Codex CLI, OpenClaw). |
| `design/` | Local CLI (`tprint-design`) compiling HTML+CSS into thermal-ready 1-bit PNGs. Runs on the user's laptop via Playwright + headless Chromium. Sends final PNG to the Pi via `/print/raw`. See [`design/SKILL.md`](design/SKILL.md). |
| `printer-core/` | Shared library: Atkinson dither + thermal constants used by both `service/` and `design/`. |
| `deploy/` | Idempotent Pi provisioning (`install.sh`), laptop → Pi sync (`sync.sh`), Tailscale HTTPS (`tailscale-serve.sh`), systemd unit. |
| `assets/fonts/` | Bundled font stack: IBM Plex Sans, JetBrains Mono, Noto Sans SC, Spleen. Loaded by `FontRegistry` via `assets/fonts/` (paths resolved from repo root in tests via `REPO_ROOT`). |
| `assets/test-pages/test-page.json` | Document used by `POST /test` and the literary-frame regression. |

`service/printer/` packages:
`schema/` (pydantic models) → `render/` (PIL pipeline, `blocks/`, `typography`, `dither`) → `queue/` (durable joblog, idempotency, PNG cache, worker) → `transport/` (python-escpos over `/dev/usb/lp0`). `app.py` wires them into FastAPI; `cli/main.py` exposes `run`, `calibrate`, `test-print`.

## Four venvs — important

The repo has **four separate Python packages**, each with its own `pyproject.toml` and `.venv`:

- `printer-core/.venv/` — installs `printer-core/` (shared dither + constants)
- `service/.venv/` — installs `service/` (depends on `printer-core` editable)
- `mcp-server/.venv/` — installs `mcp-server/`
- `design/.venv/` — installs `design/` (depends on `printer-core` editable; pulls Playwright + Chromium)

The top-level `Makefile` targets all four. Don't install one package's deps into the other's venv.

```bash
# First-time setup
python3 -m venv printer-core/.venv && printer-core/.venv/bin/pip install -e 'printer-core[dev]'
python3 -m venv service/.venv && service/.venv/bin/pip install -e ./printer-core && service/.venv/bin/pip install -e 'service[dev]'
python3 -m venv mcp-server/.venv && mcp-server/.venv/bin/pip install -e 'mcp-server[dev]'
python3 -m venv design/.venv && design/.venv/bin/pip install -e ./printer-core && design/.venv/bin/pip install -e 'design[dev]' && design/.venv/bin/playwright install chromium
```

## Commands

```bash
# Everything (test + lint + typecheck across both packages)
make verify

# Individual stages
make test            # service-test + mcp-test
make lint            # ruff over both
make typecheck       # mypy over both

# Per-package
make service-test    # service/.venv/bin/python -m pytest service/tests
make mcp-test        # mcp-server/.venv/bin/python -m pytest mcp-server/tests
```

`make verify` is the gate. CI (`.github/workflows/ci.yml`) runs the same commands across Python 3.11 and 3.13.

### Running the service locally

```bash
service/.venv/bin/printer-svc run          # FastAPI on PRINTER_HOST:PRINTER_PORT (default 127.0.0.1:8000)
service/.venv/bin/printer-svc test-print   # POST /test against PRINTER_SERVICE_URL
service/.venv/bin/printer-svc calibrate    # print or dump the DPI calibration ruler
```

Local runs need `PRINTER_DEVICE` set (or a `/dev/usb/lp0`-compatible target); without hardware, use the test suite or `--dump file.png` on `calibrate`.

### Deploying to the Pi

```bash
./deploy/sync.sh                                    # rsync + venv refresh + systemctl restart
REMOTE=printer.your-tailnet.ts.net ./deploy/sync.sh # override SSH alias
```

`sync.sh` defaults to the `pi-printer-lan` SSH alias. The Pi runs the service as the `thermalprinter` user under `systemd` (unit at `deploy/printer.service`); state lives in `/var/lib/printer/{jobs,cache,idempotency}`.

## Architecture invariants

These are spec-load-bearing — touching them requires a spec update:

- **Print head: 576 px wide**, with **24 px gutters**, leaving **528 px live area**. Defined in `service/printer/constants.py`.
- **DPMM = 8.0**, pinned from caliper measurement (2026-05-09). mm ↔ px conversions only happen at three named points: `max_length_mm` enforcement, `estimated_paper_mm` in `/print` responses, `paper_used_mm` in `/jobs`. Don't sprinkle mm math elsewhere.
- **The renderer is the single source of typographic truth.** Every text block, every glyph is composed in PIL and sent as raster image data — the printer's native text mode is intentionally unused. Vector text is rendered at 2× then Atkinson-dithered to 1-bit.
- **Durability before 202.** `POST /print` returns 202 only after validation + render + durable write to the JSONL joblog. The in-process queue is a wakeup signal; on restart the worker replays the log.
- **Single FIFO worker.** No queue coalescing — N POSTs = N print jobs. Multi-section single prints belong inside one document via `cut` blocks (see spec §8).

## Working on the schema

Adding or changing a block type is a coordinated change across these files:

1. `service/printer/schema/blocks.py` — pydantic model + `ALIGN_ALLOWED` membership.
2. `service/printer/render/blocks/{text,lists,visual,flow,embedded,literary}.py` — renderer.
3. `service/printer/render/renderer.py` — dispatch wiring if needed.
4. `assets/test-pages/test-page.json` — exercise the new block in `POST /test`.
5. `service/tests/test_schema_blocks_*.py` and `service/tests/test_render_blocks_*.py` — schema + render tests.
6. `service/tests/test_schema_descriptions.py` — per-field descriptions surfaced via `GET /schema`.
7. `service/printer/__about__.py` — bump `__version__` (renderer version).
8. `SCHEMA_CHANGELOG.md` — entry for the new version. Include a `migration_hint` if anything was renamed or removed, so the 400 error path can surface it.

The block schema is **a single living contract** — there is no schema version field. Senders pinned at build-time stay in lockstep via the 400 error contract (`valid_values`, `migration_hint`).

## Gotchas

- **mypy from repo root vs. service/.** CI runs `mypy printer` from `working-directory: service`. The Makefile uses `--config-file service/pyproject.toml`. If you run mypy by hand, pick one — `mypy printer` from repo root fails because the package layout assumes `service/` as the CWD.
- **Render-test goldens.** PNG goldens land in `service/tests/.golden-out/` (gitignored). If a render test fails, inspect the diff there; don't blindly regenerate goldens for typography changes — they're how we catch regressions.
- **Fonts via REPO_ROOT.** `service/tests/conftest.py` resolves fonts as `REPO_ROOT / "assets" / "fonts"`. If you move that directory or add a new font, update both `FontRegistry` and the test fixture.
- **`/var/lib/printer` permissions.** `install.sh` creates it `0750 thermalprinter:thermalprinter`. The service can't write the joblog if those perms drift; check there first if a fresh Pi refuses `POST /print`.
- **`auto_cut` is per-job, not per-document.** Multi-section prints use `cut` blocks (spec §8), not separate POSTs.
- **`expires_at` vs. `max_retry_age_s`.** Sender deadline → `status: "expired"`. Service self-protection ceiling (default 24h) → `status: "retry_timeout"`. Don't conflate them.
- **Clock-sync gates expiry.** Expiry checks are suspended while the Pi clock is unsynchronized (spec §11) — a job whose `expires_at` already passed won't be dropped until the clock re-syncs.
- **Two `pyproject.toml`s, two `mypy` configs.** Linter/typecheck settings live per-package. Don't add config to a phantom root `pyproject.toml`.

## Public repo hygiene

This repo is **public** (`github.com/MTAAP/thermal-print-service`). Before committing, scan diffs for:

- **Real tailnet hostnames.** The repo convention is `printer.your-tailnet.ts.net` as a placeholder. Never commit a real `*.tailXXXXXX.ts.net` host or a real device's tailnet IP. The MCP config default deliberately fails DNS so misconfiguration is loud — keep it that way.
- **Personal SSH aliases beyond `pi-printer-lan`.** `pi-printer-lan` is the documented default in `deploy/sync.sh` and `README.md`. Don't add your own aliases (`my-pi`, hostnames with usernames, LAN IPs) to scripts or docs.
- **Absolute paths with usernames.** No `/Users/<name>/...` or `/home/<name>/...` (other than the documented `/home/thermalprinter/...` service paths). Use repo-relative paths in plans, specs, and commit messages.
- **Real env values.** `deploy/printer.service` ships with safe defaults and commented-out tuning knobs. Site-specific values (`PRINTER_DEVICE=/dev/usb/lp1`, custom caps) belong on the Pi via `systemctl edit printer.service` or environment files outside the repo, not in the committed unit.
- **API keys, tokens, tailscale auth keys, WiFi credentials.** None of these belong anywhere in the repo. There are no secrets in the service today — keep it that way; if a future sender needs auth, put it in a runtime config file under `/var/lib/printer/` or systemd `EnvironmentFile=`, not committed.
- **Real job content in tests/goldens.** `assets/test-pages/test-page.json` and render fixtures should stay synthetic — no real briefings, no real names, no real calendar data.
- **Personal Claude/agent overrides.** `.claude.local.md` is gitignored for per-contributor preferences; put anything machine-specific there instead of in `CLAUDE.md`.

Quick pre-commit sweep:

```bash
git diff --cached | grep -E 'tail[a-z0-9-]{6,}\.ts\.net|/Users/|/home/(?!thermalprinter)|192\.168\.|10\.[0-9]+\.|@gmail|tskey-'
```

If that prints anything, stop and review before committing.

## Conventions

- **No emojis in debug/log messages or comments.** (Inherited from global `~/.claude/CLAUDE.md` — flagged here because the renderer touches glyph rendering and it's tempting to log Unicode.)
- **Ruff:** `line-length = 100`, `target-version = "py311"`, lints `E, F, W, I, B, UP, SIM`.
- **Python ≥ 3.11.** CI matrix: 3.11 + 3.13.
- **No legacy fallbacks.** When refactoring, replace the old implementation — don't leave dual code paths behind.
- **Comments earn their keep.** The codebase already has commentary where invariants are non-obvious (worker replay, DPMM pinning, mypy quirks). Match that bar: explain *why*, not *what*.
