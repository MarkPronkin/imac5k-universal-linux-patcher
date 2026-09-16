#!/usr/bin/env bash
# One s2idle sleep with the deepest CPU idle states (C6, C7s, C8) disabled.
#
#   sudo bash notes/s2idle-cstate-test.sh [seconds-to-stay-asleep] [states]
#
# `states` are the cpuidle state numbers to disable, default 456 (C6, C7s, C8).
# Use 6 for C8 alone, 56 for C7s and C8, and so on.
#
# Background: this iMac resets itself about 50 s into s2idle whenever it is
# left asleep (see notes/wifi-suspend-handoff-2026-09-11.md). This checks
# whether the deepest package idle states are the trigger. Watch the screen
# while it sleeps and note whether it lights up before any reboot.
#
# The idle states are restored on exit; a reset clears them anyway, since they
# are runtime settings.
set -uo pipefail
WAIT=${1:-120}
STATES=${2:-456}

[[ $EUID -eq 0 ]] || { echo "run with sudo" >&2; exit 1; }
[[ $STATES =~ ^[0-9]+$ ]] || { echo "states must be digits, e.g. 6 or 456" >&2; exit 1; }
states=(/sys/devices/system/cpu/cpu*/cpuidle/state["$STATES"]/disable)
[[ -e ${states[0]} ]] || { echo "no cpuidle state$STATES files here" >&2; exit 1; }

restore() { for f in "${states[@]}"; do echo 0 > "$f" 2>/dev/null; done; }
trap restore EXIT

show() { grep -H . /sys/devices/system/cpu/cpu0/cpuidle/"$1" 2>/dev/null | sed 's|.*/cpuidle/||'; }

for f in "${states[@]}"; do
    echo 1 > "$f" || { echo "could not write $f" >&2; exit 1; }
done
echo "idle states $STATES disabled on $(nproc) CPUs:"
show 'state*/disable'
echo
echo "s2idle usage before:"; show 'state*/s2idle/usage'

before=$(date +%s)
ok=$(cat /sys/power/suspend_stats/success 2>/dev/null || echo 0)
bad=$(cat /sys/power/suspend_stats/fail 2>/dev/null || echo 0)

echo
echo "Suspending now. Leave it alone for about ${WAIT}s, then wake it with a key."
echo "Watch the screen: does it light up on its own before any reboot?"
sync
systemctl suspend

# systemctl returns at once; this process is frozen with the session while the
# machine sleeps and carries on after the wake. Wait for the counters to move.
for _ in $(seq 900); do
    now_ok=$(cat /sys/power/suspend_stats/success 2>/dev/null || echo 0)
    now_bad=$(cat /sys/power/suspend_stats/fail 2>/dev/null || echo 0)
    [[ $now_ok != "$ok" || $now_bad != "$bad" ]] && break
    sleep 1
done

echo
echo "back after $(( $(date +%s) - before ))s in total"
echo "suspend_stats: success $(cat /sys/power/suspend_stats/success) fail $(cat /sys/power/suspend_stats/fail)"
echo
journalctl -b --since "-15 min" --no-pager 2>/dev/null |
    grep -E 'sleep-hook|sleep operation|returned from sleep|Failed to put|PM: suspend' | tail -8
echo
echo "s2idle usage after (which idle state the sleep actually used):"
show 'state*/s2idle/usage'
