"""Suspend module: suspend.target unmasked, the hibernate family masked, the
Thunderbolt sleep hook and the s2idle systemd drop-in installed, the retired
idle=poll cleaned up, on the iMac18,3 the USB controller fix built through DKMS
and loaded at boot, and on Omarchy the hibernation setup removed with
omarchy-hibernation-remove.

The Omarchy module is exercised with stubbed systemctl/sudo/boot helpers and a
stubbed omarchy-hibernation-remove; the Fedora override with a stubbed grubby.
Nothing touches the host.
"""
import configparser
import shlex
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

from test_patcher_menu import shell_function

ROOT = Path(__file__).resolve().parents[1]
PATCHER = (ROOT / "scripts/imac-patcher").read_text()
FEDORA = (ROOT / "scripts/lib/fedora.sh").read_text()
HOOK = ROOT / "scripts/imac-tb-sleep-hook"
SLEEP_CONF = ROOT / "configs/imac5k-s2idle.conf"

# File paths are set per test, so no real path can leak into a run.
CONSTS = "\n".join(line for line in PATCHER.splitlines()
                   if re.match(r"^(HIBERNATE_TARGETS|NO_CSTATES_PARAM|XHCI_FIX_(DKMS|VERSION|MODULE)|T2_(BRIDGE_ID|DRIVER))=", line))
XHCI_START = "# ── suspend: the iMac18,3 USB controller fix (DKMS) ──"


def xhci_helpers():
    """The shared USB-controller-fix and T2 helpers (some are subshell functions)."""
    start = PATCHER.index(XHCI_START)
    return PATCHER[start:PATCHER.index("\nmod_suspend_apply() {", start)]


# The helpers every backend shares; the Fedora override calls them too.
SHARED = "\n".join(shell_function(PATCHER, name) for name in (
    "suspend_systemd_ok", "suspend_uses_s2idle", "suspend_sleep_mode_ok",
    "suspend_install_sleep_files", "suspend_remove_sleep_files")) + "\n" + xhci_helpers()

UNMASK_SUSPEND = "SYSTEMCTL unmask suspend.target"
MASK_HIBERNATE = ("SYSTEMCTL mask hibernate.target"
                  " hybrid-sleep.target suspend-then-hibernate.target")
UNMASK_ALL = ("SYSTEMCTL unmask suspend.target hibernate.target"
              " hybrid-sleep.target suspend-then-hibernate.target")

# suspend.target open, the hibernate family masked.
TARGETS_APPLIED = '''
systemctl() {
    case "$2" in
        suspend.target) echo static ;;
        *) echo masked ;;
    esac
}
'''
TB_HOOK_INSTALLED = 'install -m755 /dev/null "$TB_SLEEP_HOOK"\n'
HOOK_INSTALLED = TB_HOOK_INSTALLED + 'install -m755 /dev/null "$WIFI_SLEEP_HOOK"\n'
DROP_IN_INSTALLED = 'install -D -m644 "$SCRIPT_DIR/../configs/imac5k-s2idle.conf" "$SLEEP_CONF_DROPIN"\n'


def omarchy_module():
    start = PATCHER.index("# ═══════════════════════ module: suspend ")
    end = PATCHER.index("# ═══════════════════════ module: boot ", start)
    return PATCHER[start:end]


def fedora_module():
    start = FEDORA.index("mod_suspend_tier()")
    end = FEDORA.index("mod_audio_apply()", start)
    return FEDORA[start:end]


STUBS = r'''
set -uo pipefail
say() { printf '%s\n' "$*"; }
warn() { printf '%s\n' "$*"; }
# SYSTEMD_VERSION lets a test play an older systemd.
systemctl() {
    if [[ ${1:-} == --version ]]; then echo "systemd ${SYSTEMD_VERSION:-261} (${SYSTEMD_VERSION:-261}-test)"
    else printf 'SYSTEMCTL %s\n' "$*"; fi
}
# Mirror the real helper: the parameter can sit in either file.
boot_config_has() { grep -qs -- "$1" "$LIMINE_DEFAULT" "$LIMINE_DROPIN_DIR"/*.conf; }
sync_boot_files() { printf 'SYNC_BOOT\n'; }
verify_cmdline() { printf 'VERIFY present=%s absent=%s\n' "${1:-}" "${2:-}"; }
sudo() { "$@"; }
'''

