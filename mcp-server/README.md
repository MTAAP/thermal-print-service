# thermal-printer-mcp

MCP server that wraps the [Thermal Print Service](../service) HTTP API as agent tools.

The block-document tool's input schema is fetched from `GET /schema` at boot — the MCP server has zero hand-maintained schema knowledge. New block types added to the renderer become callable from any agentic surface as soon as the MCP server restarts; removed block types vanish from the tool catalog automatically.

See [`SKILL.md`](./SKILL.md) for when and why an agent should reach for these tools.

## Install via your agent

Paste one of the blocks below into your agent (Claude Code, Codex CLI, OpenClaw, Claude Desktop chat with shell access, etc.). Each block is **idempotent** — re-running just refreshes the install.

> Prereqs: **Python 3.11+** on PATH (the install blocks try `python3.13`, `python3.12`, `python3.11`, then `python3` — at least one of those must be 3.11+; if pip says `Could not find a version that satisfies the requirement mcp>=1.2 ... from versions: none`, your runtime Python is too old) and `git`. Claude Desktop additionally needs `jq` (`brew install jq`). Codex CLI's TOML helper uses Python's stdlib, no extra packages. Adjust `REPO_DIR` if you've already cloned the repo somewhere else.

### One-prompt install (paste this into any agent)

If the agent has shell access and you don't want to pick the right block by hand, paste this prompt verbatim and let it figure out the right path for the client it's running under:

```text
Install the thermal-printer MCP server on this machine. The README with
exact, idempotent install commands for Claude Code, Claude Desktop,
Codex CLI, and OpenClaw is at:

  https://github.com/MTAAP/thermal-print-service/blob/main/mcp-server/README.md

Pick the block matching the agent surface I'm currently using, run it
exactly as written, and confirm with the verification command at the
end of that block. PRINT_SERVICE_URL in the install commands is a
placeholder (`https://printer.your-tailnet.ts.net`) — ASK ME for my
actual tailnet hostname (something like `https://printer.tailXXXXXX.ts.net`
from `tailscale status`) before running the block, and substitute it
into the `-e PRINT_SERVICE_URL=...` / `--env PRINT_SERVICE_URL=...`
argument. If anything fails, surface the error and stop, do not improvise.

For broader context (how the printer service itself is set up on the
Pi, what the block schema looks like, when an agent should reach for
these tools), see:

  https://github.com/MTAAP/thermal-print-service
  https://github.com/MTAAP/thermal-print-service/blob/main/mcp-server/SKILL.md
```

### Claude Code

Uses `claude mcp add` at user scope so the server is available in every project.

```bash
set -euo pipefail

# Pick a Python 3.11+ interpreter. `mcp` requires >=3.10 and our
# pyproject requires >=3.11. On systems where bare `python3` is older
# (e.g. macOS system Python 3.9 or older Linux defaults), pip silently
# filters out every `mcp` version with "from versions: none" instead
# of giving a clear Python-version error — so we resolve the right
# interpreter explicitly here.
PYTHON=""
for cand in python3.13 python3.12 python3.11 python3; do
  if command -v "$cand" >/dev/null 2>&1 \
     && "$cand" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
    PYTHON="$cand"
    break
  fi
done
if [ -z "$PYTHON" ]; then
  echo "ERROR: thermal-printer-mcp needs Python 3.11+ on PATH." >&2
  echo "       tried: python3.13 python3.12 python3.11 python3" >&2
  echo "       fix:   brew install python@3.13           (macOS)" >&2
  echo "              sudo apt install python3.13 python3.13-venv  (Debian/Ubuntu)" >&2
  echo "              or use pyenv: https://github.com/pyenv/pyenv" >&2
  exit 1
fi

REPO_URL="https://github.com/MTAAP/thermal-print-service.git"
REPO_DIR="${REPO_DIR:-$HOME/src/thermal-print-service}"

# Idempotent clone-or-resync. Hard-resets to the remote tip when the
# dir is already a clone of this repo — robust to upstream history
# rewrites (squash merges, fresh-history releases) which would break
# `pull --ff-only`. If the dir exists but is not a clone of this
# repo, it is removed and re-cloned from scratch.
if [ -d "$REPO_DIR/.git" ] \
   && [ "$(git -C "$REPO_DIR" remote get-url origin 2>/dev/null)" = "$REPO_URL" ]; then
  git -C "$REPO_DIR" fetch --quiet origin
  git -C "$REPO_DIR" reset --hard --quiet origin/main
else
  rm -rf "$REPO_DIR"
  git clone --quiet "$REPO_URL" "$REPO_DIR"
fi
cd "$REPO_DIR/mcp-server"
"$PYTHON" -m venv .venv
.venv/bin/pip install --quiet .

