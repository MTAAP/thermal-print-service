#!/usr/bin/env bash
# Configure Tailscale Serve to terminate HTTPS for the printer service.
# Run on the Pi (one-shot; tailscale persists the config across reboots).
#
# Result: https://<host>.<tailnet>.ts.net/  -> http://127.0.0.1:8000
#
# Note: the older `--https=443` / JSON-config form was deprecated in 1.46+;
# the current CLI accepts an imperative target URL directly.
set -euo pipefail

PORT="${PORT:-8000}"

echo "==> tailscale serve --bg http://127.0.0.1:${PORT}"
sudo tailscale serve --bg "http://127.0.0.1:${PORT}"

echo "==> current serve status:"
tailscale serve status
