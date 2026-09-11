#!/usr/bin/env bash
# Staged suspend test for the BCM43602 Wi-Fi (brcmfmac). Run with sudo:
#   sudo bash notes/wifi-d3-test.sh
# Written 2026-09-11 for notes/wifi-suspend-handoff-2026-09-11.md; a
# diagnostic, not part of the release.
#
# Every run uses the kernel's pm_test=devices stage: all devices are
# suspended, the kernel waits 5 seconds, then everything resumes. The machine
# never actually sleeps and the Thunderbolt noirq phase is never reached. The
# screen blanks and comes back once per run, about 10 s each.
#
#   1. Wi-Fi interface up     what a direct kernel suspend sees    expect PASS
#   2. Wi-Fi interface down   what NetworkManager leaves at sleep  expect FAIL
#   3. Wi-Fi card unbound     the proposed fix                     expect PASS
#
# Everything it changes (pm_test, mem_sleep, the binding, NetworkManager's
# hold on wlp3s0) is put back on exit, including after a failure.
set -u
BDF=0000:03:00.0
IFACE=wlp3s0
DRV=/sys/bus/pci/drivers/brcmfmac
P=/sys/power

[[ $EUID -eq 0 ]] || { echo "run with sudo" >&2; exit 1; }
[[ -e $DRV/$BDF ]] || { echo "brcmfmac is not bound to $BDF" >&2; exit 1; }
grep -qw devices $P/pm_test || { echo "this kernel has no pm_test=devices" >&2; exit 1; }
grep -qw s2idle $P/mem_sleep || { echo "this kernel offers no s2idle" >&2; exit 1; }
selected() { sed -n 's/.*\[\([^]]*\)\].*/\1/p' "$1"; }
[[ $(selected $P/pm_test) == none ]] || { echo "pm_test is already set; inspect it first" >&2; exit 1; }

orig_mem=$(selected $P/mem_sleep)
restore() {
    echo none > $P/pm_test 2>/dev/null
    echo "$orig_mem" > $P/mem_sleep 2>/dev/null
    [[ -e $DRV/$BDF ]] || echo "$BDF" > $DRV/bind 2>/dev/null
    ip link set "$IFACE" up 2>/dev/null
    nmcli device set "$IFACE" managed yes 2>/dev/null
}
trap restore EXIT

declare -A RESULT
run() {   # $1 = label
    local marker="wifi-d3-test: $1 $$-$RANDOM"
    echo "$marker" > /dev/kmsg
    echo s2idle > $P/mem_sleep
    echo devices > $P/pm_test || { echo "could not select pm_test=devices" >&2; exit 1; }
    if echo mem > $P/state 2>/dev/null; then RESULT[$1]=PASS; else RESULT[$1]=FAIL; fi
    echo none > $P/pm_test
    echo "== $1: ${RESULT[$1]}"
    dmesg --color=never | awk -v m="$marker" 'index($0, m) { on = 1 } on' \
        | grep -E 'brcmf|Some devices failed|failed to suspend' || echo "   (no brcmfmac errors)"
}

run 1-wifi-up

nmcli device set "$IFACE" managed no
ip link set "$IFACE" down
run 2-wifi-down
ip link set "$IFACE" up
nmcli device set "$IFACE" managed yes

echo "$BDF" > $DRV/unbind
run 3-wifi-unbound
echo "$BDF" > $DRV/bind
for _ in $(seq 30); do [[ -e /sys/class/net/$IFACE ]] && break; sleep 0.5; done

echo
echo "Summary (expected: up PASS, down FAIL, unbound PASS)"
for k in 1-wifi-up 2-wifi-down 3-wifi-unbound; do printf '  %-16s %s\n' "$k" "${RESULT[$k]:-not run}"; done
if [[ -e /sys/class/net/$IFACE ]]; then echo "  $IFACE is back after the rebind"
else echo "  $IFACE did not come back; check journalctl -k"; fi
