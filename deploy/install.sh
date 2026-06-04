#!/usr/bin/env bash
# Idempotent Pi provisioning. Safe to re-run.
set -euo pipefail

if command -v sudo >/dev/null 2>&1; then
  SUDO=sudo
else
  SUDO=
fi

SERVICE_USER="${SERVICE_USER:-thermalprinter}"
SERVICE_GROUP="${SERVICE_GROUP:-${SERVICE_USER}}"
APP_DIR="${APP_DIR:-/home/${SERVICE_USER}/thermal-print-service}"

as_service_user() {
  if [ "$(id -un)" = "${SERVICE_USER}" ]; then
    "$@"
  elif [ -n "${SUDO}" ]; then
    $SUDO -u "${SERVICE_USER}" "$@"
  elif command -v runuser >/dev/null 2>&1; then
    runuser -u "${SERVICE_USER}" -- "$@"
  else
    "$@"
  fi
}

echo "==> apt prerequisites"
$SUDO apt-get update
$SUDO apt-get install -y \
  python3-venv python3-pip \
  xfonts-utils \
  libusb-1.0-0 libudev1 \
  rsync

echo "==> ensure ${SERVICE_USER} user"
if ! getent group "${SERVICE_GROUP}" >/dev/null 2>&1; then
  $SUDO groupadd "${SERVICE_GROUP}"
fi

if ! id -u "${SERVICE_USER}" >/dev/null 2>&1; then
  $SUDO useradd \
    --create-home \
    --home-dir "/home/${SERVICE_USER}" \
    --shell /bin/bash \
    --gid "${SERVICE_GROUP}" \
    --groups lp \
    "${SERVICE_USER}"
else
  $SUDO usermod -aG lp "${SERVICE_USER}"
  if ! id -nG "${SERVICE_USER}" | tr ' ' '\n' | grep -qx "${SERVICE_GROUP}"; then
    $SUDO usermod -aG "${SERVICE_GROUP}" "${SERVICE_USER}"
  fi
fi

echo "==> ensure application directory"
$SUDO install -d -o "${SERVICE_USER}" -g "${SERVICE_GROUP}" -m 0755 "${APP_DIR}"

echo "==> create runtime state dir"
$SUDO install -d -o "${SERVICE_USER}" -g "${SERVICE_GROUP}" -m 0750 /var/lib/printer
$SUDO install -d -o "${SERVICE_USER}" -g "${SERVICE_GROUP}" -m 0750 /var/lib/printer/jobs
$SUDO install -d -o "${SERVICE_USER}" -g "${SERVICE_GROUP}" -m 0750 /var/lib/printer/cache
$SUDO install -d -o "${SERVICE_USER}" -g "${SERVICE_GROUP}" -m 0750 /var/lib/printer/idempotency

echo "==> sync current checkout into ${APP_DIR}"
if [ "$(pwd -P)" != "$(cd "${APP_DIR}" && pwd -P)" ]; then
  $SUDO rsync -a --delete \
    --exclude '.git' --exclude '.venv' --exclude '__pycache__' \
    --exclude 'service/tests/.golden-out' \
    --exclude '.pytest_cache' --exclude '.ruff_cache' --exclude '.mypy_cache' \
    ./ "${APP_DIR}/"
  $SUDO chown -R "${SERVICE_USER}:${SERVICE_GROUP}" "${APP_DIR}"
fi

echo "==> ensure venv + service deps"
as_service_user python3 -m venv "${APP_DIR}/.venv"
as_service_user "${APP_DIR}/.venv/bin/pip" install --upgrade pip wheel
as_service_user "${APP_DIR}/.venv/bin/pip" install -e "${APP_DIR}/printer-core"
as_service_user "${APP_DIR}/.venv/bin/pip" install -e "${APP_DIR}/service"

echo "==> install systemd units"
# printer.service (the print service) is always installed; printer-relay.service
# (the friend-network relay) is installed but stays DISABLED until the operator
# joins a hub -- `printer-svc relay run` exits if there are no creds, so enabling
# it before `printer-svc hub join` would just crash-loop.
for unit in printer.service printer-relay.service; do
  UNIT_TMP="$(mktemp)"
  sed \
    -e "s|User=thermalprinter|User=${SERVICE_USER}|g" \
    -e "s|Group=thermalprinter|Group=${SERVICE_GROUP}|g" \
    -e "s|/home/thermalprinter/thermal-print-service|${APP_DIR}|g" \
    "deploy/${unit}" > "${UNIT_TMP}"
  $SUDO install -m 0644 "${UNIT_TMP}" "/etc/systemd/system/${unit}"
  rm -f "${UNIT_TMP}"
done
$SUDO systemctl daemon-reload

echo "==> done. Reboot once for lp group to take effect, or open a new login shell."
echo "    To join the friend network: printer-svc hub join <code> --handle <h> --display-name <n>"
echo "    Then: sudo systemctl enable --now printer-relay.service"
