#!/usr/bin/env bash
# Syncs the repo to the Pi and restarts the systemd service.
# Default target: ssh alias `pi-printer-lan`.
set -euo pipefail

REMOTE="${REMOTE:-pi-printer-lan}"
REMOTE_DIR="${REMOTE_DIR:-/home/thermalprinter/thermal-print-service}"
REMOTE_DIR_ESCAPED="$(printf '%q' "${REMOTE_DIR}")"

echo "==> ensure remote directory ${REMOTE}:${REMOTE_DIR}"
ssh "${REMOTE}" "mkdir -p ${REMOTE_DIR_ESCAPED}"

echo "==> rsync to ${REMOTE}:${REMOTE_DIR}"
rsync -az --delete \
  --exclude '.git' --exclude '.venv' --exclude '__pycache__' \
  --exclude 'service/tests/.golden-out' \
  --exclude '.pytest_cache' --exclude '.ruff_cache' --exclude '.mypy_cache' \
  ./ "${REMOTE}:${REMOTE_DIR}/"

echo "==> ensure venv + deps"
ssh "${REMOTE}" "REMOTE_DIR_ESCAPED=${REMOTE_DIR_ESCAPED} bash -se" <<'PI'
  set -euo pipefail
  cd "${REMOTE_DIR_ESCAPED}"
  if [ ! -d .venv ]; then
    python3 -m venv .venv
  fi
  .venv/bin/pip install --upgrade pip wheel
  .venv/bin/pip install -e printer-core
  .venv/bin/pip install -e service
PI

echo "==> restart service (if installed)"
ssh "${REMOTE}" 'sudo systemctl is-enabled printer.service >/dev/null 2>&1 && sudo systemctl restart printer.service || echo "(printer.service not installed yet — skipping restart)"'

echo "==> done."