# Register with Claude Code (user scope = available in every project).
# Re-add idempotently in case it was already registered.
claude mcp remove --scope user thermal-printer 2>/dev/null || true
claude mcp add --scope user thermal-printer \
  -e PRINT_SERVICE_URL=https://printer.your-tailnet.ts.net \
  -- "$(pwd)/.venv/bin/printer-mcp"

# Verify
claude mcp list | grep thermal-printer
```

The MCP server is live in your next Claude Code session — existing sessions need to be restarted to pick it up.

### Codex CLI

Uses [`codex mcp add`](https://github.com/openai/codex/blob/main/codex-rs/cli/src/mcp_cmd.rs) to write the entry into `~/.codex/config.toml`. Codex re-reads the config on every invocation; running TUI sessions need to be restarted.

```bash
set -euo pipefail

# Pick a Python 3.11+ interpreter. `mcp` requires >=3.10 and our
# pyproject requires >=3.11. On systems where bare `python3` is older
# (e.g. macOS system Python 3.9 or older Linux defaults), pip silently
# filters out every `mcp` version with "from versions: none" instead
# of giving a clear Python-version error — so we resolve the right
# interpreter explicitly here.
PYTHON=""
for cand in python3.13 python3.12 python3.11 python3; do
  if command -v "$cand" >/dev/null 2>&1 \
     && "$cand" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
    PYTHON="$cand"
    break
  fi
done
if [ -z "$PYTHON" ]; then
  echo "ERROR: thermal-printer-mcp needs Python 3.11+ on PATH." >&2
  echo "       tried: python3.13 python3.12 python3.11 python3" >&2
  echo "       fix:   brew install python@3.13           (macOS)" >&2
  echo "              sudo apt install python3.13 python3.13-venv  (Debian/Ubuntu)" >&2
  echo "              or use pyenv: https://github.com/pyenv/pyenv" >&2
  exit 1
fi

REPO_URL="https://github.com/MTAAP/thermal-print-service.git"
REPO_DIR="${REPO_DIR:-$HOME/src/thermal-print-service}"

# Idempotent clone-or-resync. Hard-resets to the remote tip when the
# dir is already a clone of this repo — robust to upstream history
# rewrites (squash merges, fresh-history releases) which would break
# `pull --ff-only`. If the dir exists but is not a clone of this
# repo, it is removed and re-cloned from scratch.
if [ -d "$REPO_DIR/.git" ] \
   && [ "$(git -C "$REPO_DIR" remote get-url origin 2>/dev/null)" = "$REPO_URL" ]; then
  git -C "$REPO_DIR" fetch --quiet origin
  git -C "$REPO_DIR" reset --hard --quiet origin/main
else
  rm -rf "$REPO_DIR"
  git clone --quiet "$REPO_URL" "$REPO_DIR"
fi
cd "$REPO_DIR/mcp-server"
"$PYTHON" -m venv .venv
.venv/bin/pip install --quiet .

# Re-add idempotently.
codex mcp remove thermal-printer 2>/dev/null || true
codex mcp add thermal-printer \
  --env PRINT_SERVICE_URL=https://printer.your-tailnet.ts.net \
  -- "$(pwd)/.venv/bin/printer-mcp"

# Verify
codex mcp get thermal-printer
```

If you're on an older Codex without the `mcp add` subcommand, write the TOML block directly:

```bash
python3 - <<'PY'
import os, tomllib, tomli_w
p = os.path.expanduser("~/.codex/config.toml")
os.makedirs(os.path.dirname(p), exist_ok=True)
doc = tomllib.loads(open(p).read()) if os.path.exists(p) else {}
servers = doc.setdefault("mcp_servers", {})
servers["thermal-printer"] = {
    "command": os.path.expanduser("~/src/thermal-print-service/mcp-server/.venv/bin/printer-mcp"),
    "args": [],
    "env": {"PRINT_SERVICE_URL": "https://printer.your-tailnet.ts.net"},
    "startup_timeout_sec": 30,
}
open(p, "wb").write(tomli_w.dumps(doc).encode())
print("wrote", p)
PY
```

(`tomli_w` is available via `pip install tomli-w` if needed; on Python 3.11+ `tomllib` is stdlib.)

### OpenClaw

OpenClaw stores outbound MCP server definitions under `mcp.servers` in its config and registers them with [`openclaw mcp set`](https://github.com/openclaw/openclaw/blob/main/docs/cli/mcp.md). The saved definition is consumed by OpenClaw runtime adapters (embedded Pi, Gateway-backed agent runs) the next time they spin up — no separate restart step.

```bash
set -euo pipefail

