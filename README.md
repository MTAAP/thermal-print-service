# Thermal Print Service

A tailnet-attached thermal receipt printer that any agent or service can print to over HTTP. A general-purpose physical notification surface — anything that can produce structured content can produce paper.

See [`thermal-print-service-spec.md`](thermal-print-service-spec.md) for the full design: architecture, hardware, service contract, document/block schema, phased rollout, and open questions.

## Layout

- [`service/`](./service) — the FastAPI service that runs on the Pi (Phases 0-3, 5, 6).
- [`mcp-server/`](./mcp-server) — MCP server that wraps the HTTP API as agent tools for Claude Desktop, Claude Code, Codex CLI, OpenClaw, etc. (Phase 4). See [`mcp-server/README.md`](./mcp-server/README.md) for install commands and [`mcp-server/SKILL.md`](./mcp-server/SKILL.md) for when an agent should reach for it.
- [`deploy/`](./deploy) — install + sync scripts for the Pi.

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
