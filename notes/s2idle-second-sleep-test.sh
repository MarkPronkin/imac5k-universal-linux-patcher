#!/usr/bin/env bash
# Two s2idle sleeps in one boot, to test the "second sleep resets" pattern.
#
#   sudo bash notes/s2idle-second-sleep-test.sh [seconds] [rebound|unbound] [states] [modules]
#
# Every reset so far came on the SECOND sleep of a boot, about 50 s in, while
# the first sleep of a boot always survived. See
# notes/wifi-suspend-handoff-2026-09-11.md.
#
#   seconds   how long to leave the second sleep alone (default 180)
#   unbound   leave the Thunderbolt and Wi-Fi functions unbound between the two
#             sleeps (tested 2026-09-12: the second sleep still reset, so the
#             hooks' rebinds are not the cause)
#   states    cpuidle states to disable for the whole run, e.g. 456 to drop
#             C6/C7s/C8 and leave C3 as the deepest, or - for none
#   modules   comma-separated modules to unload between the two sleeps and
#             reload at the end, e.g. applesmc
set -uo pipefail
WAIT=${1:-180}
MODE=${2:-rebound}
STATES=${3:-}
[[ $STATES == - ]] && STATES=
MODULES=${4:-}
TB=0000:07:00.0
WIFI=0000:03:00.0

[[ $EUID -eq 0 ]] || { echo "run with sudo" >&2; exit 1; }
[[ $MODE == rebound || $MODE == unbound ]] || { echo "second argument: rebound or unbound" >&2; exit 1; }

idle=()
if [[ -n $STATES ]]; then
    [[ $STATES =~ ^[0-9]+$ ]] || { echo "third argument: state digits, e.g. 456" >&2; exit 1; }
    idle=(/sys/devices/system/cpu/cpu*/cpuidle/state["$STATES"]/disable)
    [[ -e ${idle[0]} ]] || { echo "no cpuidle state$STATES files here" >&2; exit 1; }
fi

restore() { for f in "${idle[@]}"; do echo 0 > "$f" 2>/dev/null; done; }
trap restore EXIT

if ((${#idle[@]})); then
    for f in "${idle[@]}"; do echo 1 > "$f" || { echo "could not write $f" >&2; exit 1; }; done
    echo "idle states $STATES disabled for this run:"
    for s in /sys/devices/system/cpu/cpu0/cpuidle/state*; do
        printf '  %-5s disabled=%s\n' "$(cat "$s/name")" "$(cat "$s/disable")"
    done
fi

stats() { printf 'success=%s fail=%s' "$(cat /sys/power/suspend_stats/success)" "$(cat /sys/power/suspend_stats/fail)"; }

do_sleep() {   # $1 = label
    local ok bad
    ok=$(cat /sys/power/suspend_stats/success)
    bad=$(cat /sys/power/suspend_stats/fail)
    sync
    systemctl suspend
    # This process is frozen with the session while the machine sleeps and
    # carries on after the wake; wait for the counters to move.
    for _ in $(seq 1800); do
        [[ $(cat /sys/power/suspend_stats/success) != "$ok" || \
           $(cat /sys/power/suspend_stats/fail) != "$bad" ]] && break
        sleep 1
    done
    sleep 2
    echo "$1: back at $(date +%H:%M:%S), $(stats)"
}

echo
echo "Mode: $MODE. Second sleep will be left alone for ${WAIT}s."
echo "SLEEP 1 of 2 starting. Let it sleep about 30 s, then wake it with a key."
do_sleep "sleep 1"

if [[ $MODE == unbound ]]; then
    echo
    for d in "thunderbolt/$TB" "brcmfmac/$WIFI"; do
        drv=${d%%/*}; bdf=${d##*/}
        if [[ -e /sys/bus/pci/drivers/$drv/$bdf ]]; then
            echo "$bdf" > "/sys/bus/pci/drivers/$drv/unbind" 2>/dev/null &&
                echo "left $bdf unbound between the sleeps"
        fi
    done
fi

if [[ -n $MODULES ]]; then
    echo
    for mod in ${MODULES//,/ }; do
        if lsmod | grep -q "^${mod} "; then
            modprobe -r "$mod" && echo "unloaded $mod for the second sleep" ||
                echo "could not unload $mod" >&2
        else
            echo "$mod is not loaded"
        fi
    done
fi

echo
echo "SLEEP 2 of 2 starting. Leave it alone for ${WAIT}s, well past the ~50 s"
echo "mark, then wake it with a key. If it reboots, say how long it slept."
do_sleep "sleep 2"

echo
journalctl -b --since "-30 min" --no-pager 2>/dev/null |
    grep -E 'sleep-hook|sleep operation|returned from sleep|Failed to put|PM: suspend' | tail -12
if ((${#idle[@]})); then
    echo
    echo "s2idle usage per state (which state the sleeps used):"
    for s in /sys/devices/system/cpu/cpu0/cpuidle/state*; do
        printf '  %-5s usage=%s\n' "$(cat "$s/name")" "$(cat "$s/s2idle/usage" 2>/dev/null || echo -)"
    done
fi
if [[ $MODE == unbound ]]; then
    for d in "thunderbolt/$TB" "brcmfmac/$WIFI"; do
        drv=${d%%/*}; bdf=${d##*/}
        [[ -e /sys/bus/pci/drivers/$drv/$bdf ]] || echo "$bdf" > "/sys/bus/pci/drivers/$drv/bind" 2>/dev/null
    done
    echo "rebound both devices"
fi
if [[ -n $MODULES ]]; then
    for mod in ${MODULES//,/ }; do
        modprobe "$mod" 2>/dev/null && echo "reloaded $mod"
    done
fi
echo "done"
