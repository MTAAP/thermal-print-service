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

# Host-liveness hardening (see deploy/io-stall-watchdog.sh for the full rationale).
# A systemd RuntimeWatchdog only proves PID 1 is alive. During an SD-card I/O stall
# the rootfs stops accepting writes and every disk-bound process wedges in D-state;
# during a brcmfmac firmware wedge the box is locally fine and unreachable. systemd
# pets /dev/watchdog through both, because its keepalive touches neither the disk
# nor the network. So we take RuntimeWatchdogSec away from systemd and give the
# device to a daemon that pets it only while both surfaces answer.
echo "==> install host watchdog, persistent journal, wifi power-save off, health log"
$SUDO install -m 0755 deploy/io-stall-watchdog.sh /usr/local/sbin/io-stall-watchdog.sh
$SUDO install -m 0644 deploy/io-stall-watchdog.service /etc/systemd/system/io-stall-watchdog.service
$SUDO install -d -m 0755 /etc/sysctl.d
$SUDO install -m 0644 deploy/io-stall-watchdog.sysctl.conf /etc/sysctl.d/99-io-stall-watchdog.conf

# Only one process may hold /dev/watchdog0, so systemd has to let go first. This
# drop-in sorts after the vendor's 40-rpi-enable-watchdog.conf and wins.
$SUDO install -d -m 0755 /etc/systemd/system.conf.d
$SUDO install -m 0644 deploy/systemd-no-runtime-watchdog.conf \
    /etc/systemd/system.conf.d/50-no-runtime-watchdog.conf

# Persistent journal. The vendor ships Storage=volatile in a 40- drop-in, so ours
# has to sort after it; the old 00-size.conf lost that race silently and every
# reboot took its logs with it. Remove the stale name so there is one file, not two.
$SUDO install -d -m 0755 /etc/systemd/journald.conf.d
$SUDO rm -f /etc/systemd/journald.conf.d/00-size.conf
$SUDO install -m 0644 deploy/journald.conf /etc/systemd/journald.conf.d/50-printer.conf
$SUDO install -d -m 2755 -o root -g systemd-journal /var/log/journal

# Wifi power save off: a known firmware-wedge trigger on this chip.
if [ -d /etc/NetworkManager ]; then
    $SUDO install -d -m 0755 /etc/NetworkManager/conf.d
    $SUDO install -m 0644 deploy/wifi-powersave-off.conf \
        /etc/NetworkManager/conf.d/50-wifi-powersave-off.conf
fi

# Board health into the journal, so the next incident has a before.
$SUDO install -m 0755 deploy/health-log.sh /usr/local/sbin/health-log.sh
$SUDO install -m 0644 deploy/health-log.service /etc/systemd/system/health-log.service
$SUDO install -m 0644 deploy/health-log.timer /etc/systemd/system/health-log.timer

$SUDO sysctl --system >/dev/null
$SUDO systemctl restart systemd-journald
$SUDO systemctl daemon-reload
# Releases /dev/watchdog0 from PID 1 so the daemon below can claim it.
$SUDO systemctl daemon-reexec
$SUDO systemctl enable --now io-stall-watchdog.service
$SUDO systemctl enable --now health-log.timer
$SUDO systemctl reload NetworkManager 2>/dev/null || true

echo "==> done. Reboot once for lp group to take effect, or open a new login shell."
echo "    To join the friend network: printer-svc hub join <code> --handle <h> --display-name <n>"
echo "    Then: sudo systemctl enable --now printer-relay.service"
