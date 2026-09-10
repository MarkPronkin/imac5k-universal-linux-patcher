#!/usr/bin/env bash
# Checks that systemd suspends in s2idle through imac5k-s2idle.conf: one
# `systemctl suspend` in pm_test=freezer mode, with /sys/power/mem_sleep set to
# deep first, so only systemd's MemorySleepMode= can bring s2idle back.
# Nothing really sleeps: the kernel freezes tasks for about five seconds and
# thaws them. The Thunderbolt hook still unbinds and rebinds, and the desktop
# may lock the screen. Needs root, after `imac-patcher --apply suspend`.
set -uo pipefail
[[ $EUID -eq 0 ]] || { echo "run it with sudo" >&2; exit 1; }
conf=/etc/systemd/sleep.conf.d/imac5k-s2idle.conf
[[ -f $conf ]] || { echo "no $conf: apply the suspend module first" >&2; exit 1; }

mode_before=$(grep -o '\[[a-z0-9]*\]' /sys/power/mem_sleep | tr -d '[]')
restore() {
    echo none > /sys/power/pm_test
    echo "$mode_before" > /sys/power/mem_sleep
    echo "restored: pm_test none, mem_sleep: $(cat /sys/power/mem_sleep)"
}
trap restore EXIT

echo deep > /sys/power/mem_sleep
echo freezer > /sys/power/pm_test
grep -q '\[freezer\]' /sys/power/pm_test || { echo "pm_test did not arm; not suspending" >&2; exit 1; }

since=$(date '+%Y-%m-%d %H:%M:%S')
systemctl suspend || exit 1
for _ in $(seq 60); do
    journalctl -k -q --no-pager --since "$since" | grep -q 'PM: suspend exit' && break
    sleep 1
done
log=$(journalctl -q --no-pager --since "$since" | grep -E 'PM: suspend (entry|exit)|imac-tb-sleep-hook')
printf '%s\n' "$log"
if grep -q 'PM: suspend entry (s2idle)' <<<"$log"; then
    echo "PASS: systemd switched mem_sleep from deep to s2idle before suspending"
elif grep -q 'PM: suspend entry' <<<"$log"; then
    echo "FAIL: $(grep -o 'suspend entry ([a-z0-9]*)' <<<"$log" | head -1) — the drop-in did not take"
    exit 1
else
    echo "INCONCLUSIVE: no suspend within 60 s (an inhibitor? see systemd-inhibit --list)"
    exit 1
fi