# Pick a Python 3.11+ interpreter. `mcp` requires >=3.10 and our
# pyproject requires >=3.11. On systems where bare `python3` is older
# (e.g. macOS system Python 3.9 or older Linux defaults), pip silently
# filters out every `mcp` version with "from versions: none" instead
# of giving a clear Python-version error — so we resolve the right
# interpreter explicitly here.
PYTHON=""
for cand in python3.13 python3.12 python3.11 python3; do
  if command -v "$cand" >/dev/null 2>&1 \
     && "$cand" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
    PYTHON="$cand"
    break
  fi
done
if [ -z "$PYTHON" ]; then
  echo "ERROR: thermal-printer-mcp needs Python 3.11+ on PATH." >&2
  echo "       tried: python3.13 python3.12 python3.11 python3" >&2
  echo "       fix:   brew install python@3.13           (macOS)" >&2
  echo "              sudo apt install python3.13 python3.13-venv  (Debian/Ubuntu)" >&2
  echo "              or use pyenv: https://github.com/pyenv/pyenv" >&2
  exit 1
fi

REPO_URL="https://github.com/MTAAP/thermal-print-service.git"
REPO_DIR="${REPO_DIR:-$HOME/src/thermal-print-service}"

# Idempotent clone-or-resync. Hard-resets to the remote tip when the
# dir is already a clone of this repo — robust to upstream history
# rewrites (squash merges, fresh-history releases) which would break
# `pull --ff-only`. If the dir exists but is not a clone of this
# repo, it is removed and re-cloned from scratch.
if [ -d "$REPO_DIR/.git" ] \
   && [ "$(git -C "$REPO_DIR" remote get-url origin 2>/dev/null)" = "$REPO_URL" ]; then
  git -C "$REPO_DIR" fetch --quiet origin
  git -C "$REPO_DIR" reset --hard --quiet origin/main
else
  rm -rf "$REPO_DIR"
  git clone --quiet "$REPO_URL" "$REPO_DIR"
fi
cd "$REPO_DIR/mcp-server"
"$PYTHON" -m venv .venv
.venv/bin/pip install --quiet .
MCP_BIN="$(pwd)/.venv/bin/printer-mcp"

# Re-add idempotently — `openclaw mcp set` overwrites by name.
# Build the JSON with python (stdlib only) so the absolute path is quoted
# correctly regardless of any spaces or special chars.
JSON=$(python3 -c '
import json, sys
print(json.dumps({
  "command": sys.argv[1],
  "env": {"PRINT_SERVICE_URL": "https://printer.your-tailnet.ts.net"},
}))' "$MCP_BIN")
openclaw mcp set printer "$JSON"

# Verify
openclaw mcp show printer --json
```

`PRINT_SERVICE_URL` is a plain server var and is **not** affected by OpenClaw's stdio env safety filter (which blocks interpreter-startup vars like `NODE_OPTIONS`, `PYTHONPATH`, `PYTHONSTARTUP`). For deterministic scheduled briefings (e.g., a daily printout at 06:30), use `openclaw cron add` with a webhook posting directly to the print service's `/print` endpoint — that's a separate surface from the MCP registry.

### Claude Desktop

Patches `~/Library/Application Support/Claude/claude_desktop_config.json` in place; safe over an existing config.

```bash
set -euo pipefail

# Pick a Python 3.11+ interpreter. `mcp` requires >=3.10 and our
# pyproject requires >=3.11. On systems where bare `python3` is older
# (e.g. macOS system Python 3.9 or older Linux defaults), pip silently
# filters out every `mcp` version with "from versions: none" instead
# of giving a clear Python-version error — so we resolve the right
# interpreter explicitly here.
PYTHON=""
for cand in python3.13 python3.12 python3.11 python3; do
  if command -v "$cand" >/dev/null 2>&1 \
     && "$cand" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
    PYTHON="$cand"
    break
  fi
done
if [ -z "$PYTHON" ]; then
  echo "ERROR: thermal-printer-mcp needs Python 3.11+ on PATH." >&2
  echo "       tried: python3.13 python3.12 python3.11 python3" >&2
  echo "       fix:   brew install python@3.13           (macOS)" >&2
  echo "              sudo apt install python3.13 python3.13-venv  (Debian/Ubuntu)" >&2
  echo "              or use pyenv: https://github.com/pyenv/pyenv" >&2
  exit 1
fi

REPO_URL="https://github.com/MTAAP/thermal-print-service.git"
REPO_DIR="${REPO_DIR:-$HOME/src/thermal-print-service}"

# Idempotent clone-or-resync. Hard-resets to the remote tip when the
# dir is already a clone of this repo — robust to upstream history
# rewrites (squash merges, fresh-history releases) which would break
# `pull --ff-only`. If the dir exists but is not a clone of this
# repo, it is removed and re-cloned from scratch.
if [ -d "$REPO_DIR/.git" ] \
   && [ "$(git -C "$REPO_DIR" remote get-url origin 2>/dev/null)" = "$REPO_URL" ]; then
  git -C "$REPO_DIR" fetch --quiet origin
  git -C "$REPO_DIR" reset --hard --quiet origin/main
else
  rm -rf "$REPO_DIR"
  git clone --quiet "$REPO_URL" "$REPO_DIR"
fi
cd "$REPO_DIR/mcp-server"
"$PYTHON" -m venv .venv
.venv/bin/pip install --quiet .
MCP_BIN="$(pwd)/.venv/bin/printer-mcp"

CONFIG="$HOME/Library/Application Support/Claude/claude_desktop_config.json"
mkdir -p "$(dirname "$CONFIG")"
[ -s "$CONFIG" ] || echo '{}' > "$CONFIG"
jq --arg cmd "$MCP_BIN" \
  '.mcpServers["thermal-printer"] = {
     command: $cmd,
     env: {PRINT_SERVICE_URL: "https://printer.your-tailnet.ts.net"}
   }' "$CONFIG" > "$CONFIG.tmp" && mv "$CONFIG.tmp" "$CONFIG"

