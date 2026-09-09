#!/bin/sh
# io-stall-watchdog -- reboot the Pi when it stops being useful, not just when
# PID 1 stops running.
#
# Why this exists: a Pi Zero 2 W goes dark in ways that leave systemd perfectly
# healthy. An SD-card I/O stall (2026-06-24, dark ~31h) wedges every disk-bound
# process in uninterruptible D-state while systemd's own keepalive, which never
# touches the disk, keeps petting the hardware watchdog. A brcmfmac firmware
# wedge (suspected 2026-09-08, dark ~22h) leaves the box locally healthy and
# unreachable from every network path. Neither is visible to a liveness check
# that only asks "is init scheduling?".
#
# So this daemon owns /dev/watchdog0 itself and pets it ONLY while both surfaces
# answer. Going unhealthy is not an active reboot, it is the absence of a pet:
# the hardware resets on its own timeout. That inversion is the whole point,
# because it also covers this script hanging, being killed, or its host stalling
# in a way it cannot detect.
#
# Two rules keep it honest under the failures it is meant to catch:
#
#   1. The control path never touches the failing surface. Probes run detached
#      and report success by stamping /run (tmpfs); the loop reads only /run and
#      /proc. The previous version ran the probe under `timeout`, which blocks
#      in waitpid() on a child stuck in D-state -- SIGKILL is queued but cannot
#      be delivered until the I/O completes -- so the very first genuine stall
#      hung the loop before it could ever count a failure.
#   2. Petting is decoupled from probing. The hardware timeout is shorter than a
#      sensible probe cycle -- 15s on this board, and note that systemd had been
#      raising it to 60s while it held the device, so it changes the moment we
#      take over -- and the pet interval is derived from it at startup rather
#      than hardcoded. The pet asks a cached health flag, never a fresh probe.
#
# To watch the recovery ladder climb without touching the real network or the
# real watchdog device, run it against a fake device with the bounce delay set
# to zero -- every step names itself and performs nothing:
#
#   sudo IOWDT_DRYRUN=1 IOWDT_WATCHDOG=/tmp/fake-wd IOWDT_RUN_DIR=/run/iowdt-test \
#        IOWDT_NET_BOUNCE=0 IOWDT_NET_BOUNCE_INTERVAL=2 IOWDT_GRACE=0 \
#        timeout 11 /usr/local/sbin/io-stall-watchdog.sh
#
# If /dev/watchdog0 cannot be opened -- most likely because systemd still holds
# it, see 40-rpi-enable-watchdog.conf -- this degrades to the sysrq path and
# says so loudly. It never degrades into a reboot loop.

set -u

PROBE_DIR="${IOWDT_DIR:-/var/lib/printer}"
PROBE_FILE="$PROBE_DIR/.io-stall-probe"
RUN_DIR="${IOWDT_RUN_DIR:-/run/io-stall-watchdog}"
DISK_STAMP="$RUN_DIR/disk.ok"
NET_STAMP="$RUN_DIR/net.ok"
WATCHDOG_DEV="${IOWDT_WATCHDOG:-/dev/watchdog0}"

PET_INTERVAL="${IOWDT_PET_INTERVAL:-0}"    # 0 = derive from the hardware timeout
PROBE_INTERVAL="${IOWDT_INTERVAL:-20}"     # seconds between probe launches
DISK_LIMIT="${IOWDT_DISK_LIMIT:-80}"       # no successful disk probe for this long -> unhealthy
NET_LIMIT="${IOWDT_NET_LIMIT:-240}"        # no network for this long -> unhealthy
NET_BOUNCE_AFTER="${IOWDT_NET_BOUNCE:-90}"  # start trying to fix the link at this age
NET_BOUNCE_INTERVAL="${IOWDT_NET_BOUNCE_INTERVAL:-60}"  # seconds between recovery steps
NET_IFACE="${IOWDT_NET_IFACE:-wlan0}"
GRACE="${IOWDT_GRACE:-120}"                # do not arm until this much uptime
DRYRUN="${IOWDT_DRYRUN:-0}"                # 1 = log the decision, keep petting

log() { echo "io-stall-watchdog: $*"; }

uptime_s() { cut -d. -f1 /proc/uptime; }

mkdir -p "$RUN_DIR" 2>/dev/null || true

