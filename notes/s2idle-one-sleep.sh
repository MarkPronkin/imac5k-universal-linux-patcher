#!/usr/bin/env bash
# One sleep now, with a list of modules unloaded first.
#
#   sudo bash notes/s2idle-one-sleep.sh [seconds] [modules]
#
# Meant for a boot that has ALREADY had its safe first sleep: on this iMac the
# next sleep is the one that resets the machine at ~50 s, so it is the slot to
# test a mitigation in. No reboot needed, and nothing is lost if it fails.
#
# Default modules are the ones whose state the first resume visibly changes:
# Thunderbolt and Wi-Fi (unbound and rebound by our sleep hooks, which also
# renumbers interrupts), the Intel ME interface, and the SMBus controller,
# which the firmware itself grabs during resume.
#
# Modules are unloaded in order and reloaded in reverse if the machine lives.
set -uo pipefail
WAIT=${1:-180}
MODULES=${2:-thunderbolt,brcmfmac_wcc,brcmfmac,mei_hdcp,mei_pxp,mei_me,mei,ee1004,i2c_i801}

[[ $EUID -eq 0 ]] || { echo "run with sudo" >&2; exit 1; }

read -ra mods <<< "${MODULES//,/ }"
echo "unloading: ${mods[*]}"
for m in "${mods[@]}"; do
    if lsmod | grep -q "^${m} "; then
        if modprobe -r "$m" 2>/dev/null; then echo "  unloaded $m"
        else echo "  COULD NOT unload $m (in use?)"; fi
    else
        echo "  $m not loaded"
    fi
done
echo
echo "still loaded of that list:"
lsmod | awk 'NR>1 {print $1}' | grep -xE "$(IFS='|'; echo "${mods[*]}")" || echo "  none"

ok=$(cat /sys/power/suspend_stats/success)
bad=$(cat /sys/power/suspend_stats/fail)
echo
echo "suspend_stats before: success=$ok fail=$bad"
echo "Sleeping now. Leave it alone for ${WAIT}s, well past the ~50 s mark,"
echo "then wake it with a key. If it reboots, the mitigation did not help."
sync
systemctl suspend
for _ in $(seq 1800); do
    [[ $(cat /sys/power/suspend_stats/success) != "$ok" || \
       $(cat /sys/power/suspend_stats/fail) != "$bad" ]] && break
    sleep 1
done
sleep 3

echo
echo "SURVIVED. back at $(date +%H:%M:%S), success=$(cat /sys/power/suspend_stats/success) fail=$(cat /sys/power/suspend_stats/fail)"
journalctl -b --since "-15 min" --no-pager 2>/dev/null |
    grep -E 'sleep-hook|sleep operation|returned from sleep|PM: suspend' | tail -8

echo
for (( i=${#mods[@]}-1; i>=0; i-- )); do
    modprobe "${mods[i]}" 2>/dev/null && echo "reloaded ${mods[i]}"
done
echo "done"
