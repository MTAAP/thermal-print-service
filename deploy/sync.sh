#!/usr/bin/env bash
# Syncs the repo to the Pi and restarts the systemd service.
# Default target: ssh alias `pi-printer-lan`.
set -euo pipefail

REMOTE="${REMOTE:-pi-printer-lan}"
REMOTE_DIR="${REMOTE_DIR:-/home/thermalprinter/thermal-print-service}"
REMOTE_DIR_ESCAPED="$(printf '%q' "${REMOTE_DIR}")"

if [ -n "${HUB_URL:-}" ]; then
  LOCAL_SHA="$(git rev-parse HEAD)"
  HUB_HEALTH_URL="${HUB_URL%/}/healthz"
  echo "==> check hub deploy parity (${HUB_HEALTH_URL})"
  HUB_PAYLOAD="$(curl -fsS "${HUB_HEALTH_URL}" 2>/dev/null || true)"
  HUB_SHA="$(
    printf '%s' "${HUB_PAYLOAD}" \
      | python3 -c 'import json, sys; print(json.load(sys.stdin).get("git_sha", ""))' \
        2>/dev/null || true
  )"

  if [ "${HUB_SHA}" != "${LOCAL_SHA}" ]; then
    echo "WARNING: hub deploy skew detected before Pi sync." >&2
    echo "WARNING: local git_sha=${LOCAL_SHA}" >&2
    echo "WARNING: hub git_sha=${HUB_SHA:-missing-or-unreachable}" >&2
    if [ "${SYNC_ANYWAY:-}" != "1" ]; then
      echo "Refusing sync. Deploy the hub first, or set SYNC_ANYWAY=1 to override." >&2
      exit 1
    fi
    echo "WARNING: proceeding because SYNC_ANYWAY=1 is set." >&2
  fi
fi

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

echo "==> restart relay (if enabled)"
ssh "${REMOTE}" 'sudo systemctl is-enabled printer-relay.service >/dev/null 2>&1 && sudo systemctl restart printer-relay.service || echo "(printer-relay.service not enabled — skipping restart)"'

echo "==> done."
