#!/usr/bin/env bash
# Idempotent Pi provisioning. Safe to re-run.
set -euo pipefail

SUDO=$(command -v sudo)

echo "==> apt prerequisites"
$SUDO apt-get update
$SUDO apt-get install -y \
  python3-venv python3-pip \
  xfonts-utils \
  libusb-1.0-0 libudev1 \
  rsync

echo "==> add thermalprinter to lp group"
$SUDO usermod -aG lp thermalprinter

echo "==> create runtime state dir"
$SUDO install -d -o thermalprinter -g thermalprinter -m 0750 /var/lib/printer
$SUDO install -d -o thermalprinter -g thermalprinter -m 0750 /var/lib/printer/jobs
$SUDO install -d -o thermalprinter -g thermalprinter -m 0750 /var/lib/printer/cache
$SUDO install -d -o thermalprinter -g thermalprinter -m 0750 /var/lib/printer/idempotency

echo "==> install service unit"
$SUDO install -m 0644 deploy/printer.service /etc/systemd/system/printer.service
$SUDO systemctl daemon-reload

echo "==> done. Reboot once for lp group to take effect, or open a new login shell."
