#!/bin/sh
# io-stall-watchdog -- force a reboot if the rootfs/SD card stops accepting writes.
#
# Why this exists: systemd's RuntimeWatchdog only proves PID1 is alive. During an
# SD-card I/O stall (observed 2026-06-24: host dark ~31h) systemd keeps petting
# /dev/watchdog because its keepalive never touches the disk, while every
# disk-bound process wedges in uninterruptible D-state. The box stays up on paper
# but answers nothing. This daemon probes the actual failing surface -- a
# write+fsync to the SD -- and hard-resets via sysrq when it stays dead, turning
# hours of downtime into ~80s of auto-recovery. Its control path uses only /proc
# and shell builtins, so it survives the stall it is detecting (a D-state probe
# child cannot block the loop -- timeout returns even if the child lingers).

set -u

PROBE_DIR="${IOWDT_DIR:-/var/lib/printer}"
PROBE_FILE="$PROBE_DIR/.io-stall-probe"
INTERVAL="${IOWDT_INTERVAL:-20}"      # seconds between probes
PROBE_TIMEOUT="${IOWDT_TIMEOUT:-10}"  # max seconds a healthy write+fsync may take
FAIL_LIMIT="${IOWDT_FAILS:-4}"        # consecutive failures before reset (~80s)
GRACE="${IOWDT_GRACE:-120}"           # do not arm until this much uptime (seconds)
DRYRUN="${IOWDT_DRYRUN:-0}"           # 1 = log the decision instead of rebooting

log() { echo "io-stall-watchdog: $*"; }

fails=0
log "started dir=$PROBE_DIR interval=${INTERVAL}s timeout=${PROBE_TIMEOUT}s limit=$FAIL_LIMIT grace=${GRACE}s dryrun=$DRYRUN"

while : ; do
    up=$(cut -d. -f1 /proc/uptime)
    if [ "${up:-0}" -lt "$GRACE" ]; then
        sleep "$INTERVAL"
        continue
    fi

    # Probe in a timeout-bounded child. A stalled card makes write/fsync block in
    # D-state; timeout returns non-zero regardless, so this loop keeps control.
    if PROBE_FILE="$PROBE_FILE" timeout -k 2 "$PROBE_TIMEOUT" \
        sh -c 'printf "%s\n" "$(cut -d" " -f1 /proc/uptime)" > "$PROBE_FILE" && sync "$PROBE_FILE"' \
        2>/dev/null
    then
        [ "$fails" -ne 0 ] && log "disk write recovered after $fails failure(s)"
        fails=0
    else
        fails=$((fails + 1))
        log "disk write+fsync FAILED/STALLED ($fails/$FAIL_LIMIT)"
        if [ "$fails" -ge "$FAIL_LIMIT" ]; then
            secs=$((fails * INTERVAL))
            if [ "$DRYRUN" = "1" ]; then
                log "DRYRUN: rootfs stalled ~${secs}s -- would write 'b' to /proc/sysrq-trigger"
                fails=0
            else
                log "rootfs I/O stalled ~${secs}s -- forcing hard reset via sysrq"
                echo b > /proc/sysrq-trigger
                sleep 5
                # Fallbacks if sysrq 'b' was disabled for some reason.
                systemctl reboot -ff 2>/dev/null || reboot -f 2>/dev/null || true
            fi
        fi
    fi
    sleep "$INTERVAL"
done
