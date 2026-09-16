#!/usr/bin/env bash
# Arm or disarm a real-S3 suspend test on Omarchy/Limine.
#
#   sudo bash notes/s3-nonvs-test.sh arm      then reboot
#   sudo bash notes/s3-nonvs-test.sh disarm   then reboot
#
# s2idle resets this iMac on the second sleep of every boot, cause unfound.
# Deep S3 fails differently here: it sleeps properly and resets on wake, which
# is the classic symptom `acpi_sleep=nonvs` addresses. Arming does two things:
#
#   1. adds acpi_sleep=nonvs to the default kernel command line, through the
#      same limine drop-in mechanism the patcher uses, and rebuilds the boot
#      image
#   2. moves the suspend module's MemorySleepMode=s2idle drop-in aside, so
#      systemd stops forcing s2idle and sleeps land in deep S3
#
# After rebooting, test with:  sudo bash notes/s2idle-second-sleep-test.sh 180
# and check the kernel logs say "PM: suspend entry (deep)".
set -uo pipefail
ACTION=${1:-}
DROPIN=/etc/limine-entry-tool.d/zz-imac-s3-test.conf
SLEEPCONF=/etc/systemd/sleep.conf.d/imac5k-s2idle.conf
PARKED=$SLEEPCONF.parked-by-s3-test

[[ $EUID -eq 0 ]] || { echo "run with sudo" >&2; exit 1; }
[[ -f /etc/default/limine ]] || { echo "this script is for the Omarchy/Limine layout" >&2; exit 1; }
command -v limine-mkinitcpio >/dev/null || { echo "limine-mkinitcpio not found" >&2; exit 1; }

case "$ACTION" in
arm)
    mkdir -p "$(dirname "$DROPIN")"
    cat > "$DROPIN" <<'CONF'
# Temporary, written by notes/s3-nonvs-test.sh. Remove with:
#   sudo bash notes/s3-nonvs-test.sh disarm
KERNEL_CMDLINE[default]+=" acpi_sleep=nonvs"
CONF
    echo "wrote $DROPIN"
    [[ -f $SLEEPCONF ]] && { mv "$SLEEPCONF" "$PARKED"; echo "parked $SLEEPCONF so systemd stops forcing s2idle"; }
    limine-mkinitcpio && echo "boot image rebuilt"
    echo
    echo "Reboot, then confirm:  cat /proc/cmdline   (should contain acpi_sleep=nonvs)"
    echo "                       cat /sys/power/mem_sleep   (deep should be selected)"
    echo "Then:  sudo bash notes/s2idle-second-sleep-test.sh 180"
    ;;
disarm)
    rm -f "$DROPIN" && echo "removed $DROPIN"
    [[ -f $PARKED ]] && { mv "$PARKED" "$SLEEPCONF"; echo "restored $SLEEPCONF"; }
    limine-mkinitcpio && echo "boot image rebuilt"
    echo "Reboot to return to the normal setup."
    ;;
*)
    echo "usage: sudo bash notes/s3-nonvs-test.sh arm|disarm" >&2
    exit 1
    ;;
esac
