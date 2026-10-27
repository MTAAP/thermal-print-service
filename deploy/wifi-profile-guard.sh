#!/usr/bin/env bash
# wifi-profile-guard -- restore the Wi-Fi netplan profile at boot if it is gone.
#
# Why this exists: on 2026-09-10 both NetworkManager profiles under /etc/netplan
# were truncated to 0 bytes, most likely by a hard reset mid-write. With no
# Wi-Fi profile the Pi never joined the network, so it stayed unreachable until
# someone rewrote the file from another machine. cloud-init applies the boot
# partition's network-config only on first boot, so nothing on the Pi restored it.
#
# Runs before NetworkManager. If no non-empty netplan file defines a Wi-Fi
# network, it copies network-config into place crash-safely and regenerates the
# profiles. It never fails the boot: every path exits 0.

set -uo pipefail

NETPLAN_DIR="${WIFI_GUARD_NETPLAN_DIR:-/etc/netplan}"
SOURCE="${WIFI_GUARD_SOURCE:-/boot/firmware/network-config}"
TARGET="${NETPLAN_DIR}/${WIFI_GUARD_TARGET_NAME:-50-cloud-init.yaml}"
GENERATE="${WIFI_GUARD_GENERATE:-netplan generate}"

log() { echo "wifi-profile-guard: $*"; }

# Counts only a file that names at least one network: an empty "wifis: {}"
# section generates no NetworkManager profile.
defines_wifi() {
    [ -s "$1" ] && grep -Eq '^[[:space:]]*wifis:' "$1" \
        && grep -Eq '^[[:space:]]*access-points:' "$1"
}

restore() {
    for f in "$NETPLAN_DIR"/*.yaml; do
        if defines_wifi "$f"; then
            log "Wi-Fi profile present ($f); nothing to do"
            return 0
        fi
    done

    if ! defines_wifi "$SOURCE"; then
        log "no Wi-Fi profile in $NETPLAN_DIR and no usable source at $SOURCE; nothing restored"
        return 0
    fi

    # Temp file, fsync, rename, fsync the directory: a reset at any point leaves
    # either no target or a complete one, never the 0-byte file this guards against.
    local tmp="${TARGET}.tmp.$$"
    if ! (umask 077 && cp "$SOURCE" "$tmp") || ! chmod 0600 "$tmp"; then
        rm -f "$tmp"
        log "ERROR: could not stage $tmp; nothing restored"
        return 1
    fi
    if [ "$(id -u)" = 0 ]; then
        chown 0:0 "$tmp"
    fi
    if ! sync "$tmp" || ! mv -f "$tmp" "$TARGET"; then
        rm -f "$tmp"
        log "ERROR: could not move the profile into $TARGET; nothing restored"
        return 1
    fi
    sync "$NETPLAN_DIR"
    log "no Wi-Fi profile in $NETPLAN_DIR; restored $TARGET from $SOURCE"

    # The netplan systemd generator already ran this boot, so regenerate the
    # NetworkManager keyfiles from the restored YAML.
    local -a generate
    read -r -a generate <<< "$GENERATE"
    # Discard netplan's output: on a parse error it quotes the offending line,
    # which can be the Wi-Fi password.
    if ! "${generate[@]}" >/dev/null 2>&1; then
        log "ERROR: '$GENERATE' failed (output suppressed); the profile is restored but may not load until next boot"
        return 1
    fi
    # Only matters on a manual run: at boot this unit finishes before NetworkManager starts.
    if command -v systemctl >/dev/null 2>&1 && systemctl is-active --quiet NetworkManager.service; then
        nmcli connection reload || log "ERROR: nmcli connection reload failed"
    fi
}

restore || true
exit 0