# Own the watchdog, or say why not. A failure here is not fatal: no pet means no
# hardware protection, which is exactly where we were before this script existed.
HAVE_WD=0
if exec 9>"$WATCHDOG_DEV" 2>/dev/null; then
    HAVE_WD=1
    WD_TIMEOUT=$(cat /sys/class/watchdog/watchdog0/timeout 2>/dev/null || echo "")
    # Derive the pet interval from the device rather than hardcoding it. The
    # BCM2835 defaults to 15s, but while systemd owned the device it had raised
    # it to 60s -- so a value that looked safe under systemd becomes a coin flip
    # the moment we take the device over. A quarter of the timeout leaves three
    # missed pets of headroom.
    case "${WD_TIMEOUT:-}" in
        ''|*[!0-9]*) WD_TIMEOUT=15 ;;
    esac
    if [ "$PET_INTERVAL" -le 0 ] || [ "$PET_INTERVAL" -ge "$WD_TIMEOUT" ]; then
        PET_INTERVAL=$((WD_TIMEOUT / 4))
        [ "$PET_INTERVAL" -lt 2 ] && PET_INTERVAL=2
    fi
    log "holding $WATCHDOG_DEV (hardware timeout ${WD_TIMEOUT}s, petting every ${PET_INTERVAL}s)"
else
    log "WARNING cannot open $WATCHDOG_DEV -- another process holds it (systemd?);"
    log "WARNING falling back to sysrq only, so a hang of THIS script is unprotected"
    [ "$PET_INTERVAL" -le 0 ] && PET_INTERVAL=5
fi

# Petting with anything but 'V' keeps the timer alive. Closing fd 9 without
# writing 'V' is a magic close, which resets the box -- the behaviour we want if
# this process dies unexpectedly.
pet() { [ "$HAVE_WD" -eq 1 ] && printf 'x' >&9 2>/dev/null; return 0; }

# Both probes run detached and report by stamping tmpfs. Neither is ever waited
# on, so neither can block the loop no matter how wedged the surface is.
probe_disk() {
    (
        printf '%s\n' "$(uptime_s)" > "$PROBE_FILE" &&
        sync "$PROBE_FILE" &&
        printf '%s\n' "$(uptime_s)" > "$DISK_STAMP"
    ) >/dev/null 2>&1 &
}

probe_net() {
    (
        gw=$(ip route show default 2>/dev/null | awk '/default/ {print $3; exit}')
        [ -n "${gw:-}" ] || exit 1
        ping -c 1 -W 3 "$gw" >/dev/null 2>&1 &&
            printf '%s\n' "$(uptime_s)" > "$NET_STAMP"
    ) >/dev/null 2>&1 &
}

# The recovery ladder, in increasing order of force. NetworkManager owns wlan0
# on this box, so a raw link bounce is the gentlest thing that can clear a
# brcmfmac wedge, and restarting NetworkManager is the last thing short of a
# reset. Each is a plain function so start_recovery can background it without
# eval, and so a dry run can name the step without performing it.
recover_link_bounce() { ip link set "$NET_IFACE" down; sleep 2; ip link set "$NET_IFACE" up; }
recover_nm_reconnect() { nmcli device disconnect "$NET_IFACE"; sleep 2; nmcli device connect "$NET_IFACE"; }
recover_nm_restart() { systemctl restart NetworkManager; }

start_recovery() { # start_recovery <description> <function>
    _what=$1
    shift
    log "no network for ${net_age}s -- recovery step $bounce_step: $_what"
    if [ "$DRYRUN" = "1" ]; then
        log "DRYRUN: would run $*"
        return 0
    fi
    "$@" >/dev/null 2>&1 &
    bounce_pid=$!
}

# Age of a stamp in seconds, or a number larger than any limit when missing. The
# read is tmpfs-only, so it cannot inherit the stall it is measuring.
stamp_age() {
    _now=$(uptime_s)
    _then=$(cat "$1" 2>/dev/null) || _then=""
    case "${_then:-}" in
        ''|*[!0-9]*) echo 999999; return ;;
    esac
    echo $((_now - _then))
}

# A live child means the previous probe is still stuck. Tracking the pid stops
# one wedged surface from spawning a probe every 20s until PIDs run out; the
# unreaped D-state child is bounded at one per surface.
disk_pid=""
net_pid=""
child_alive() { [ -n "${1:-}" ] && [ -d "/proc/$1" ]; }