# The USB controller fix against fakes only: DKMS state, the module tree and
# /sys/module live under $FAKE, so the host's real module never leaks in.
# PRODUCT picks the model (default: one the fix does not apply to).
XHCI_STUBS = r'''
KREL=7.2.3-test
imac_xhci_fix_supported() { [[ ${PRODUCT:-iMac17,1} == iMac18,3 ]]; }
imac_has_t2() { [[ ${PRODUCT:-iMac17,1} == @(iMacPro1,1|iMac20,1|iMac20,2) ]]; }
imac_kernel_uses_clang() { return 1; }
imac_tool_package() { echo "$1"; }
imac_kernel_headers_package() { echo linux-headers; }
confirm() { return 0; }
gcc() { :; }
make() { :; }
depmod() { :; }
pacman() { printf 'PACMAN %s\n' "$*"; }
mokutil() {
    case $1 in
        --sb-state) echo "${SB_STATE:-SecureBoot disabled}" ;;
        --test-key) printf 'MOK-TEST\n'; [[ ${MOK_ENROLLED:-1} == 1 ]] ;;
    esac
}
dkms() {
    local cmd=$1 kernel='' arg
    shift
    printf 'DKMS %s %s\n' "$cmd" "$*" >> "$FAKE/calls"
    for arg in "$@"; do [[ ${prev:-} == -k ]] && kernel=$arg; prev=$arg; done
    unset prev
    case $cmd in
        status)
            [[ -f $FAKE/dkms-status ]] || return 0
            if [[ -n $kernel ]]; then grep -F ", $kernel, " "$FAKE/dkms-status" || true
            else cat "$FAKE/dkms-status"; fi ;;
        add) ls "$1" > "$FAKE/staged"; echo "imac5k-xhci-d0/1: added" >> "$FAKE/dkms-status" ;;
        build) [[ ${FAIL_DKMS_BUILD:-0} == 0 ]] ;;
        install)
            echo "imac5k-xhci-d0/1, $kernel, x86_64: installed" >> "$FAKE/dkms-status"
            mkdir -p "$XHCI_FIX_MODULES_DIR/$kernel/updates/dkms"
            touch "$XHCI_FIX_MODULES_DIR/$kernel/updates/dkms/imac5k_xhci_d0.ko.zst" ;;
        remove) rm -f "$FAKE/dkms-status"; rm -rf "$XHCI_FIX_MODULES_DIR"/*/updates ;;
    esac
}
modinfo() {
    local kernel='' field=n
    while (($#)); do
        case $1 in -k) kernel=$2; shift 2 ;; -n) field=n; shift ;; -F) field=$2; shift 2 ;; *) shift ;; esac
    done
    local path="$XHCI_FIX_MODULES_DIR/$kernel/updates/dkms/imac5k_xhci_d0.ko.zst"
    [[ -f $path ]] || return 1
    if [[ $field == n ]]; then echo "$path"; else echo SRCVERSION1; fi
}
modprobe() {
    printf 'MODPROBE %s\n' "$*"
    if [[ $1 == -r ]]; then rm -rf "$XHCI_FIX_SYSFS"; return 0; fi
    [[ ${FAIL_MODPROBE:-0} == 0 ]] || return 1
    mkdir -p "$XHCI_FIX_SYSFS/parameters"
    echo Y > "$XHCI_FIX_SYSFS/parameters/acpi_pm_skipped"
    echo SRCVERSION1 > "$XHCI_FIX_SYSFS/srcversion"
}
'''


def xhci_paths(tmp):
    return f'''
FAKE={tmp}/fake
XHCI_FIX_SRC={ROOT}/modules/imac5k-xhci-d0
XHCI_FIX_LOAD_CONF={tmp}/modules-load.d/imac5k-xhci-d0.conf
XHCI_FIX_SYSFS={tmp}/sys-module/imac5k_xhci_d0
XHCI_FIX_MODULES_DIR={tmp}/lib-modules
CACHE={tmp}/cache
T2_PCI_DIR={tmp}/pci
T2_UNLOAD_HOOK_DIRS=({tmp}/etc-system-sleep {tmp}/etc-systemd-system)
mkdir -p "$FAKE" "$XHCI_FIX_MODULES_DIR/7.2.3-test/build" "$T2_PCI_DIR" "${{T2_UNLOAD_HOOK_DIRS[@]}}"
touch "$XHCI_FIX_MODULES_DIR/7.2.3-test/build/Module.symvers"
'''


# The fix fully in place for the one kernel with headers.
XHCI_FIX_INSTALLED = '''
echo "imac5k-xhci-d0/1, 7.2.3-test, x86_64: installed" > "$FAKE/dkms-status"
mkdir -p "$XHCI_FIX_MODULES_DIR/7.2.3-test/updates/dkms" "$XHCI_FIX_SYSFS/parameters" "$(dirname "$XHCI_FIX_LOAD_CONF")"
touch "$XHCI_FIX_MODULES_DIR/7.2.3-test/updates/dkms/imac5k_xhci_d0.ko.zst" "$XHCI_FIX_LOAD_CONF"
echo Y > "$XHCI_FIX_SYSFS/parameters/acpi_pm_skipped"
echo SRCVERSION1 > "$XHCI_FIX_SYSFS/srcversion"
'''


class SleepDropInTests(unittest.TestCase):
    def test_the_shipped_drop_in_sets_s2idle(self):
        conf = configparser.ConfigParser()
        conf.read_string(SLEEP_CONF.read_text())
        self.assertEqual(conf["Sleep"]["MemorySleepMode"], "s2idle")

    def test_it_lands_where_systemd_reads_sleep_drop_ins(self):
        # systemd-sleep reads only *.conf files in sleep.conf.d.
        self.assertRegex(PATCHER, r"(?m)^SLEEP_CONF_DROPIN=/etc/systemd/sleep\.conf\.d/[\w.-]+\.conf$")


