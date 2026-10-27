#!/bin/sh
# health-log -- append a line of board health so the next incident has a before.
#
# get_throttled carries sticky "has this ever happened" bits that are cleared by
# a hard power cycle, which is precisely what recovering from a hang requires.
# So after the fact there is no way to ask whether the box had been browning out
# or cooking for hours beforehand. Sampling it into the journal keeps that
# answer, and the journal now survives reboots.
set -u

throttled=$(vcgencmd get_throttled 2>/dev/null | cut -d= -f2)
temp=$(vcgencmd measure_temp 2>/dev/null | cut -d= -f2)
volts=$(vcgencmd measure_volts core 2>/dev/null | cut -d= -f2)
mem=$(awk '/MemAvailable/ {print int($2/1024) "M"}' /proc/meminfo 2>/dev/null)
load=$(cut -d' ' -f1-3 /proc/loadavg 2>/dev/null)

# Wifi is the failure this box actually has: the link dropped three times on
# 2026-09-09 and the last one cost 13 minutes and two hard resets. /proc/net/
# wireless needs no package and cannot block, unlike nmcli, which talks to the
# very daemon that may be wedged. Signal is dBm, so less negative is better and
# anything past -80 is the edge of association. Retries and missed beacons are
# cumulative since boot, so what matters is how fast they climb between samples.
IFACE="${HEALTH_LOG_IFACE:-wlan0}"
wifi=$(awk -v i="$IFACE:" '$1 == i {
    gsub(/\./, "", $3); gsub(/\./, "", $4)
    print "link=" $3 " signal=" $4 "dBm retries=" $9 " missed_beacon=" $11
}' /proc/net/wireless 2>/dev/null)
carrier=$(cat "/sys/class/net/$IFACE/operstate" 2>/dev/null)

# Decode the bits that matter. 0x0 is the healthy answer; anything else is worth
# seeing in isolation rather than as a hex blob nobody reads.
flags=""
case "$throttled" in
    0x0|"") ;;
    *)
        v=$((throttled))
        [ $((v & 0x1)) -ne 0 ] && flags="$flags under-voltage-now"
        [ $((v & 0x2)) -ne 0 ] && flags="$flags arm-freq-capped-now"
        [ $((v & 0x4)) -ne 0 ] && flags="$flags throttled-now"
        [ $((v & 0x8)) -ne 0 ] && flags="$flags soft-temp-limit-now"
        [ $((v & 0x10000)) -ne 0 ] && flags="$flags under-voltage-since-boot"
        [ $((v & 0x20000)) -ne 0 ] && flags="$flags arm-freq-capped-since-boot"
        [ $((v & 0x40000)) -ne 0 ] && flags="$flags throttled-since-boot"
        [ $((v & 0x80000)) -ne 0 ] && flags="$flags soft-temp-limit-since-boot"
        ;;
esac

echo "health: throttled=${throttled:-?}${flags:+ (}${flags# }${flags:+)} temp=${temp:-?} volts=${volts:-?} mem_avail=${mem:-?} load=${load:-?}"
echo "health: iface=$IFACE state=${carrier:-?} ${wifi:-link=? signal=? retries=? missed_beacon=?}"