# Both surfaces start healthy so a slow first probe never reboots a fresh boot.
: > "$DISK_STAMP" 2>/dev/null
printf '%s\n' "$(uptime_s)" > "$DISK_STAMP" 2>/dev/null
printf '%s\n' "$(uptime_s)" > "$NET_STAMP" 2>/dev/null

last_probe=0
last_bounce=0
bounce_step=0
bounce_pid=""
unhealthy_logged=0

log "started disk=$PROBE_DIR iface=$NET_IFACE pet=${PET_INTERVAL}s probe=${PROBE_INTERVAL}s" \
    "disk_limit=${DISK_LIMIT}s net_limit=${NET_LIMIT}s bounce_after=${NET_BOUNCE_AFTER}s" \
    "bounce_every=${NET_BOUNCE_INTERVAL}s grace=${GRACE}s dryrun=$DRYRUN wd=$HAVE_WD"

while : ; do
    up=$(uptime_s)

    # Before the grace period the box is still coming up: pet unconditionally so
    # a slow boot is never mistaken for a stall.
    if [ "${up:-0}" -lt "$GRACE" ]; then
        pet
        sleep "$PET_INTERVAL"
        continue
    fi

    if [ $((up - last_probe)) -ge "$PROBE_INTERVAL" ]; then
        last_probe=$up
        if child_alive "$disk_pid"; then
            log "previous disk probe still wedged (pid $disk_pid)"
        else
            probe_disk
            disk_pid=$!
        fi
        if child_alive "$net_pid"; then
            log "previous network probe still wedged (pid $net_pid)"
        else
            probe_net
            net_pid=$!
        fi
    fi

    disk_age=$(stamp_age "$DISK_STAMP")
    net_age=$(stamp_age "$NET_STAMP")

    # Try to fix the link before treating the network as fatal, and hit harder
    # each time. A single link bounce was enough on 2026-09-09 at 16:31 and
    # 17:06 and not enough at 18:25, so one attempt is a coin flip. Each step
    # runs detached: a wedged NetworkManager must never block the pet.
    if [ "$net_age" -ge "$NET_BOUNCE_AFTER" ] &&
       [ $((up - last_bounce)) -ge "$NET_BOUNCE_INTERVAL" ]; then
        if child_alive "$bounce_pid"; then
            log "previous recovery step still running (pid $bounce_pid) -- not starting another"
        else
            last_bounce=$up
            bounce_step=$((bounce_step + 1))
            case "$bounce_step" in
                1) start_recovery "a link bounce of $NET_IFACE" recover_link_bounce ;;
                2) start_recovery "a NetworkManager reconnect" recover_nm_reconnect ;;
                *) start_recovery "a NetworkManager restart" recover_nm_restart ;;
            esac
        fi
    fi

    if [ "$disk_age" -lt "$DISK_LIMIT" ] && [ "$net_age" -lt "$NET_LIMIT" ]; then
        if [ "$unhealthy_logged" -eq 1 ]; then
            log "recovered (disk ${disk_age}s ago, network ${net_age}s ago)"
            unhealthy_logged=0
        fi
        if [ "$bounce_step" -ne 0 ] && [ "$net_age" -lt "$NET_BOUNCE_AFTER" ]; then
            log "network back after $bounce_step recovery step(s)"
            bounce_step=0
        fi
        pet
    else
        if [ "$unhealthy_logged" -eq 0 ]; then
            log "UNHEALTHY disk_age=${disk_age}s (limit $DISK_LIMIT) net_age=${net_age}s (limit $NET_LIMIT)"
            unhealthy_logged=1
        fi
        if [ "$DRYRUN" = "1" ]; then
            log "DRYRUN: would stop petting and let the hardware reset the box"
            pet
        elif [ "$HAVE_WD" -eq 1 ]; then
            log "withholding the pet -- hardware watchdog will reset the box"
        else
            # No watchdog to withhold from, so this is the only lever left.
            log "no hardware watchdog held -- forcing a reset via sysrq"
            echo b > /proc/sysrq-trigger
            sleep 5
            systemctl reboot -ff 2>/dev/null || reboot -f 2>/dev/null || true
        fi
    fi

    sleep "$PET_INTERVAL"
done
