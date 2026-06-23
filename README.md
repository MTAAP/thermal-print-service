# Thermal Print Service

A tailnet-attached thermal receipt printer that any agent or service can print to over HTTP. A general-purpose physical notification surface — anything that can produce structured content can produce paper.

See [`thermal-print-service-spec.md`](thermal-print-service-spec.md) for the full design: architecture, hardware, service contract, document/block schema, phased rollout, and open questions.

## Layout

Five installable Python packages, each with its own `pyproject.toml` and `.venv`:

- [`service/`](./service) — the FastAPI service that runs on the Pi. JSON-in, paper-out HTTP endpoints; owns rendering, queueing, durability.
- [`mcp-server/`](./mcp-server) — MCP adapter wrapping the HTTP API as agent tools for Claude Desktop, Claude Code, Codex CLI, OpenClaw, etc. See [`mcp-server/README.md`](./mcp-server/README.md) for install commands and [`mcp-server/SKILL.md`](./mcp-server/SKILL.md) for when an agent should reach for it.
- [`design/`](./design) — the laptop-side `tprint-design` CLI: compiles HTML+CSS into a thermal-ready 1-bit PNG via Playwright + headless Chromium, then posts to the Pi's `/print/raw` endpoint. The escape hatch when the block schema can't express what you want. See [`design/SKILL.md`](./design/SKILL.md).
- [`printer-core/`](./printer-core) — shared library: Atkinson/Floyd-Steinberg/ordered dither + thermal geometry constants (576 px head, 24 px gutters, 8.0 dots/mm). Pure leaf; used by both `service/` and `design/`.
- [`hub/`](./hub) — public relay hub for the friend network. Runs as `printer-hub`, stores and routes jobs between friends' Pis, and owns the web console templates/static assets.
- [`deploy/`](./deploy) — install + sync scripts for the Pi.

`printer-core` is not on PyPI; both `service/` and `design/` install it as an editable sibling. The deploy scripts handle the install order. For local development, see the per-package `pyproject.toml`s and the `Makefile` (`make verify` runs tests + lint + typecheck across all five).

## Install on the Pi

Hardware: a Raspberry Pi (Zero 2 W or similar) attached over USB to a NetumScan 80mm ESC/POS thermal printer, with Tailscale already on the Pi.

The two scripts in [`deploy/`](./deploy) are idempotent and meant to be re-run safely. Defaults target the maintainer's Pi, but the important paths are configurable with environment variables.

**One-time provisioning** (apt deps, `thermalprinter` user, `lp` group, app directory, venv, `/var/lib/printer/` state dirs, systemd unit). Run **on the Pi**:

```bash
git clone https://github.com/MTAAP/thermal-print-service.git
cd thermal-print-service
./deploy/install.sh
sudo systemctl enable --now printer.service
```

For a different service user or install path (`SERVICE_GROUP` defaults to `SERVICE_USER`):

```bash
SERVICE_USER=printer APP_DIR=/opt/thermal-print-service ./deploy/install.sh
```

**Push code from your laptop** (rsync, refresh venv, restart the service). Run **on your laptop** with `ssh pi-printer-lan` (or override the alias) configured:

```bash
./deploy/sync.sh
# or, against a different host
REMOTE=printer.your-tailnet.ts.net ./deploy/sync.sh
# or, against a different install path
REMOTE=printer.your-tailnet.ts.net REMOTE_DIR=/opt/thermal-print-service ./deploy/sync.sh
```

**Expose over the tailnet via HTTPS** (real LetsEncrypt cert, no self-signed warnings). Run **on the Pi** once:

```bash
./deploy/tailscale-serve.sh
```

After that, `https://<pi-host>.<tailnet>.ts.net/healthz` returns the printer's health snapshot, and the MCP server (see [`mcp-server/`](./mcp-server)) can be installed on any machine that's on the same tailnet.

You can trigger the built-in hardware test page from the Pi or from any host that can reach the service:

```bash
printer-svc test-print --url https://<pi-host>.<tailnet>.ts.net
```

## Install the MCP server on your machine

See [`mcp-server/README.md`](./mcp-server/README.md) for copy-paste install commands per agent surface (Claude Code, Codex CLI, OpenClaw, Claude Desktop). It also includes a one-prompt block you can paste into any shell-running agent to have it self-install.

## Design HTML+CSS prints on your laptop

For pieces the JSON block schema can't express, [`design/`](./design) ships a `tprint-design` CLI that compiles HTML+CSS into a thermal-ready 1-bit PNG via Playwright. See [`design/SKILL.md`](./design/SKILL.md) for the agent-facing workflow.

```bash
python3 -m venv design/.venv
design/.venv/bin/pip install -e ./printer-core
design/.venv/bin/pip install -e 'design[dev]'
design/.venv/bin/playwright install chromium

design/.venv/bin/tprint-design init my.html
design/.venv/bin/tprint-design compile my.html   # → my.png + my.lint.json
PRINT_SERVICE_URL=https://<pi-host>.<tailnet>.ts.net \
  design/.venv/bin/tprint-design print my.html
```

The CLI default-denies non-tailnet `PRINT_SERVICE_URL` hosts (pass `--allow-public-url` or set `PRINT_SERVICE_ALLOW_PUBLIC_URL=1` to override).

## Local development

Five sibling Python packages, each with its own venv. First-time setup:

```bash
python3 -m venv printer-core/.venv && printer-core/.venv/bin/pip install -e 'printer-core[dev]'
python3 -m venv service/.venv && service/.venv/bin/pip install -e ./printer-core && service/.venv/bin/pip install -e 'service[dev]'
python3 -m venv mcp-server/.venv && mcp-server/.venv/bin/pip install -e 'mcp-server[dev]'
python3 -m venv hub/.venv && hub/.venv/bin/pip install -e 'hub[dev]'
python3 -m venv design/.venv && design/.venv/bin/pip install -e ./printer-core && design/.venv/bin/pip install -e 'design[dev]' && design/.venv/bin/playwright install chromium
```

Order matters: install `printer-core` editable into a venv before installing any package that depends on it (`service`, `design`). The deploy scripts handle this for the Pi-side venv automatically.

```bash
make verify    # tests + lint + typecheck across all five packages
make test      # tests only
make lint      # ruff
make typecheck # mypy
```

CI runs the same package gates across Python 3.11 and 3.13, plus a non-editable hub runtime install smoke using `hub/constraints.txt` to mirror the Railway image path.