class OmarchySuspendTests(unittest.TestCase):
    def run_module(self, code, env=""):
        tmp = tempfile.mkdtemp()
        prelude = STUBS + XHCI_STUBS + CONSTS + xhci_paths(tmp) + f'''
LIMINE_DEFAULT={tmp}/limine-default
LIMINE_DROPIN_DIR={tmp}/dropins
NO_CSTATES_DROPIN={tmp}/dropins/imac5k-no-cstates.conf
HIBERNATE_HOOK_CONF={tmp}/omarchy_resume.conf
HIBERNATE_DROPIN={tmp}/dropins/resume.conf
TB_SLEEP_HOOK={tmp}/system-sleep/imac-tb-sleep-hook
WIFI_SLEEP_HOOK={tmp}/system-sleep/imac-wifi-sleep-hook
SLEEP_CONF_DROPIN={tmp}/sleep.conf.d/imac5k-s2idle.conf
SCRIPT_DIR={ROOT}/scripts
mkdir -p "$LIMINE_DROPIN_DIR" "$(dirname "$TB_SLEEP_HOOK")"
touch "$LIMINE_DEFAULT"
{env}
''' + omarchy_module()
        result = subprocess.run(["bash", "-c", prelude + code],
                                text=True, capture_output=True, timeout=10)
        result.tmp = tmp
        return result

    def test_suspend_open_and_hibernate_masked_detects_applied(self):
        result = self.run_module(
            "mod_suspend_detect", env=TARGETS_APPLIED + HOOK_INSTALLED + DROP_IN_INSTALLED)
        self.assertEqual(result.stdout.strip(), "applied", result.stderr)

    def test_missing_drop_in_detects_partial(self):
        # Targets right and the hook installed, but without the drop-in suspend
        # enters the kernel's default mode, deep S3, and resets on wake.
        result = self.run_module("mod_suspend_detect", env=TARGETS_APPLIED + HOOK_INSTALLED)
        self.assertEqual(result.stdout.strip(), "partial", result.stderr)

    def test_missing_hook_detects_partial(self):
        result = self.run_module("mod_suspend_detect", env=TARGETS_APPLIED + DROP_IN_INSTALLED)
        self.assertEqual(result.stdout.strip(), "partial", result.stderr)

    def test_drop_in_alone_detects_partial(self):
        # The module's own file is left over, so not "not-applied".
        result = self.run_module(
            "mod_suspend_detect", env='systemctl() { echo static; }\n' + DROP_IN_INSTALLED)
        self.assertEqual(result.stdout.strip(), "partial", result.stderr)

    def test_all_four_masked_detects_partial(self):
        # The old block-everything state: suspend must be unmasked too.
        result = self.run_module(
            "mod_suspend_detect",
            env='systemctl() { echo masked; }\n')
        self.assertEqual(result.stdout.strip(), "partial", result.stderr)

    def test_stale_idle_poll_dropin_detects_partial(self):
        # All four targets masked, but the retired drop-in is still there.
        result = self.run_module(
            "mod_suspend_detect",
            env='''
systemctl() { echo masked; }
printf 'KERNEL_CMDLINE[default]+=" idle=poll"\n' > "$NO_CSTATES_DROPIN"
''')
        self.assertEqual(result.stdout.strip(), "partial", result.stderr)

    def test_stale_idle_poll_in_limine_default_detects_partial(self):
        result = self.run_module(
            "mod_suspend_detect",
            env='''
systemctl() { echo masked; }
printf 'KERNEL_CMDLINE[default]="quiet idle=poll"\n' > "$LIMINE_DEFAULT"
''')
        self.assertEqual(result.stdout.strip(), "partial", result.stderr)

    def test_some_masked_detects_partial(self):
        result = self.run_module(
            "mod_suspend_detect",
            env='''
systemctl() {
    case "$2" in
        hibernate.target) echo static ;;
        *) echo masked ;;
    esac
}
''')
        self.assertEqual(result.stdout.strip(), "partial", result.stderr)

    def test_untouched_system_detects_not_applied(self):
        result = self.run_module(
            "mod_suspend_detect",
            env='systemctl() { echo static; }\n')
        self.assertEqual(result.stdout.strip(), "not-applied", result.stderr)

    def test_apply_unmasks_suspend_and_masks_hibernate(self):
        result = self.run_module("mod_suspend_apply")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(UNMASK_SUSPEND, result.stdout)
        self.assertIn(MASK_HIBERNATE, result.stdout)
        # A clean system needs no boot-config change at all.
        self.assertNotIn("SYNC_BOOT", result.stdout)
        tmp = Path(result.tmp)
        self.assertEqual((tmp / "system-sleep/imac-tb-sleep-hook").read_text(), HOOK.read_text())
        self.assertEqual((tmp / "sleep.conf.d/imac5k-s2idle.conf").read_text(), SLEEP_CONF.read_text())

    def test_apply_refuses_before_systemd_256(self):
        # Older systemd ignores MemorySleepMode= and would suspend into deep
        # S3: stop before unmasking anything.
        result = self.run_module("mod_suspend_apply", env="SYSTEMD_VERSION=255\n")
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("systemd 256", result.stdout)
        self.assertNotIn(UNMASK_SUSPEND, result.stdout)
        self.assertFalse((Path(result.tmp) / "sleep.conf.d/imac5k-s2idle.conf").exists())

    def test_apply_stops_when_the_idle_poll_rebuild_fails(self):
        # A failed rebuild or verification must fail the apply rather than
        # end in "reboot to restore idle C-states".
        result = self.run_module(
            "mod_suspend_apply",
            env='printf \'KERNEL_CMDLINE[default]+=" idle=poll"\\n\' > "$NO_CSTATES_DROPIN"\n'
                'verify_cmdline() { echo VERIFY-FAILED; return 1; }\n')
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("VERIFY-FAILED", result.stdout)
        self.assertNotIn("reboot", result.stdout)

    def test_remove_deletes_the_hook_and_the_drop_in(self):
        result = self.run_module(HOOK_INSTALLED + DROP_IN_INSTALLED + "mod_suspend_remove\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(UNMASK_ALL, result.stdout)
        self.assertNotIn("SYNC_BOOT", result.stdout)
        tmp = Path(result.tmp)
        self.assertFalse((tmp / "system-sleep/imac-tb-sleep-hook").exists())
        self.assertFalse((tmp / "sleep.conf.d/imac5k-s2idle.conf").exists())

    def test_apply_cleans_stale_dropin_and_rebuilds(self):
        result = self.run_module('''
printf 'KERNEL_CMDLINE[default]+=" idle=poll"\n' > "$NO_CSTATES_DROPIN"
mod_suspend_apply
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(UNMASK_SUSPEND, result.stdout)
        self.assertIn(MASK_HIBERNATE, result.stdout)
        self.assertFalse((Path(result.tmp) / "dropins/imac5k-no-cstates.conf").exists())
        self.assertIn("SYNC_BOOT", result.stdout)
        self.assertIn("VERIFY present= absent=idle=poll", result.stdout)

    def test_apply_strips_idle_poll_from_limine_default(self):
        result = self.run_module('''
printf 'KERNEL_CMDLINE[default]="quiet idle=poll"\n' > "$LIMINE_DEFAULT"
mod_suspend_apply
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        default = (Path(result.tmp) / "limine-default").read_text()
        self.assertNotIn("idle=poll", default)
        self.assertTrue(list(Path(result.tmp).glob("limine-default.backup-cstates-*")))
        self.assertIn("SYNC_BOOT", result.stdout)

    def test_remove_unmasks_all_four_and_cleans_stale_dropin(self):
        result = self.run_module('''
printf 'KERNEL_CMDLINE[default]+=" idle=poll"\n' > "$NO_CSTATES_DROPIN"
mod_suspend_remove
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(UNMASK_ALL, result.stdout)
        self.assertFalse((Path(result.tmp) / "dropins/imac5k-no-cstates.conf").exists())
        self.assertIn("SYNC_BOOT", result.stdout)

    def test_remove_without_stale_config_touches_no_boot_files(self):
        result = self.run_module("mod_suspend_remove")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(UNMASK_ALL, result.stdout)
        self.assertNotIn("SYNC_BOOT", result.stdout)

    def test_tier_safe_on_clean_system(self):
        result = self.run_module("mod_suspend_tier")
        self.assertEqual(result.stdout.strip(), "safe", result.stderr)

    def test_tier_boot_while_stale_dropin_remains(self):
        result = self.run_module(
            "mod_suspend_tier",
            env='printf \'KERNEL_CMDLINE[default]+=" idle=poll"\n\' > "$NO_CSTATES_DROPIN"\n')
        self.assertEqual(result.stdout.strip(), "boot", result.stderr)

    def test_tier_boot_while_stale_limine_default_remains(self):
        result = self.run_module(
            "mod_suspend_tier",
            env='printf \'KERNEL_CMDLINE[default]="quiet idle=poll"\n\' > "$LIMINE_DEFAULT"\n')
        self.assertEqual(result.stdout.strip(), "boot", result.stderr)

    def test_hibernation_hook_conf_detects_partial_when_masked(self):
        result = self.run_module(
            "mod_suspend_detect",
            env='''
systemctl() { echo masked; }
printf 'HOOKS+=(resume)\n' > "$HIBERNATE_HOOK_CONF"
''')
        self.assertEqual(result.stdout.strip(), "partial", result.stderr)

    def test_hibernation_dropin_alone_detects_partial(self):
        result = self.run_module(
            "mod_suspend_detect",
            env='''
systemctl() { echo masked; }
printf 'KERNEL_CMDLINE[default]+=" resume=/dev/mapper/root resume_offset=1"\n' > "$HIBERNATE_DROPIN"
''')
        self.assertEqual(result.stdout.strip(), "partial", result.stderr)

    def test_hibernation_setup_alone_detects_partial(self):
        # Hibernation configured but nothing masked yet: still not "not-applied".
        result = self.run_module(
            "mod_suspend_detect",
            env='''
systemctl() { echo static; }
printf 'HOOKS+=(resume)\n' > "$HIBERNATE_HOOK_CONF"
''')
        self.assertEqual(result.stdout.strip(), "partial", result.stderr)

    def test_tier_boot_while_hibernation_setup_remains(self):
        result = self.run_module(
            "mod_suspend_tier",
            env='printf \'HOOKS+=(resume)\n\' > "$HIBERNATE_HOOK_CONF"\n')
        self.assertEqual(result.stdout.strip(), "boot", result.stderr)

    def test_apply_removes_hibernation_and_the_leftover_dropin(self):
        result = self.run_module('''
printf 'HOOKS+=(resume)\n' > "$HIBERNATE_HOOK_CONF"
printf 'KERNEL_CMDLINE[default]+=" resume=/dev/mapper/root resume_offset=1"\n' > "$HIBERNATE_DROPIN"
omarchy-hibernation-remove() { rm -f "$HIBERNATE_HOOK_CONF"; echo OMARCHY-HIBERNATION-REMOVE; }
mod_suspend_apply
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(UNMASK_SUSPEND, result.stdout)
        self.assertIn(MASK_HIBERNATE, result.stdout)
        self.assertIn("OMARCHY-HIBERNATION-REMOVE", result.stdout)
        # Omarchy's tool leaves the resume= drop-in; the module removes it and
        # rebuilds so the parameter leaves the cmdline too.
        self.assertFalse((Path(result.tmp) / "dropins/resume.conf").exists())
        self.assertIn("SYNC_BOOT", result.stdout)
        self.assertIn("VERIFY present= absent=resume=", result.stdout)

    def test_apply_declined_hibernation_removal_keeps_everything(self):
        # Omarchy's tool exits 0 without touching anything when its gum
        # confirm is declined; the module must leave the setup alone.
        result = self.run_module('''
printf 'HOOKS+=(resume)\n' > "$HIBERNATE_HOOK_CONF"
printf 'KERNEL_CMDLINE[default]+=" resume=/dev/mapper/root resume_offset=1"\n' > "$HIBERNATE_DROPIN"
omarchy-hibernation-remove() { echo DECLINED; }
mod_suspend_apply
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(UNMASK_SUSPEND, result.stdout)
        self.assertIn(MASK_HIBERNATE, result.stdout)
        self.assertTrue((Path(result.tmp) / "omarchy_resume.conf").exists())
        self.assertTrue((Path(result.tmp) / "dropins/resume.conf").exists())
        self.assertNotIn("SYNC_BOOT", result.stdout)

    def test_apply_without_hibernation_never_calls_the_tool(self):
        result = self.run_module('''
omarchy-hibernation-remove() { echo SHOULD-NOT-RUN; }
mod_suspend_apply
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(UNMASK_SUSPEND, result.stdout)
        self.assertIn(MASK_HIBERNATE, result.stdout)
        self.assertNotIn("SHOULD-NOT-RUN", result.stdout)
        self.assertNotIn("SYNC_BOOT", result.stdout)

    def test_apply_removes_a_leftover_dropin_without_omarchys_tool(self):
        # Omarchy's remover leaves resume.conf behind. With the hook conf gone
        # there is nothing for that tool to do and no swapfile to warn about.
        result = self.run_module('''
printf 'KERNEL_CMDLINE[default]+=" resume=/dev/mapper/root resume_offset=1"\n' > "$HIBERNATE_DROPIN"
omarchy-hibernation-remove() { echo SHOULD-NOT-RUN; }
mod_suspend_apply
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("SHOULD-NOT-RUN", result.stdout)
        self.assertNotIn("swapfile", result.stdout)
        self.assertFalse((Path(result.tmp) / "dropins/resume.conf").exists())
        self.assertIn("SYNC_BOOT", result.stdout)
        self.assertIn("VERIFY present= absent=resume=", result.stdout)


class StartupAuditTests(unittest.TestCase):
    def test_the_hibernation_remover_is_never_sent_to_the_package_manager(self):
        # It ships inside the omarchy package: asking pacman for it by name
        # fails the whole prerequisite install ("target not found").
        code = shell_function(PATCHER, "startup_deps_note") + '''
declare -A MODULE_STATES=([suspend]=partial)
MODULES=(suspend)
imac_is_fedora() { return 1; }
imac_is_kde() { return 1; }
imac_is_arch_grub() { return 1; }
hibernation_setup_present() { return 0; }
PATH=/nonexistent
startup_deps_note
echo "MISSING=${STARTUP_MISSING_TOOLS[*]}"
'''
        result = subprocess.run(["bash", "-c", code], text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("MISSING=systemctl", result.stdout)
        self.assertNotIn("omarchy-hibernation-remove", result.stdout)


class FedoraSuspendTests(unittest.TestCase):
    def run_module(self, code, grubby_has_arg=False):
        arg_line = 'echo \'args="idle=poll"\'' if grubby_has_arg else ':'
        tmp = tempfile.mkdtemp()
        prelude = STUBS + XHCI_STUBS + CONSTS + xhci_paths(tmp) + f'''
TB_SLEEP_HOOK={tmp}/system-sleep/imac-tb-sleep-hook
WIFI_SLEEP_HOOK={tmp}/system-sleep/imac-wifi-sleep-hook
SLEEP_CONF_DROPIN={tmp}/sleep.conf.d/imac5k-s2idle.conf
SCRIPT_DIR={ROOT}/scripts
mkdir -p "$(dirname "$TB_SLEEP_HOOK")"
fedora_mutable() {{ return 0; }}
fedora_deps() {{ printf 'FEDORA_DEPS %s\n' "$*"; }}
unset -f boot_config_has sync_boot_files verify_cmdline
grubby() {{
    if [[ $1 == --info ]]; then {arg_line}; else printf 'GRUBBY %s\n' "$*"; fi
}}
''' + SHARED + "\n" + fedora_module()
        result = subprocess.run(["bash", "-c", prelude + code],
                                text=True, capture_output=True, timeout=10)
        result.tmp = tmp
        return result

    def test_suspend_open_and_hibernate_masked_detects_applied(self):
        result = self.run_module(
            TARGETS_APPLIED + HOOK_INSTALLED + DROP_IN_INSTALLED + "mod_suspend_detect")
        self.assertEqual(result.stdout.strip(), "applied", result.stderr)

    def test_missing_drop_in_detects_partial(self):
        result = self.run_module(TARGETS_APPLIED + HOOK_INSTALLED + "mod_suspend_detect")
        self.assertEqual(result.stdout.strip(), "partial", result.stderr)

    def test_all_four_masked_detects_partial(self):
        result = self.run_module(
            "systemctl() { echo masked; }; mod_suspend_detect")
        self.assertEqual(result.stdout.strip(), "partial", result.stderr)

    def test_stale_idle_poll_arg_detects_partial(self):
        result = self.run_module(
            "systemctl() { echo masked; }; mod_suspend_detect",
            grubby_has_arg=True)
        self.assertEqual(result.stdout.strip(), "partial", result.stderr)

    def test_apply_installs_the_sleep_files_without_touching_grub(self):
        result = self.run_module("mod_suspend_apply")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(UNMASK_SUSPEND, result.stdout)
        self.assertIn(MASK_HIBERNATE, result.stdout)
        self.assertNotIn("--update-kernel", result.stdout)
        tmp = Path(result.tmp)
        self.assertTrue((tmp / "system-sleep/imac-tb-sleep-hook").exists())
        self.assertEqual((tmp / "sleep.conf.d/imac5k-s2idle.conf").read_text(), SLEEP_CONF.read_text())

    def test_apply_refuses_before_systemd_256(self):
        result = self.run_module("SYSTEMD_VERSION=255\nmod_suspend_apply")
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertNotIn(UNMASK_SUSPEND, result.stdout)

    def test_apply_removes_stale_idle_poll_arg(self):
        result = self.run_module("mod_suspend_apply", grubby_has_arg=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(UNMASK_SUSPEND, result.stdout)
        self.assertIn(MASK_HIBERNATE, result.stdout)
        self.assertIn("GRUBBY --update-kernel /boot/vmlinuz-7.2.3-test --remove-args idle=poll",
                      result.stdout)
        self.assertNotIn("--args idle=poll", result.stdout)

    def test_apply_fails_when_grubby_fails(self):
        result = self.run_module('''
grubby() {
    if [[ $1 == --info ]]; then echo 'args="idle=poll"'; else printf 'GRUBBY %s\\n' "$*"; return 1; fi
}
mod_suspend_apply''')
        self.assertNotEqual(result.returncode, 0, result.stdout)

    def test_remove_unmasks_all_four_and_removes_stale_arg(self):
        result = self.run_module("mod_suspend_remove", grubby_has_arg=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(UNMASK_ALL, result.stdout)
        self.assertIn("GRUBBY --update-kernel /boot/vmlinuz-7.2.3-test --remove-args idle=poll",
                      result.stdout)

    def test_remove_deletes_the_sleep_files(self):
        result = self.run_module(HOOK_INSTALLED + DROP_IN_INSTALLED + "mod_suspend_remove")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(UNMASK_ALL, result.stdout)
        tmp = Path(result.tmp)
        self.assertFalse((tmp / "system-sleep/imac-tb-sleep-hook").exists())
        self.assertFalse((tmp / "sleep.conf.d/imac5k-s2idle.conf").exists())

    def test_remove_fails_when_grubby_fails(self):
        result = self.run_module('''
grubby() {
    if [[ $1 == --info ]]; then echo 'args="idle=poll"'; else printf 'GRUBBY %s\\n' "$*"; return 1; fi
}
mod_suspend_remove''')
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertNotIn("back to stock", result.stdout)

    def test_tier_safe_on_clean_system(self):
        result = self.run_module("mod_suspend_tier")
        self.assertEqual(result.stdout.strip(), "safe", result.stderr)

    def test_tier_boot_while_stale_grub_arg_remains(self):
        result = self.run_module("mod_suspend_tier", grubby_has_arg=True)
        self.assertEqual(result.stdout.strip(), "boot", result.stderr)


class XhciFixTests(unittest.TestCase):
    """iMac18,3: Apple's XHC1._PS3 resets the machine on every second sleep.

    The suspend module builds the imac5k-xhci-d0 DKMS module, loads it at
    boot through modules-load.d and at once, and reports applied only while it
    is built for the kernels and holding the controller. Other models are
    left alone. Both backends are exercised against the same fakes.
    """
    omarchy = OmarchySuspendTests.run_module
    fedora = FedoraSuspendTests.run_module

    def backends(self):
        return (("omarchy", lambda code, env="": self.omarchy(code, env=env)),
                ("fedora", lambda code, env="": self.fedora(env + code)))

    @staticmethod
    def calls(result):
        path = Path(result.tmp) / "fake/calls"
        return path.read_text() if path.exists() else ""

    def test_imac18_3_needs_the_fix_for_applied(self):
        for name, run in self.backends():
            with self.subTest(backend=name):
                everything_else = TARGETS_APPLIED + HOOK_INSTALLED + DROP_IN_INSTALLED
                result = run("mod_suspend_detect", env="PRODUCT=iMac18,3\n" + everything_else)
                self.assertEqual(result.stdout.strip(), "partial", result.stderr)
                result = run("mod_suspend_detect", env="PRODUCT=iMac18,3\n" + everything_else + XHCI_FIX_INSTALLED)
                self.assertEqual(result.stdout.strip(), "applied", result.stderr)

    def test_other_models_do_not_need_it(self):
        for name, run in self.backends():
            with self.subTest(backend=name):
                result = run("mod_suspend_detect", env=TARGETS_APPLIED + HOOK_INSTALLED + DROP_IN_INSTALLED)
                self.assertEqual(result.stdout.strip(), "applied", result.stderr)
                result = run("mod_suspend_apply")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertNotRegex(self.calls(result), r"DKMS (add|build|install|remove)")
                self.assertNotIn("MODPROBE", result.stdout)

    def test_an_installed_but_unloaded_or_stale_build_is_partial(self):
        everything = "PRODUCT=iMac18,3\n" + TARGETS_APPLIED + HOOK_INSTALLED + DROP_IN_INSTALLED + XHCI_FIX_INSTALLED
        cases = {
            "not loaded": 'rm -rf "$XHCI_FIX_SYSFS"\n',
            "old test build without the parameter": 'rm -f "$XHCI_FIX_SYSFS/parameters/acpi_pm_skipped"\n',
            "different build in memory": 'echo OLDSRC > "$XHCI_FIX_SYSFS/srcversion"\n',
            "no boot load": 'rm -f "$XHCI_FIX_LOAD_CONF"\n',
            "not built for this kernel": 'rm -f "$FAKE/dkms-status"\n',
        }
        for name, run in self.backends():
            for case, change in cases.items():
                with self.subTest(backend=name, case=case):
                    result = run("mod_suspend_detect", env=everything + change)
                    self.assertEqual(result.stdout.strip(), "partial", result.stderr)

    def test_a_leftover_on_another_model_is_partial_and_apply_clears_it(self):
        # A modules-load entry the model does not need would fail at every boot.
        leftover = TARGETS_APPLIED + HOOK_INSTALLED + DROP_IN_INSTALLED + XHCI_FIX_INSTALLED
        for name, run in self.backends():
            with self.subTest(backend=name):
                result = run("mod_suspend_detect", env=leftover)
                self.assertEqual(result.stdout.strip(), "partial", result.stderr)
                result = run("mod_suspend_apply\n" + TARGETS_APPLIED + "mod_suspend_detect",
                             env=HOOK_INSTALLED + DROP_IN_INSTALLED + XHCI_FIX_INSTALLED)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("DKMS remove imac5k-xhci-d0/1 --all", self.calls(result))
                self.assertEqual(result.stdout.strip().splitlines()[-1], "applied")

    def test_apply_builds_loads_and_enables_it_before_unmasking_suspend(self):
        for name, run in self.backends():
            with self.subTest(backend=name):
                # The stub systemctl only prints; report the masks apply set.
                result = run("mod_suspend_apply\n" + TARGETS_APPLIED + "mod_suspend_detect", env="PRODUCT=iMac18,3\n")
                self.assertEqual(result.returncode, 0, result.stderr)
                calls = self.calls(result)
                self.assertIn("DKMS add", calls)
                self.assertIn("DKMS build -m imac5k-xhci-d0 -v 1 -k 7.2.3-test", calls)
                self.assertIn("DKMS install -m imac5k-xhci-d0 -v 1 -k 7.2.3-test --force", calls)
                # Only the sources are handed to DKMS, never a development build.
                staged = (Path(result.tmp) / "fake/staged").read_text().split()
                self.assertEqual(sorted(staged), ["Makefile", "dkms.conf", "imac5k_xhci_d0.c"])
                conf = (Path(result.tmp) / "modules-load.d/imac5k-xhci-d0.conf").read_text()
                self.assertIn("imac5k_xhci_d0", [line.strip() for line in conf.splitlines()
                                                  if line.strip() and not line.startswith("#")])
                out = result.stdout
                self.assertIn("MODPROBE imac5k_xhci_d0", out)
                self.assertLess(out.index("MODPROBE imac5k_xhci_d0"), out.index(UNMASK_SUSPEND))
                self.assertEqual(out.strip().splitlines()[-1], "applied")

    def test_a_failed_build_leaves_suspend_masked_and_unloaded(self):
        for name, run in self.backends():
            with self.subTest(backend=name):
                result = run("mod_suspend_apply", env="PRODUCT=iMac18,3\nFAIL_DKMS_BUILD=1\n")
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertNotIn(UNMASK_SUSPEND, result.stdout)
                self.assertNotIn("MODPROBE", result.stdout)
                self.assertFalse((Path(result.tmp) / "modules-load.d/imac5k-xhci-d0.conf").exists())

    def test_a_failed_load_stops_before_suspend_is_unmasked(self):
        result = self.omarchy("mod_suspend_apply", env="PRODUCT=iMac18,3\nFAIL_MODPROBE=1\n")
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertNotIn(UNMASK_SUSPEND, result.stdout)

    def test_apply_swaps_a_different_build_already_in_memory(self):
        result = self.omarchy("mod_suspend_apply", env="PRODUCT=iMac18,3\n" + '''
mkdir -p "$XHCI_FIX_SYSFS/parameters"
echo Y > "$XHCI_FIX_SYSFS/parameters/active"
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertLess(result.stdout.index("MODPROBE -r imac5k_xhci_d0"), result.stdout.index("MODPROBE imac5k_xhci_d0"))

    def test_remove_unloads_it_and_removes_every_dkms_version(self):
        for name, run in self.backends():
            with self.subTest(backend=name):
                result = run("mod_suspend_remove\nmod_suspend_detect", env="PRODUCT=iMac18,3\n" + XHCI_FIX_INSTALLED)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("MODPROBE -r imac5k_xhci_d0", result.stdout)
                self.assertIn("DKMS remove imac5k-xhci-d0/1 --all", self.calls(result))
                self.assertFalse((Path(result.tmp) / "modules-load.d/imac5k-xhci-d0.conf").exists())
                self.assertEqual(result.stdout.strip().splitlines()[-1], "not-applied")

    def test_fedora_refuses_to_load_an_unsigned_module_under_secure_boot(self):
        env = "PRODUCT=iMac18,3\nSB_STATE='SecureBoot enabled'\nMOK_ENROLLED=0\n"
        result = self.fedora(env + "mod_suspend_apply")
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("mokutil --import", result.stdout)
        self.assertNotIn("MODPROBE", result.stdout)
        self.assertNotIn(UNMASK_SUSPEND, result.stdout)
        self.assertIn("FEDORA_DEPS dkms kernel-devel-7.2.3-test", result.stdout)
        result = self.fedora("PRODUCT=iMac18,3\nSB_STATE='SecureBoot enabled'\nmod_suspend_apply")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("MODPROBE imac5k_xhci_d0", result.stdout)


def t2_bridge(driver="t2bce_core"):
    """A fake T2 (bridge plus audio function), the bridge bound to driver.

    driver=None leaves the bridge unbound.
    """
    code = (
        'mkdir -p "$T2_PCI_DIR/0000:03:00.0" "$T2_PCI_DIR/0000:03:00.1"\n'
        'echo 0x106b > "$T2_PCI_DIR/0000:03:00.1/vendor"; echo 0x1801 > "$T2_PCI_DIR/0000:03:00.1/device"\n'
        'echo 0x106b > "$T2_PCI_DIR/0000:03:00.0/vendor"; echo 0x1803 > "$T2_PCI_DIR/0000:03:00.0/device"\n'
    )
    if driver:
        code += (f'mkdir -p "$FAKE/drivers/{driver}"\n'
                 f'ln -s "$FAKE/drivers/{driver}" "$T2_PCI_DIR/0000:03:00.1/driver"\n')
    return code


def write_file(rel, body):
    """Shell that writes body to rel, a path under the test's temporary root."""
    return f'printf %s {shlex.quote(body)} > "$(dirname "$FAKE")/{rel}"\n'


# The older t2linux suspend service that unloads apple-bce around sleep.
OLD_UNLOAD_SERVICE = """[Unit]
Description=Disable and Re-Enable Apple BCE Module
Before=sleep.target
[Service]
Type=oneshot
ExecStart=/usr/bin/rmmod -f apple-bce
ExecStop=/usr/bin/modprobe apple-bce
[Install]
WantedBy=sleep.target
"""
T2_ALL_APPLIED = TARGETS_APPLIED + HOOK_INSTALLED


class T2SuspendTests(unittest.TestCase):
    """T2 models (iMac Pro, 2020 iMacs) follow t2linux's suspend rules.

    linux-t2's t2bce stack suspends the T2 itself, so the module requires it
    bound to the T2 bridge, refuses while anything unloads the T2 driver
    around sleep, and keeps the kernel's sleep mode (no s2idle drop-in).
    Both backends are exercised against the same fakes.
    """
    omarchy = OmarchySuspendTests.run_module
    fedora = FedoraSuspendTests.run_module

    def each(self, models=("iMacPro1,1", "iMac20,1", "iMac20,2")):
        backends = (("omarchy", lambda code, env: self.omarchy(code, env=env)),
                    ("fedora", lambda code, env: self.fedora(env + code)))
        for model in models:
            for name, run in backends:
                with self.subTest(model=model, backend=name):
                    yield model, (lambda code, env="", run=run, model=model:
                                  run(code, f"PRODUCT={model}\n" + env))

    def test_ready_t2_model_is_applied_without_the_s2idle_drop_in(self):
        for _, run in self.each():
            result = run("mod_suspend_detect", env=t2_bridge() + T2_ALL_APPLIED)
            self.assertEqual(result.stdout.strip(), "applied", result.stderr)
            # The drop-in that forces s2idle is a leftover on these models.
            result = run("mod_suspend_detect", env=t2_bridge() + T2_ALL_APPLIED + DROP_IN_INSTALLED)
            self.assertEqual(result.stdout.strip(), "partial", result.stderr)

    def test_apply_keeps_the_kernel_sleep_mode_and_the_hooks(self):
        for _, run in self.each():
            # Older systemd is fine: MemorySleepMode= is not used.
            result = run("mod_suspend_apply\n" + TARGETS_APPLIED + "mod_suspend_detect",
                         env="SYSTEMD_VERSION=255\n" + t2_bridge() + DROP_IN_INSTALLED)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn(UNMASK_SUSPEND, result.stdout)
            self.assertIn(MASK_HIBERNATE, result.stdout)
            tmp = Path(result.tmp)
            self.assertFalse((tmp / "sleep.conf.d/imac5k-s2idle.conf").exists())
            self.assertEqual((tmp / "system-sleep/imac-tb-sleep-hook").read_text(), HOOK.read_text())
            self.assertTrue((tmp / "system-sleep/imac-wifi-sleep-hook").exists())
            self.assertEqual(result.stdout.strip().splitlines()[-1], "applied")

    def test_apply_refuses_without_t2bce_before_changing_anything(self):
        cases = {
            "apple-bce": (t2_bridge("apple-bce"), "driven by apple-bce"),
            "unbound": (t2_bridge(None), "driven by no driver"),
            "no bridge": ("", "no Apple T2 bridge"),
        }
        for _, run in self.each():
            for case, (env, message) in cases.items():
                with self.subTest(case=case):
                    result = run("mod_suspend_apply", env=env)
                    self.assertNotEqual(result.returncode, 0, result.stdout)
                    self.assertIn(message, result.stdout)
                    self.assertNotIn("SYSTEMCTL", result.stdout)
                    self.assertFalse((Path(result.tmp) / "system-sleep/imac-tb-sleep-hook").exists())
                    result = run("mod_suspend_detect", env=env + T2_ALL_APPLIED)
                    self.assertEqual(result.stdout.strip(), "partial", result.stderr)

    def test_apply_refuses_while_something_unloads_the_t2_driver(self):
        hooks = {
            "old service": ("etc-systemd-system/suspend-fix-t2.service", OLD_UNLOAD_SERVICE),
            "sleep hook": ("etc-system-sleep/t2-sleep",
                           '#!/bin/sh\n[ "$1" = pre ] && modprobe -rv t2bce_vhci t2bce_core\n'),
        }
        for _, run in self.each(("iMacPro1,1",)):
            for case, (rel, body) in hooks.items():
                with self.subTest(case=case):
                    env = t2_bridge() + write_file(rel, body)
                    result = run("mod_suspend_apply", env=env)
                    self.assertNotEqual(result.returncode, 0, result.stdout)
                    self.assertIn("unloads the T2 driver", result.stdout)
                    self.assertIn(rel, result.stdout)
                    self.assertNotIn("SYSTEMCTL", result.stdout)
                    result = run("mod_suspend_detect", env=env + T2_ALL_APPLIED)
                    self.assertEqual(result.stdout.strip(), "partial", result.stderr)

    def test_files_that_only_load_or_mention_the_driver_are_not_unload_hooks(self):
        body = "#!/bin/sh\nmodprobe apple-bce\n# t2bce stays loaded; see rmmod-free notes\n"
        for _, run in self.each(("iMacPro1,1",)):
            result = run("mod_suspend_apply", env=t2_bridge() + write_file("etc-system-sleep/load-only", body))
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_other_models_ignore_the_t2_rules(self):
        # No T2 bridge and an old unload service: irrelevant off T2 models,
        # which still get the s2idle drop-in.
        env = write_file("etc-systemd-system/x.service", OLD_UNLOAD_SERVICE)
        for model, run in self.each(("iMac17,1", "iMac18,3", "iMac19,1")):
            fix = XHCI_FIX_INSTALLED if model == "iMac18,3" else ""
            result = run("mod_suspend_detect", env=env + T2_ALL_APPLIED + DROP_IN_INSTALLED + fix)
            self.assertEqual(result.stdout.strip(), "applied", result.stderr)
            result = run("mod_suspend_apply", env=env)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue((Path(result.tmp) / "sleep.conf.d/imac5k-s2idle.conf").exists())


WIFI_HOOK = ROOT / "scripts/imac-wifi-sleep-hook"


class WifiSleepHookWiringTests(unittest.TestCase):
    """Both backends install, require and remove the Wi-Fi sleep hook.

    Installs from before the hook existed report partial until suspend is
    applied again, which is how an upgrade picks it up.
    """
    omarchy = OmarchySuspendTests.run_module
    fedora = FedoraSuspendTests.run_module

    def test_omarchy_requires_installs_and_removes_the_wifi_hook(self):
        result = self.omarchy(
            "mod_suspend_detect", env=TARGETS_APPLIED + TB_HOOK_INSTALLED + DROP_IN_INSTALLED)
        self.assertEqual(result.stdout.strip(), "partial", result.stderr)
        result = self.omarchy("mod_suspend_apply")
        self.assertEqual(result.returncode, 0, result.stderr)
        hook = Path(result.tmp) / "system-sleep/imac-wifi-sleep-hook"
        self.assertEqual(hook.read_text(), WIFI_HOOK.read_text())
        result = self.omarchy(HOOK_INSTALLED + DROP_IN_INSTALLED + "mod_suspend_remove\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((Path(result.tmp) / "system-sleep/imac-wifi-sleep-hook").exists())

    def test_fedora_requires_installs_and_removes_the_wifi_hook(self):
        result = self.fedora(
            TARGETS_APPLIED + TB_HOOK_INSTALLED + DROP_IN_INSTALLED + "mod_suspend_detect")
        self.assertEqual(result.stdout.strip(), "partial", result.stderr)
        result = self.fedora("mod_suspend_apply")
        self.assertEqual(result.returncode, 0, result.stderr)
        hook = Path(result.tmp) / "system-sleep/imac-wifi-sleep-hook"
        self.assertEqual(hook.read_text(), WIFI_HOOK.read_text())
        result = self.fedora(HOOK_INSTALLED + DROP_IN_INSTALLED + "mod_suspend_remove")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((Path(result.tmp) / "system-sleep/imac-wifi-sleep-hook").exists())


if __name__ == "__main__":
    unittest.main()
