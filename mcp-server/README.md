# thermal-printer-mcp

MCP server that wraps the [Thermal Print Service](../service) HTTP API as agent tools.

The block-document tool's input schema is fetched from `GET /schema` at boot — the MCP server has zero hand-maintained schema knowledge. New block types added to the renderer become callable from any agentic surface as soon as the MCP server restarts; removed block types vanish from the tool catalog automatically.

See [`SKILL.md`](./SKILL.md) for when and why an agent should reach for these tools.

## Install via your agent

Paste one of the blocks below into your agent (Claude Code, Codex CLI, OpenClaw, Claude Desktop chat with shell access, etc.). Each block is **idempotent** — re-running just refreshes the install.

> Prereqs: `git` and `curl`. The install blocks try a system Python 3.11+ first (in PATH or in standard Homebrew/Linux locations), and bootstrap one automatically via [uv](https://github.com/astral-sh/uv) from `astral.sh` if none is found — no sudo, no system changes, all under `~/.local/`. Claude Desktop additionally needs `jq` (`brew install jq`). Codex CLI's TOML helper uses Python's stdlib, no extra packages. Adjust `REPO_DIR` if you've already cloned the repo somewhere else.

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
#
# Detection order:
#   1. Explicit override: $PRINTER_PYTHON (escape hatch for unusual setups).
#   2. Names on PATH: python3.13 → 3.12 → 3.11 → python3 (only if 3.11+).
#   3. Well-known absolute paths: Homebrew (Apple Silicon + Intel), Linux
#      package managers, common pyenv shim layouts. This handles agent
#      runtimes (e.g. Claude Desktop, OpenClaw subprocesses) that inherit
#      a sanitized PATH missing /opt/homebrew/bin.
_python_ok() {
  [ -x "$1" ] || command -v "$1" >/dev/null 2>&1 || return 1
  "$1" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null
}
PYTHON=""
if [ -n "${PRINTER_PYTHON:-}" ] && _python_ok "$PRINTER_PYTHON"; then
  PYTHON="$PRINTER_PYTHON"
fi
if [ -z "$PYTHON" ]; then
  for cand in python3.13 python3.12 python3.11 python3; do
    if _python_ok "$cand"; then PYTHON="$cand"; break; fi
  done
fi
if [ -z "$PYTHON" ]; then
  for cand in \
    /opt/homebrew/bin/python3.13 /opt/homebrew/bin/python3.12 /opt/homebrew/bin/python3.11 \
    /usr/local/bin/python3.13   /usr/local/bin/python3.12   /usr/local/bin/python3.11 \
    /usr/bin/python3.13         /usr/bin/python3.12         /usr/bin/python3.11; do
    if _python_ok "$cand"; then PYTHON="$cand"; break; fi
  done
fi
# Final fallback: bootstrap a self-contained Python via uv (Astral's
# Python package/version manager — downloads uv to ~/.local/bin/uv and
# manages Python distributions under ~/.local/share/uv/python/, no
# sudo or system changes). Lets the install succeed on hosts where no
# Python 3.11+ is installed and the user does not want to install one
# globally. Skipped silently if curl is unavailable.
USE_UV=
if [ -z "$PYTHON" ] && command -v curl >/dev/null 2>&1; then
  if ! command -v uv >/dev/null 2>&1 && [ ! -x "$HOME/.local/bin/uv" ]; then
    echo "No Python 3.11+ found locally — bootstrapping uv from astral.sh..." >&2
    curl -LsSf https://astral.sh/uv/install.sh | sh
  fi
  export PATH="$HOME/.local/bin:$PATH"
  if command -v uv >/dev/null 2>&1; then USE_UV=1; fi
fi

if [ -z "$PYTHON" ] && [ -z "${USE_UV:-}" ]; then
  echo "ERROR: thermal-printer-mcp needs Python 3.11+." >&2
  echo "       tried PATH names: python3.13 python3.12 python3.11 python3" >&2
  echo "       tried absolute paths: /opt/homebrew/bin, /usr/local/bin, /usr/bin" >&2
  echo "       tried uv bootstrap: requires curl + network reach to astral.sh" >&2
  echo "       fix:   brew install python@3.13           (macOS)" >&2
  echo "              sudo apt install python3.13 python3.13-venv  (Debian/Ubuntu)" >&2
  echo "              or use pyenv: https://github.com/pyenv/pyenv" >&2
  echo "       override: rerun with PRINTER_PYTHON=/path/to/python3.X prefixed" >&2
  exit 1
fi

REPO_URL="https://github.com/MTAAP/thermal-print-service.git"
REPO_DIR="${REPO_DIR:-$HOME/src/thermal-print-service}"

# Idempotent clone-or-resync, refusing to destroy local work.
#  - If $REPO_DIR is our clone with a clean working tree: fetch + reset
#    to origin/main (robust to upstream history rewrites that would
#    break `pull --ff-only`).
#  - If $REPO_DIR is our clone but has uncommitted changes: STOP. The
#    user is likely hacking on the checkout; never wipe that silently.
#  - If $REPO_DIR exists but isn't our clone: STOP. Never `rm -rf` a
#    directory the script didn't create.
#  - If $REPO_DIR doesn't exist: clone fresh.
# Set REPO_DIR=<another path> if you want a separate install.
if [ -d "$REPO_DIR/.git" ] \
   && [ "$(git -C "$REPO_DIR" remote get-url origin 2>/dev/null)" = "$REPO_URL" ]; then
  if [ -n "$(git -C "$REPO_DIR" status --porcelain 2>/dev/null)" ]; then
    echo "ERROR: $REPO_DIR has uncommitted changes." >&2
    echo "       Stash/commit them, or set REPO_DIR=<another path> and re-run." >&2
    exit 1
  fi
  git -C "$REPO_DIR" fetch --quiet origin
  git -C "$REPO_DIR" reset --hard --quiet origin/main
elif [ -e "$REPO_DIR" ]; then
  echo "ERROR: $REPO_DIR exists but is not a clone of $REPO_URL." >&2
  echo "       Move/remove it manually, or set REPO_DIR=<another path>, then re-run." >&2
  exit 1
else
  git clone --quiet "$REPO_URL" "$REPO_DIR"
fi
cd "$REPO_DIR/mcp-server"
if [ -n "${USE_UV:-}" ]; then
  uv venv --quiet --seed --python 3.13 .venv
else
  "$PYTHON" -m venv .venv
fi
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
#
# Detection order:
#   1. Explicit override: $PRINTER_PYTHON (escape hatch for unusual setups).
#   2. Names on PATH: python3.13 → 3.12 → 3.11 → python3 (only if 3.11+).
#   3. Well-known absolute paths: Homebrew (Apple Silicon + Intel), Linux
#      package managers, common pyenv shim layouts. This handles agent
#      runtimes (e.g. Claude Desktop, OpenClaw subprocesses) that inherit
#      a sanitized PATH missing /opt/homebrew/bin.
_python_ok() {
  [ -x "$1" ] || command -v "$1" >/dev/null 2>&1 || return 1
  "$1" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null
}
PYTHON=""
if [ -n "${PRINTER_PYTHON:-}" ] && _python_ok "$PRINTER_PYTHON"; then
  PYTHON="$PRINTER_PYTHON"
fi
if [ -z "$PYTHON" ]; then
  for cand in python3.13 python3.12 python3.11 python3; do
    if _python_ok "$cand"; then PYTHON="$cand"; break; fi
  done
fi
if [ -z "$PYTHON" ]; then
  for cand in \
    /opt/homebrew/bin/python3.13 /opt/homebrew/bin/python3.12 /opt/homebrew/bin/python3.11 \
    /usr/local/bin/python3.13   /usr/local/bin/python3.12   /usr/local/bin/python3.11 \
    /usr/bin/python3.13         /usr/bin/python3.12         /usr/bin/python3.11; do
    if _python_ok "$cand"; then PYTHON="$cand"; break; fi
  done
fi
# Final fallback: bootstrap a self-contained Python via uv (Astral's
# Python package/version manager — downloads uv to ~/.local/bin/uv and
# manages Python distributions under ~/.local/share/uv/python/, no
# sudo or system changes). Lets the install succeed on hosts where no
# Python 3.11+ is installed and the user does not want to install one
# globally. Skipped silently if curl is unavailable.
USE_UV=
if [ -z "$PYTHON" ] && command -v curl >/dev/null 2>&1; then
  if ! command -v uv >/dev/null 2>&1 && [ ! -x "$HOME/.local/bin/uv" ]; then
    echo "No Python 3.11+ found locally — bootstrapping uv from astral.sh..." >&2
    curl -LsSf https://astral.sh/uv/install.sh | sh
  fi
  export PATH="$HOME/.local/bin:$PATH"
  if command -v uv >/dev/null 2>&1; then USE_UV=1; fi
fi

if [ -z "$PYTHON" ] && [ -z "${USE_UV:-}" ]; then
  echo "ERROR: thermal-printer-mcp needs Python 3.11+." >&2
  echo "       tried PATH names: python3.13 python3.12 python3.11 python3" >&2
  echo "       tried absolute paths: /opt/homebrew/bin, /usr/local/bin, /usr/bin" >&2
  echo "       tried uv bootstrap: requires curl + network reach to astral.sh" >&2
  echo "       fix:   brew install python@3.13           (macOS)" >&2
  echo "              sudo apt install python3.13 python3.13-venv  (Debian/Ubuntu)" >&2
  echo "              or use pyenv: https://github.com/pyenv/pyenv" >&2
  echo "       override: rerun with PRINTER_PYTHON=/path/to/python3.X prefixed" >&2
  exit 1
fi

REPO_URL="https://github.com/MTAAP/thermal-print-service.git"
REPO_DIR="${REPO_DIR:-$HOME/src/thermal-print-service}"

# Idempotent clone-or-resync, refusing to destroy local work.
#  - If $REPO_DIR is our clone with a clean working tree: fetch + reset
#    to origin/main (robust to upstream history rewrites that would
#    break `pull --ff-only`).
#  - If $REPO_DIR is our clone but has uncommitted changes: STOP. The
#    user is likely hacking on the checkout; never wipe that silently.
#  - If $REPO_DIR exists but isn't our clone: STOP. Never `rm -rf` a
#    directory the script didn't create.
#  - If $REPO_DIR doesn't exist: clone fresh.
# Set REPO_DIR=<another path> if you want a separate install.
if [ -d "$REPO_DIR/.git" ] \
   && [ "$(git -C "$REPO_DIR" remote get-url origin 2>/dev/null)" = "$REPO_URL" ]; then
  if [ -n "$(git -C "$REPO_DIR" status --porcelain 2>/dev/null)" ]; then
    echo "ERROR: $REPO_DIR has uncommitted changes." >&2
    echo "       Stash/commit them, or set REPO_DIR=<another path> and re-run." >&2
    exit 1
  fi
  git -C "$REPO_DIR" fetch --quiet origin
  git -C "$REPO_DIR" reset --hard --quiet origin/main
elif [ -e "$REPO_DIR" ]; then
  echo "ERROR: $REPO_DIR exists but is not a clone of $REPO_URL." >&2
  echo "       Move/remove it manually, or set REPO_DIR=<another path>, then re-run." >&2
  exit 1
else
  git clone --quiet "$REPO_URL" "$REPO_DIR"
fi
cd "$REPO_DIR/mcp-server"
if [ -n "${USE_UV:-}" ]; then
  uv venv --quiet --seed --python 3.13 .venv
else
  "$PYTHON" -m venv .venv
fi
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
#
# Detection order:
#   1. Explicit override: $PRINTER_PYTHON (escape hatch for unusual setups).
#   2. Names on PATH: python3.13 → 3.12 → 3.11 → python3 (only if 3.11+).
#   3. Well-known absolute paths: Homebrew (Apple Silicon + Intel), Linux
#      package managers, common pyenv shim layouts. This handles agent
#      runtimes (e.g. Claude Desktop, OpenClaw subprocesses) that inherit
#      a sanitized PATH missing /opt/homebrew/bin.
_python_ok() {
  [ -x "$1" ] || command -v "$1" >/dev/null 2>&1 || return 1
  "$1" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null
}
PYTHON=""
if [ -n "${PRINTER_PYTHON:-}" ] && _python_ok "$PRINTER_PYTHON"; then
  PYTHON="$PRINTER_PYTHON"
fi
if [ -z "$PYTHON" ]; then
  for cand in python3.13 python3.12 python3.11 python3; do
    if _python_ok "$cand"; then PYTHON="$cand"; break; fi
  done
fi
if [ -z "$PYTHON" ]; then
  for cand in \
    /opt/homebrew/bin/python3.13 /opt/homebrew/bin/python3.12 /opt/homebrew/bin/python3.11 \
    /usr/local/bin/python3.13   /usr/local/bin/python3.12   /usr/local/bin/python3.11 \
    /usr/bin/python3.13         /usr/bin/python3.12         /usr/bin/python3.11; do
    if _python_ok "$cand"; then PYTHON="$cand"; break; fi
  done
fi
# Final fallback: bootstrap a self-contained Python via uv (Astral's
# Python package/version manager — downloads uv to ~/.local/bin/uv and
# manages Python distributions under ~/.local/share/uv/python/, no
# sudo or system changes). Lets the install succeed on hosts where no
# Python 3.11+ is installed and the user does not want to install one
# globally. Skipped silently if curl is unavailable.
USE_UV=
if [ -z "$PYTHON" ] && command -v curl >/dev/null 2>&1; then
  if ! command -v uv >/dev/null 2>&1 && [ ! -x "$HOME/.local/bin/uv" ]; then
    echo "No Python 3.11+ found locally — bootstrapping uv from astral.sh..." >&2
    curl -LsSf https://astral.sh/uv/install.sh | sh
  fi
  export PATH="$HOME/.local/bin:$PATH"
  if command -v uv >/dev/null 2>&1; then USE_UV=1; fi
fi

if [ -z "$PYTHON" ] && [ -z "${USE_UV:-}" ]; then
  echo "ERROR: thermal-printer-mcp needs Python 3.11+." >&2
  echo "       tried PATH names: python3.13 python3.12 python3.11 python3" >&2
  echo "       tried absolute paths: /opt/homebrew/bin, /usr/local/bin, /usr/bin" >&2
  echo "       tried uv bootstrap: requires curl + network reach to astral.sh" >&2
  echo "       fix:   brew install python@3.13           (macOS)" >&2
  echo "              sudo apt install python3.13 python3.13-venv  (Debian/Ubuntu)" >&2
  echo "              or use pyenv: https://github.com/pyenv/pyenv" >&2
  echo "       override: rerun with PRINTER_PYTHON=/path/to/python3.X prefixed" >&2
  exit 1
fi

REPO_URL="https://github.com/MTAAP/thermal-print-service.git"
REPO_DIR="${REPO_DIR:-$HOME/src/thermal-print-service}"

# Idempotent clone-or-resync, refusing to destroy local work.
#  - If $REPO_DIR is our clone with a clean working tree: fetch + reset
#    to origin/main (robust to upstream history rewrites that would
#    break `pull --ff-only`).
#  - If $REPO_DIR is our clone but has uncommitted changes: STOP. The
#    user is likely hacking on the checkout; never wipe that silently.
#  - If $REPO_DIR exists but isn't our clone: STOP. Never `rm -rf` a
#    directory the script didn't create.
#  - If $REPO_DIR doesn't exist: clone fresh.
# Set REPO_DIR=<another path> if you want a separate install.
if [ -d "$REPO_DIR/.git" ] \
   && [ "$(git -C "$REPO_DIR" remote get-url origin 2>/dev/null)" = "$REPO_URL" ]; then
  if [ -n "$(git -C "$REPO_DIR" status --porcelain 2>/dev/null)" ]; then
    echo "ERROR: $REPO_DIR has uncommitted changes." >&2
    echo "       Stash/commit them, or set REPO_DIR=<another path> and re-run." >&2
    exit 1
  fi
  git -C "$REPO_DIR" fetch --quiet origin
  git -C "$REPO_DIR" reset --hard --quiet origin/main
elif [ -e "$REPO_DIR" ]; then
  echo "ERROR: $REPO_DIR exists but is not a clone of $REPO_URL." >&2
  echo "       Move/remove it manually, or set REPO_DIR=<another path>, then re-run." >&2
  exit 1
else
  git clone --quiet "$REPO_URL" "$REPO_DIR"
fi
cd "$REPO_DIR/mcp-server"
if [ -n "${USE_UV:-}" ]; then
  uv venv --quiet --seed --python 3.13 .venv
else
  "$PYTHON" -m venv .venv
fi
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
#
# Detection order:
#   1. Explicit override: $PRINTER_PYTHON (escape hatch for unusual setups).
#   2. Names on PATH: python3.13 → 3.12 → 3.11 → python3 (only if 3.11+).
#   3. Well-known absolute paths: Homebrew (Apple Silicon + Intel), Linux
#      package managers, common pyenv shim layouts. This handles agent
#      runtimes (e.g. Claude Desktop, OpenClaw subprocesses) that inherit
#      a sanitized PATH missing /opt/homebrew/bin.
_python_ok() {
  [ -x "$1" ] || command -v "$1" >/dev/null 2>&1 || return 1
  "$1" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null
}
PYTHON=""
if [ -n "${PRINTER_PYTHON:-}" ] && _python_ok "$PRINTER_PYTHON"; then
  PYTHON="$PRINTER_PYTHON"
fi
if [ -z "$PYTHON" ]; then
  for cand in python3.13 python3.12 python3.11 python3; do
    if _python_ok "$cand"; then PYTHON="$cand"; break; fi
  done
fi
if [ -z "$PYTHON" ]; then
  for cand in \
    /opt/homebrew/bin/python3.13 /opt/homebrew/bin/python3.12 /opt/homebrew/bin/python3.11 \
    /usr/local/bin/python3.13   /usr/local/bin/python3.12   /usr/local/bin/python3.11 \
    /usr/bin/python3.13         /usr/bin/python3.12         /usr/bin/python3.11; do
    if _python_ok "$cand"; then PYTHON="$cand"; break; fi
  done
fi
# Final fallback: bootstrap a self-contained Python via uv (Astral's
# Python package/version manager — downloads uv to ~/.local/bin/uv and
# manages Python distributions under ~/.local/share/uv/python/, no
# sudo or system changes). Lets the install succeed on hosts where no
# Python 3.11+ is installed and the user does not want to install one
# globally. Skipped silently if curl is unavailable.
USE_UV=
if [ -z "$PYTHON" ] && command -v curl >/dev/null 2>&1; then
  if ! command -v uv >/dev/null 2>&1 && [ ! -x "$HOME/.local/bin/uv" ]; then
    echo "No Python 3.11+ found locally — bootstrapping uv from astral.sh..." >&2
    curl -LsSf https://astral.sh/uv/install.sh | sh
  fi
  export PATH="$HOME/.local/bin:$PATH"
  if command -v uv >/dev/null 2>&1; then USE_UV=1; fi
fi

if [ -z "$PYTHON" ] && [ -z "${USE_UV:-}" ]; then
  echo "ERROR: thermal-printer-mcp needs Python 3.11+." >&2
  echo "       tried PATH names: python3.13 python3.12 python3.11 python3" >&2
  echo "       tried absolute paths: /opt/homebrew/bin, /usr/local/bin, /usr/bin" >&2
  echo "       tried uv bootstrap: requires curl + network reach to astral.sh" >&2
  echo "       fix:   brew install python@3.13           (macOS)" >&2
  echo "              sudo apt install python3.13 python3.13-venv  (Debian/Ubuntu)" >&2
  echo "              or use pyenv: https://github.com/pyenv/pyenv" >&2
  echo "       override: rerun with PRINTER_PYTHON=/path/to/python3.X prefixed" >&2
  exit 1
fi

REPO_URL="https://github.com/MTAAP/thermal-print-service.git"
REPO_DIR="${REPO_DIR:-$HOME/src/thermal-print-service}"

# Idempotent clone-or-resync, refusing to destroy local work.
#  - If $REPO_DIR is our clone with a clean working tree: fetch + reset
#    to origin/main (robust to upstream history rewrites that would
#    break `pull --ff-only`).
#  - If $REPO_DIR is our clone but has uncommitted changes: STOP. The
#    user is likely hacking on the checkout; never wipe that silently.
#  - If $REPO_DIR exists but isn't our clone: STOP. Never `rm -rf` a
#    directory the script didn't create.
#  - If $REPO_DIR doesn't exist: clone fresh.
# Set REPO_DIR=<another path> if you want a separate install.
if [ -d "$REPO_DIR/.git" ] \
   && [ "$(git -C "$REPO_DIR" remote get-url origin 2>/dev/null)" = "$REPO_URL" ]; then
  if [ -n "$(git -C "$REPO_DIR" status --porcelain 2>/dev/null)" ]; then
    echo "ERROR: $REPO_DIR has uncommitted changes." >&2
    echo "       Stash/commit them, or set REPO_DIR=<another path> and re-run." >&2
    exit 1
  fi
  git -C "$REPO_DIR" fetch --quiet origin
  git -C "$REPO_DIR" reset --hard --quiet origin/main
elif [ -e "$REPO_DIR" ]; then
  echo "ERROR: $REPO_DIR exists but is not a clone of $REPO_URL." >&2
  echo "       Move/remove it manually, or set REPO_DIR=<another path>, then re-run." >&2
  exit 1
else
  git clone --quiet "$REPO_URL" "$REPO_DIR"
fi
cd "$REPO_DIR/mcp-server"
if [ -n "${USE_UV:-}" ]; then
  uv venv --quiet --seed --python 3.13 .venv
else
  "$PYTHON" -m venv .venv
fi
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

### Optional: install the design CLI (`tprint-design`)

The MCP server exposes `get_design_guidelines`, which returns a rulebook telling agents to invoke `tprint-design compile`/`print` for HTML-designed prints. The CLI itself is a separate package (lives in `design/` in this repo) and the per-agent installers above intentionally don't pull it — most prints go through the JSON block schema, and the design pipeline drags in Playwright + a ~200 MB Chromium binary.

Run this **after** one of the per-agent install blocks (which clones the repo into `$REPO_DIR`):

```bash
set -euo pipefail

REPO_DIR="${REPO_DIR:-$HOME/src/thermal-print-service}"
if [ ! -d "$REPO_DIR" ]; then
  echo "ERROR: $REPO_DIR doesn't exist — run a per-agent MCP install block first." >&2
  exit 1
fi

# Reuse PRINTER_PYTHON if set; otherwise the MCP installer already
# verified python3 resolves to 3.11+, so trust that here.
PYTHON="${PRINTER_PYTHON:-python3}"

cd "$REPO_DIR"
"$PYTHON" -m venv design/.venv
design/.venv/bin/pip install --quiet --upgrade pip wheel
design/.venv/bin/pip install --quiet -e ./printer-core
design/.venv/bin/pip install --quiet -e ./design
design/.venv/bin/playwright install chromium

# Expose `tprint-design` on PATH so the SKILL.md examples work verbatim.
# ~/.local/bin is on PATH by default on most Linux + macOS shells; skip
# the symlink if you'd rather call the venv binary directly.
mkdir -p "$HOME/.local/bin"
ln -sf "$REPO_DIR/design/.venv/bin/tprint-design" "$HOME/.local/bin/tprint-design"

# Verify
"$HOME/.local/bin/tprint-design" info >/dev/null && echo "tprint-design ready."
```

If `~/.local/bin` isn't on your `$PATH`, either add it (`export PATH="$HOME/.local/bin:$PATH"` in your shell rc) or call the venv binary directly (`$REPO_DIR/design/.venv/bin/tprint-design`).

`tprint-design print` also defaults-deny non-tailnet `PRINT_SERVICE_URL` hosts. Pass `--allow-public-url` (or set `PRINT_SERVICE_ALLOW_PUBLIC_URL=1`) to send to a public host explicitly.

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

# Optional design CLI
rm -f "$HOME/.local/bin/tprint-design"
# (the repo + venv at $REPO_DIR are shared with the MCP install; remove
# them only if you're done with the MCP server too)
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
