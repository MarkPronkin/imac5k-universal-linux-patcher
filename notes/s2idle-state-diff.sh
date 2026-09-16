#!/usr/bin/env bash
# What does the first resume leave changed?
#
#   sudo bash notes/s2idle-state-diff.sh
#
# On this iMac the first s2idle sleep of a boot always works and the second
# always resets the machine at ~50 s. So something the first cycle leaves
# behind is the culprit. This takes a broad snapshot of system state, sleeps
# ONCE (the safe one), snapshots again after the wake, and prints the diff.
# It never takes a second sleep, so it cannot reset the machine.
#
# Snapshots stay in /var/tmp/s2idle-diff/ for later comparison.
set -uo pipefail
OUT=/var/tmp/s2idle-diff
[[ $EUID -eq 0 ]] || { echo "run with sudo" >&2; exit 1; }

snapshot() {   # $1 = directory
    local d=$1
    mkdir -p "$d"
    cat /proc/acpi/wakeup > "$d/acpi_wakeup.txt" 2>/dev/null
    for f in /sys/firmware/acpi/interrupts/*; do
        printf '%-20s %s\n' "${f##*/}" "$(cat "$f" 2>/dev/null)"
    done > "$d/acpi_gpe.txt"
    for p in /sys/bus/pci/devices/*; do
        printf '%s power_state=%s runtime=%s wakeup=%s d3cold=%s driver=%s\n' \
            "${p##*/}" "$(cat "$p/power_state" 2>/dev/null)" \
            "$(cat "$p/power/runtime_status" 2>/dev/null)" \
            "$(cat "$p/power/wakeup" 2>/dev/null || echo -)" \
            "$(cat "$p/d3cold_allowed" 2>/dev/null)" \
            "$(basename "$(readlink "$p/driver" 2>/dev/null)" 2>/dev/null || echo -)"
    done > "$d/pci.txt"
    lspci -vvnn 2>/dev/null | grep -E '^[0-9a-f]{2}:|LnkSta:|LnkCtl:|PME-Enable|Status:.*PME' > "$d/pci_link.txt"
    for u in /sys/bus/usb/devices/*; do
        printf '%s wakeup=%s runtime=%s level=%s\n' "${u##*/}" \
            "$(cat "$u/power/wakeup" 2>/dev/null || echo -)" \
            "$(cat "$u/power/runtime_status" 2>/dev/null || echo -)" \
            "$(cat "$u/power/control" 2>/dev/null || echo -)"
    done > "$d/usb.txt"
    { for f in /sys/power/mem_sleep /sys/power/pm_test /sys/power/wakeup_count \
               /sys/power/suspend_stats/success /sys/power/suspend_stats/fail; do
          printf '%-40s %s\n' "$f" "$(cat "$f" 2>/dev/null)"
      done; } > "$d/power.txt"
    for s in /sys/devices/system/cpu/cpu0/cpuidle/state*; do
        printf '%-6s %-5s disable=%s s2idle_usage=%s\n' "${s##*/}" \
            "$(cat "$s/name")" "$(cat "$s/disable")" "$(cat "$s/s2idle/usage" 2>/dev/null || echo -)"
    done > "$d/cpuidle.txt"
    lsmod | awk 'NR>1 {print $1}' | sort > "$d/modules.txt"
    for n in /sys/class/net/*; do
        printf '%s operstate=%s carrier=%s wakeup=%s\n' "${n##*/}" \
            "$(cat "$n/operstate" 2>/dev/null)" "$(cat "$n/carrier" 2>/dev/null || echo -)" \
            "$(cat "$n/device/power/wakeup" 2>/dev/null || echo -)"
    done > "$d/net.txt"
    for c in /sys/class/drm/card*-*; do
        printf '%s status=%s\n' "${c##*/}" "$(cat "$c/status" 2>/dev/null)"
    done > "$d/drm.txt"
    for t in /sys/class/thermal/thermal_zone*; do
        printf '%s %s %s\n' "${t##*/}" "$(cat "$t/type" 2>/dev/null)" "$(cat "$t/temp" 2>/dev/null)"
    done > "$d/thermal.txt"
    if [[ -d /sys/devices/platform/applesmc.768 ]]; then
        for f in /sys/devices/platform/applesmc.768/fan*_{input,output,manual,min,max}; do
            [[ -e $f ]] && printf '%s %s\n' "${f##*/}" "$(cat "$f" 2>/dev/null)"
        done > "$d/applesmc.txt"
    fi
    awk '{ $2=""; $3=""; $4=""; $5=""; print }' /proc/interrupts > "$d/irq_names.txt" 2>/dev/null
    sync
}

echo "snapshot 1: before any sleep"
snapshot "$OUT/before"

echo
echo "Sleeping now — this is the FIRST sleep of the boot, the safe one."
echo "Let it sleep ~30 s, then wake it with a key."
ok=$(cat /sys/power/suspend_stats/success)
bad=$(cat /sys/power/suspend_stats/fail)
sync
systemctl suspend
for _ in $(seq 1800); do
    [[ $(cat /sys/power/suspend_stats/success) != "$ok" || \
       $(cat /sys/power/suspend_stats/fail) != "$bad" ]] && break
    sleep 1
done
sleep 5

echo "snapshot 2: after the first resume"
snapshot "$OUT/after"

echo
echo "=============== what the first sleep changed ==============="
for f in "$OUT"/before/*.txt; do
    n=${f##*/}
    if ! diff -q "$f" "$OUT/after/$n" >/dev/null 2>&1; then
        echo
        echo "--- $n ---"
        diff -U0 "$f" "$OUT/after/$n" | grep -vE '^(---|\+\+\+|@@)' | head -40
    fi
done
echo
echo "(snapshots kept in $OUT)"