echo "Done. Restart Claude Desktop (Cmd+Q, reopen) to pick up the new server."
```

### Uninstall

```bash
# Claude Code
claude mcp remove --scope user thermal-printer

# Codex CLI
codex mcp remove thermal-printer

# OpenClaw
openclaw mcp unset printer

# Claude Desktop
CONFIG="$HOME/Library/Application Support/Claude/claude_desktop_config.json"
jq 'del(.mcpServers["thermal-printer"])' "$CONFIG" > "$CONFIG.tmp" \
  && mv "$CONFIG.tmp" "$CONFIG"
```

## Manual config (if the agent install doesn't fit)

Each user running an agentic surface installs the server locally and points the client at it.

### Claude Desktop — manual

Edit `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "thermal-printer": {
      "command": "/path/to/thermal-print-service/mcp-server/.venv/bin/printer-mcp",
      "env": {
        "PRINT_SERVICE_URL": "https://printer.your-tailnet.ts.net"
      }
    }
  }
}
```

Restart Claude Desktop.

### Claude Code — manual

Drop the same block into your project's `.mcp.json` or `~/.claude.json` under `mcpServers`.

### Codex CLI — manual

Append to `~/.codex/config.toml`:

```toml
[mcp_servers.thermal-printer]
command = "/path/to/thermal-print-service/mcp-server/.venv/bin/printer-mcp"
args = []
startup_timeout_sec = 30

[mcp_servers.thermal-printer.env]
PRINT_SERVICE_URL = "https://printer.your-tailnet.ts.net"
```

### OpenClaw — manual

Add to OpenClaw config under `mcp.servers`:

```json
{
  "mcp": {
    "servers": {
      "printer": {
        "command": "/path/to/thermal-print-service/mcp-server/.venv/bin/printer-mcp",
        "env": {
          "PRINT_SERVICE_URL": "https://printer.your-tailnet.ts.net"
        }
      }
    }
  }
}
```

## Configuration

| Env var | Default | Purpose |
|---|---|---|
| `PRINT_SERVICE_URL` | `https://printer.your-tailnet.ts.net` | **Placeholder** — replace with your actual tailnet hostname (e.g. `https://printer.tailXXXXXX.ts.net` from `tailscale status`). Tailnet URL works anywhere Tailscale is up; for home-LAN-only setups use `http://printer.local:8000` or your printer host's LAN address. The placeholder default fails DNS resolution loudly so misconfiguration is obvious. |
| `PRINT_SENDER` | `mcp` | Value sent in `X-Sender` so jobs are grouped under this label in the Pi's `/jobs` log. |
| `PRINT_TIMEOUT_S` | `30` | HTTP request timeout. |
| `PRINT_SCHEMA_BOOT_RETRY_S` | `5` | How long to keep retrying `/schema` at boot before falling back to a permissive schema. |

## Tools

| Tool | Wraps | Notes |
|---|---|---|
| `print_document` | `POST /print` | Full block document. Input schema is the live `Document` schema fetched from `/schema` at boot. |
| `print_image` | `POST /print/raw` | Raw PNG escape hatch (576px wide). |
| `get_status` | `GET /healthz` | Connection / paper / cover / queue depth / uptime. |
| `list_recent_jobs` | `GET /jobs` | Recent prints with reprint info. |
| `reprint_job` | `POST /jobs/{id}/reprint` | Cached PNG by default; `force_json` re-renders. |
| `print_test` | `POST /test` | Hello-world test page. |

## Develop

```bash
.venv/bin/pytest
.venv/bin/ruff check .
```

## Running the server directly (for debugging)

The server speaks MCP over stdio. To test it without an MCP client, you can pipe a JSON-RPC handshake into it:

```bash
echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"0"}}}' | .venv/bin/printer-mcp
```

For real interactive testing, point an MCP client (Claude Desktop, Inspector) at it.
