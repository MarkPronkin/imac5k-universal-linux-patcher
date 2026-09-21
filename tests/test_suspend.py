"""The two sleep modules.

suspend holds the iMac18,3's fixes: suspend.target unmasked, the hibernate
family masked, the Thunderbolt and Wi-Fi sleep hooks and the s2idle systemd
drop-in installed, the retired idle=poll cleaned up, the USB controller fix
built through DKMS and loaded at boot, and on Omarchy the hibernation setup
removed with omarchy-hibernation-remove. On the other non-T2 models it is n/a
and only takes back what an earlier release installed there. t2suspend
follows t2linux on T2 models, with the same sleep policy.

Both backends run: the Omarchy module with stubbed systemctl/sudo/boot helpers
and a stubbed omarchy-hibernation-remove, and the Fedora overrides sourced on
top of it, as the patcher does, with a stubbed grubby. Nothing touches the
host.
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
WIFI_HOOK = ROOT / "scripts/imac-wifi-sleep-hook"
SLEEP_CONF = ROOT / "configs/imac5k-s2idle.conf"

T2_MODELS = ("iMacPro1,1", "iMac20,1", "iMac20,2")
# Non-T2 models the iMac18,3's fixes are not for.
OTHER_MODELS = ("iMac15,1", "iMac17,1", "iMac19,1")
BACKENDS = ("omarchy", "fedora")

# File paths are set per test, so no real path can leak into a run.
CONSTS = "\n".join(line for line in PATCHER.splitlines()
                   if re.match(r"^(HIBERNATE_TARGETS|NO_CSTATES_PARAM|XHCI_FIX_(DKMS|VERSION|MODULE)|T2_(BRIDGE_ID|DRIVER))=", line))


def sleep_modules():
    """Both sleep modules and everything they share, as the patcher has them."""
    start = PATCHER.index("# ═══════════════════════ module: suspend ")
    return PATCHER[start:PATCHER.index("# ═══════════════════════ module: boot ", start)]


def fedora_overrides():
    """What lib/fedora.sh re-points for the sleep modules."""
    start = FEDORA.index("suspend_backend_ok()")
    return FEDORA[start:FEDORA.index("audio_target_kernels()", start)]


UNMASK_SUSPEND = "SYSTEMCTL unmask suspend.target"
MASK_HIBERNATE = ("SYSTEMCTL mask hibernate.target"
                  " hybrid-sleep.target suspend-then-hibernate.target")
UNMASK_ALL = ("SYSTEMCTL unmask suspend.target hibernate.target"
              " hybrid-sleep.target suspend-then-hibernate.target")

# suspend.target open, the hibernate family masked.
TARGETS_APPLIED = 'MASKED="hibernate.target hybrid-sleep.target suspend-then-hibernate.target"\n'
# How releases up to 0.1.9-alpha blocked sleep.
ALL_FOUR_MASKED = 'MASKED="suspend.target hibernate.target hybrid-sleep.target suspend-then-hibernate.target"\n'
TB_HOOK_INSTALLED = 'install -m755 /dev/null "$TB_SLEEP_HOOK"\n'
WIFI_HOOK_INSTALLED = 'install -m755 /dev/null "$WIFI_SLEEP_HOOK"\n'
HOOK_INSTALLED = TB_HOOK_INSTALLED + WIFI_HOOK_INSTALLED
DROP_IN_INSTALLED = 'install -D -m644 "$SCRIPT_DIR/../configs/imac5k-s2idle.conf" "$SLEEP_CONF_DROPIN"\n'
IDLE_POLL_DROPIN = 'printf \'KERNEL_CMDLINE[default]+=" idle=poll"\\n\' > "$NO_CSTATES_DROPIN"\n'
IDLE_POLL_DEFAULT = 'printf \'KERNEL_CMDLINE[default]="quiet idle=poll"\\n\' > "$LIMINE_DEFAULT"\n'
HIBERNATION_HOOK = 'printf \'HOOKS+=(resume)\\n\' > "$HIBERNATE_HOOK_CONF"\n'
HIBERNATION_DROPIN = ('printf \'KERNEL_CMDLINE[default]+=" resume=/dev/mapper/root resume_offset=1"\\n\''
                      ' > "$HIBERNATE_DROPIN"\n')

STUBS = r'''
set -uo pipefail
say() { printf '%s\n' "$*"; }
warn() { printf '%s\n' "$*"; }
# MASKED lists the masked units and mask/unmask keep it current, so detection
# after an apply sees what the apply did. SYSTEMD_VERSION plays an older one.
MASKED=''
systemctl() {
    local unit kept=''
    case ${1:-} in
        --version) echo "systemd ${SYSTEMD_VERSION:-261} (${SYSTEMD_VERSION:-261}-test)" ;;
        is-enabled) if [[ " $MASKED " == *" $2 "* ]]; then echo masked; else echo static; fi ;;
        mask)
            printf 'SYSTEMCTL %s\n' "$*"; shift
            for unit; do [[ " $MASKED " == *" $unit "* ]] || MASKED+=" $unit"; done ;;
        unmask)
            printf 'SYSTEMCTL %s\n' "$*"; shift
            for unit in $MASKED; do [[ " $* " == *" $unit "* ]] || kept+=" $unit"; done
            MASKED=$kept ;;
        *) printf 'SYSTEMCTL %s\n' "$*" ;;
    esac
}
# Mirror the real helper: the parameter can sit in either file.
boot_config_has() { grep -qs -- "$1" "$LIMINE_DEFAULT" "$LIMINE_DROPIN_DIR"/*.conf; }
sync_boot_files() { printf 'SYNC_BOOT\n'; }
verify_cmdline() { printf 'VERIFY present=%s absent=%s\n' "${1:-}" "${2:-}"; }
sudo() { "$@"; }
'''

# The model and the USB controller fix, against fakes only: DKMS state, the
# module tree and /sys/module live under $FAKE, so the host's real module
# never leaks in. PRODUCT picks the model; the default is the iMac18,3.
MODEL_STUBS = r'''
KREL=7.2.3-test
imac_suspend_supported() { [[ ${PRODUCT:-iMac18,3} == iMac18,3 ]]; }
imac_xhci_fix_supported() { [[ ${PRODUCT:-iMac18,3} == iMac18,3 ]]; }
imac_has_t2() { [[ ${PRODUCT:-iMac18,3} == @(iMacPro1,1|iMac20,1|iMac20,2) ]]; }
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


def paths(tmp):
    return f'''
FAKE={tmp}/fake
XHCI_FIX_SRC={ROOT}/modules/imac5k-xhci-d0
XHCI_FIX_LOAD_CONF={tmp}/modules-load.d/imac5k-xhci-d0.conf
XHCI_FIX_SYSFS={tmp}/sys-module/imac5k_xhci_d0
XHCI_FIX_MODULES_DIR={tmp}/lib-modules
CACHE={tmp}/cache
T2_PCI_DIR={tmp}/pci
T2_UNLOAD_HOOK_DIRS=({tmp}/etc-system-sleep {tmp}/etc-systemd-system)
LIMINE_DEFAULT={tmp}/limine-default
LIMINE_DROPIN_DIR={tmp}/dropins
NO_CSTATES_DROPIN={tmp}/dropins/imac5k-no-cstates.conf
HIBERNATE_HOOK_CONF={tmp}/omarchy_resume.conf
HIBERNATE_DROPIN={tmp}/dropins/resume.conf
TB_SLEEP_HOOK={tmp}/system-sleep/imac-tb-sleep-hook
WIFI_SLEEP_HOOK={tmp}/system-sleep/imac-wifi-sleep-hook
SLEEP_CONF_DROPIN={tmp}/sleep.conf.d/imac5k-s2idle.conf
SCRIPT_DIR={ROOT}/scripts
mkdir -p "$FAKE" "$XHCI_FIX_MODULES_DIR/7.2.3-test/build" "$T2_PCI_DIR" "${{T2_UNLOAD_HOOK_DIRS[@]}}" \\
    "$LIMINE_DROPIN_DIR" "$(dirname "$TB_SLEEP_HOOK")"
touch "$XHCI_FIX_MODULES_DIR/7.2.3-test/build/Module.symvers" "$LIMINE_DEFAULT"
'''


# The USB controller fix fully in place for the one kernel with headers.
XHCI_FIX_INSTALLED = '''
echo "imac5k-xhci-d0/1, 7.2.3-test, x86_64: installed" > "$FAKE/dkms-status"
mkdir -p "$XHCI_FIX_MODULES_DIR/7.2.3-test/updates/dkms" "$XHCI_FIX_SYSFS/parameters" "$(dirname "$XHCI_FIX_LOAD_CONF")"
touch "$XHCI_FIX_MODULES_DIR/7.2.3-test/updates/dkms/imac5k_xhci_d0.ko.zst" "$XHCI_FIX_LOAD_CONF"
echo Y > "$XHCI_FIX_SYSFS/parameters/acpi_pm_skipped"
echo SRCVERSION1 > "$XHCI_FIX_SYSFS/srcversion"
'''
# Everything the suspend module sets up on the iMac18,3.
SUSPEND_APPLIED = TARGETS_APPLIED + HOOK_INSTALLED + DROP_IN_INSTALLED + XHCI_FIX_INSTALLED


def fedora_stubs(grubby_has_arg):
    arg_line = 'echo \'args="idle=poll"\'' if grubby_has_arg else ':'
    return f'''
fedora_mutable() {{ return 0; }}
fedora_deps() {{ printf 'FEDORA_DEPS %s\\n' "$*"; }}
# The Fedora path must never reach the Limine helpers.
unset -f boot_config_has sync_boot_files verify_cmdline
grubby() {{
    if [[ $1 == --info ]]; then {arg_line}; else printf 'GRUBBY %s\\n' "$*"; fi
}}
'''


def run_sleep(code, env="", backend="omarchy", grubby_has_arg=False):
    """Run code after env, against the sleep modules of one backend."""
    tmp = tempfile.mkdtemp()
    prelude = STUBS + MODEL_STUBS + CONSTS + paths(tmp) + sleep_modules()
    if backend == "fedora":
        prelude += fedora_stubs(grubby_has_arg) + fedora_overrides()
    result = subprocess.run(["bash", "-c", prelude + "\n" + env + "\n" + code],
                            text=True, capture_output=True, timeout=10)
    result.tmp = tmp
    return result


def last_line(result):
    return result.stdout.strip().splitlines()[-1]


def dkms_calls(result):
    path = Path(result.tmp) / "fake/calls"
    return path.read_text() if path.exists() else ""


class SleepDropInTests(unittest.TestCase):
    def test_the_shipped_drop_in_sets_s2idle(self):
        conf = configparser.ConfigParser()
        conf.read_string(SLEEP_CONF.read_text())
        self.assertEqual(conf["Sleep"]["MemorySleepMode"], "s2idle")

    def test_it_lands_where_systemd_reads_sleep_drop_ins(self):
        # systemd-sleep reads only *.conf files in sleep.conf.d.
        self.assertRegex(PATCHER, r"(?m)^SLEEP_CONF_DROPIN=/etc/systemd/sleep\.conf\.d/[\w.-]+\.conf$")


class SuspendTests(unittest.TestCase):
    """The iMac18,3's module, the same on both backends."""

    def each_backend(self):
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                yield (lambda code, env="", backend=backend: run_sleep(code, env, backend))

    def test_everything_in_place_detects_applied(self):
        for run in self.each_backend():
            result = run("mod_suspend_detect", SUSPEND_APPLIED)
            self.assertEqual(result.stdout.strip(), "applied", result.stderr)

    def test_each_missing_piece_detects_partial(self):
        # Without the drop-in, suspend enters the kernel's default mode, deep
        # S3, and resets on wake; without a hook it hangs or is refused.
        missing = {
            "drop-in": TARGETS_APPLIED + HOOK_INSTALLED + XHCI_FIX_INSTALLED,
            "Thunderbolt hook": TARGETS_APPLIED + WIFI_HOOK_INSTALLED + DROP_IN_INSTALLED + XHCI_FIX_INSTALLED,
            "Wi-Fi hook": TARGETS_APPLIED + TB_HOOK_INSTALLED + DROP_IN_INSTALLED + XHCI_FIX_INSTALLED,
            "USB controller fix": TARGETS_APPLIED + HOOK_INSTALLED + DROP_IN_INSTALLED,
            "hibernate masks": HOOK_INSTALLED + DROP_IN_INSTALLED + XHCI_FIX_INSTALLED,
            "suspend unmasked": ALL_FOUR_MASKED + HOOK_INSTALLED + DROP_IN_INSTALLED + XHCI_FIX_INSTALLED,
        }
        for run in self.each_backend():
            for case, env in missing.items():
                with self.subTest(missing=case):
                    result = run("mod_suspend_detect", env)
                    self.assertEqual(result.stdout.strip(), "partial", result.stderr)

    def test_any_trace_detects_partial(self):
        traces = {
            "drop-in alone": DROP_IN_INSTALLED,
            "the old all-four mask": ALL_FOUR_MASKED,
            "some hibernate targets masked": 'MASKED="hybrid-sleep.target suspend-then-hibernate.target"\n',
            "the USB controller fix alone": XHCI_FIX_INSTALLED,
        }
        for run in self.each_backend():
            for case, env in traces.items():
                with self.subTest(trace=case):
                    result = run("mod_suspend_detect", env)
                    self.assertEqual(result.stdout.strip(), "partial", result.stderr)

    def test_untouched_system_detects_not_applied(self):
        for run in self.each_backend():
            result = run("mod_suspend_detect")
            self.assertEqual(result.stdout.strip(), "not-applied", result.stderr)

    def test_apply_sets_everything_up(self):
        for run in self.each_backend():
            result = run("mod_suspend_apply\nmod_suspend_detect")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn(UNMASK_SUSPEND, result.stdout)
            self.assertIn(MASK_HIBERNATE, result.stdout)
            # A clean system needs no boot-config change at all.
            self.assertNotIn("SYNC_BOOT", result.stdout)
            self.assertNotIn("GRUBBY", result.stdout)
            tmp = Path(result.tmp)
            self.assertEqual((tmp / "system-sleep/imac-tb-sleep-hook").read_text(), HOOK.read_text())
            self.assertEqual((tmp / "system-sleep/imac-wifi-sleep-hook").read_text(), WIFI_HOOK.read_text())
            self.assertEqual((tmp / "sleep.conf.d/imac5k-s2idle.conf").read_text(), SLEEP_CONF.read_text())
            self.assertEqual(last_line(result), "applied")

    def test_apply_refuses_before_systemd_256(self):
        # Older systemd ignores MemorySleepMode= and would suspend into deep
        # S3: stop before building or unmasking anything.
        for run in self.each_backend():
            result = run("mod_suspend_apply", "SYSTEMD_VERSION=255\n")
            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertIn("systemd 256", result.stdout)
            self.assertNotIn(UNMASK_SUSPEND, result.stdout)
            self.assertNotIn("DKMS", dkms_calls(result))
            self.assertFalse((Path(result.tmp) / "sleep.conf.d/imac5k-s2idle.conf").exists())

    def test_remove_returns_every_target_and_file_to_stock(self):
        for run in self.each_backend():
            result = run("mod_suspend_remove\nmod_suspend_detect", SUSPEND_APPLIED)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn(UNMASK_ALL, result.stdout)
            self.assertNotIn("SYNC_BOOT", result.stdout)
            tmp = Path(result.tmp)
            for name in ("system-sleep/imac-tb-sleep-hook", "system-sleep/imac-wifi-sleep-hook",
                         "sleep.conf.d/imac5k-s2idle.conf", "modules-load.d/imac5k-xhci-d0.conf"):
                self.assertFalse((tmp / name).exists(), name)
            self.assertEqual(last_line(result), "not-applied")

    def test_an_upgrade_without_the_wifi_hook_is_partial_until_reapplied(self):
        # Installs from before the Wi-Fi hook existed pick it up this way.
        before = TARGETS_APPLIED + TB_HOOK_INSTALLED + DROP_IN_INSTALLED + XHCI_FIX_INSTALLED
        for run in self.each_backend():
            result = run("mod_suspend_detect\nmod_suspend_apply >/dev/null\nmod_suspend_detect", before)
            self.assertEqual(result.stdout.split(), ["partial", "applied"], result.stderr)

    def test_the_t2_rules_are_not_consulted(self):
        # A T2 unload service is no concern of the iMac18,3's.
        env = write_file("etc-systemd-system/x.service", OLD_UNLOAD_SERVICE)
        for run in self.each_backend():
            result = run("mod_suspend_detect", env + SUSPEND_APPLIED)
            self.assertEqual(result.stdout.strip(), "applied", result.stderr)
            result = run("mod_suspend_apply", env)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class OmarchySuspendTests(unittest.TestCase):
    """The boot-config cleanup on Omarchy/Limine: the retired idle=poll and
    Omarchy's hibernation setup."""

    def test_stale_idle_poll_detects_partial_and_boot_tier(self):
        for case, env in (("drop-in", IDLE_POLL_DROPIN), ("limine default", IDLE_POLL_DEFAULT)):
            with self.subTest(case=case):
                result = run_sleep("mod_suspend_tier\nmod_suspend_detect", ALL_FOUR_MASKED + env)
                self.assertEqual(result.stdout.split(), ["boot", "partial"], result.stderr)

    def test_tier_safe_on_clean_system(self):
        result = run_sleep("mod_suspend_tier")
        self.assertEqual(result.stdout.strip(), "safe", result.stderr)

    def test_apply_stops_when_the_idle_poll_rebuild_fails(self):
        # A failed rebuild or verification must fail the apply rather than
        # end in "reboot to restore idle C-states".
        result = run_sleep("mod_suspend_apply",
                           IDLE_POLL_DROPIN + 'verify_cmdline() { echo VERIFY-FAILED; return 1; }\n')
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("VERIFY-FAILED", result.stdout)
        self.assertNotIn("reboot", result.stdout)

    def test_apply_cleans_stale_dropin_and_rebuilds(self):
        result = run_sleep("mod_suspend_apply", IDLE_POLL_DROPIN)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(UNMASK_SUSPEND, result.stdout)
        self.assertIn(MASK_HIBERNATE, result.stdout)
        self.assertFalse((Path(result.tmp) / "dropins/imac5k-no-cstates.conf").exists())
        self.assertIn("SYNC_BOOT", result.stdout)
        self.assertIn("VERIFY present= absent=idle=poll", result.stdout)

    def test_apply_strips_idle_poll_from_limine_default(self):
        result = run_sleep("mod_suspend_apply", IDLE_POLL_DEFAULT)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        default = (Path(result.tmp) / "limine-default").read_text()
        self.assertNotIn("idle=poll", default)
        self.assertTrue(list(Path(result.tmp).glob("limine-default.backup-cstates-*")))
        self.assertIn("SYNC_BOOT", result.stdout)

    def test_remove_unmasks_all_four_and_cleans_stale_dropin(self):
        result = run_sleep("mod_suspend_remove", IDLE_POLL_DROPIN)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(UNMASK_ALL, result.stdout)
        self.assertFalse((Path(result.tmp) / "dropins/imac5k-no-cstates.conf").exists())
        self.assertIn("SYNC_BOOT", result.stdout)

    def test_hibernation_setup_detects_partial_and_boot_tier(self):
        cases = {
            "hook conf, all masked": ALL_FOUR_MASKED + HIBERNATION_HOOK,
            "leftover drop-in, all masked": ALL_FOUR_MASKED + HIBERNATION_DROPIN,
            # Hibernation configured but nothing masked yet: not "not-applied".
            "hook conf alone": HIBERNATION_HOOK,
        }
        for case, env in cases.items():
            with self.subTest(case=case):
                result = run_sleep("mod_suspend_detect", env)
                self.assertEqual(result.stdout.strip(), "partial", result.stderr)
        result = run_sleep("mod_suspend_tier", HIBERNATION_HOOK)
        self.assertEqual(result.stdout.strip(), "boot", result.stderr)

    def test_apply_removes_hibernation_and_the_leftover_dropin(self):
        result = run_sleep("mod_suspend_apply", HIBERNATION_HOOK + HIBERNATION_DROPIN + '''
omarchy-hibernation-remove() { rm -f "$HIBERNATE_HOOK_CONF"; echo OMARCHY-HIBERNATION-REMOVE; }
''')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
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
        result = run_sleep("mod_suspend_apply", HIBERNATION_HOOK + HIBERNATION_DROPIN +
                           "omarchy-hibernation-remove() { echo DECLINED; }\n")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(UNMASK_SUSPEND, result.stdout)
        self.assertIn(MASK_HIBERNATE, result.stdout)
        self.assertTrue((Path(result.tmp) / "omarchy_resume.conf").exists())
        self.assertTrue((Path(result.tmp) / "dropins/resume.conf").exists())
        self.assertNotIn("SYNC_BOOT", result.stdout)

    def test_apply_without_hibernation_never_calls_the_tool(self):
        result = run_sleep("mod_suspend_apply", "omarchy-hibernation-remove() { echo SHOULD-NOT-RUN; }\n")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(UNMASK_SUSPEND, result.stdout)
        self.assertIn(MASK_HIBERNATE, result.stdout)
        self.assertNotIn("SHOULD-NOT-RUN", result.stdout)
        self.assertNotIn("SYNC_BOOT", result.stdout)

    def test_apply_removes_a_leftover_dropin_without_omarchys_tool(self):
        # Omarchy's remover leaves resume.conf behind. With the hook conf gone
        # there is nothing for that tool to do and no swapfile to warn about.
        result = run_sleep("mod_suspend_apply", HIBERNATION_DROPIN +
                           "omarchy-hibernation-remove() { echo SHOULD-NOT-RUN; }\n")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("SHOULD-NOT-RUN", result.stdout)
        self.assertNotIn("swapfile", result.stdout)
        self.assertFalse((Path(result.tmp) / "dropins/resume.conf").exists())
        self.assertIn("SYNC_BOOT", result.stdout)
        self.assertIn("VERIFY present= absent=resume=", result.stdout)


class FedoraSuspendTests(unittest.TestCase):
    """The retired idle=poll lives in this kernel's GRUB entry on Fedora."""

    def run_fedora(self, code, env="", grubby_has_arg=False):
        return run_sleep(code, env, "fedora", grubby_has_arg)

    def test_stale_idle_poll_arg_detects_partial_and_boot_tier(self):
        result = self.run_fedora("mod_suspend_tier\nmod_suspend_detect", SUSPEND_APPLIED, grubby_has_arg=True)
        self.assertEqual(result.stdout.split(), ["boot", "partial"], result.stderr)
        result = self.run_fedora("mod_suspend_tier\nmod_suspend_detect", SUSPEND_APPLIED)
        self.assertEqual(result.stdout.split(), ["safe", "applied"], result.stderr)

    def test_omarchys_hibernation_files_mean_nothing_here(self):
        result = self.run_fedora("mod_suspend_tier\nmod_suspend_detect",
                                 SUSPEND_APPLIED + HIBERNATION_HOOK + HIBERNATION_DROPIN)
        self.assertEqual(result.stdout.split(), ["safe", "applied"], result.stderr)

    def test_apply_removes_stale_idle_poll_arg(self):
        result = self.run_fedora("mod_suspend_apply", grubby_has_arg=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(UNMASK_SUSPEND, result.stdout)
        self.assertIn(MASK_HIBERNATE, result.stdout)
        self.assertIn("GRUBBY --update-kernel /boot/vmlinuz-7.2.3-test --remove-args idle=poll",
                      result.stdout)
        self.assertNotIn("--args idle=poll", result.stdout)

    def test_apply_and_remove_fail_when_grubby_fails(self):
        failing = '''
grubby() {
    if [[ $1 == --info ]]; then echo 'args="idle=poll"'; else printf 'GRUBBY %s\\n' "$*"; return 1; fi
}
'''
        for action in ("apply", "remove"):
            with self.subTest(action=action):
                result = self.run_fedora(f"mod_suspend_{action}", failing)
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertNotIn("back to stock", result.stdout)

    def test_remove_unmasks_all_four_and_removes_stale_arg(self):
        result = self.run_fedora("mod_suspend_remove", grubby_has_arg=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(UNMASK_ALL, result.stdout)
        self.assertIn("GRUBBY --update-kernel /boot/vmlinuz-7.2.3-test --remove-args idle=poll",
                      result.stdout)

    def test_an_image_based_system_is_refused(self):
        for code in ("mod_suspend_apply", "mod_suspend_remove", "mod_t2suspend_apply", "mod_t2suspend_remove"):
            with self.subTest(code=code):
                env = "fedora_mutable() { echo IMAGE-BASED; return 1; }\n"
                if "t2" in code:
                    env = "PRODUCT=iMacPro1,1\n" + t2_bridge() + env
                result = self.run_fedora(code, env)
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertIn("IMAGE-BASED", result.stdout)
                self.assertNotIn("SYSTEMCTL", result.stdout)


class XhciFixTests(unittest.TestCase):
    """iMac18,3: Apple's XHC1._PS3 resets the machine on every second sleep.

    The suspend module builds the imac5k-xhci-d0 DKMS module, loads it at
    boot through modules-load.d and at once, and reports applied only while it
    is built for the kernels and holding the controller. Both backends are
    exercised against the same fakes.
    """

    def each_backend(self):
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                yield (lambda code, env="", backend=backend: run_sleep(code, env, backend))

    def test_an_installed_but_unloaded_or_stale_build_is_partial(self):
        cases = {
            "not loaded": 'rm -rf "$XHCI_FIX_SYSFS"\n',
            "old test build without the parameter": 'rm -f "$XHCI_FIX_SYSFS/parameters/acpi_pm_skipped"\n',
            "different build in memory": 'echo OLDSRC > "$XHCI_FIX_SYSFS/srcversion"\n',
            "no boot load": 'rm -f "$XHCI_FIX_LOAD_CONF"\n',
            "not built for this kernel": 'rm -f "$FAKE/dkms-status"\n',
        }
        for run in self.each_backend():
            for case, change in cases.items():
                with self.subTest(case=case):
                    result = run("mod_suspend_detect", SUSPEND_APPLIED + change)
                    self.assertEqual(result.stdout.strip(), "partial", result.stderr)

    def test_apply_builds_loads_and_enables_it_before_unmasking_suspend(self):
        for run in self.each_backend():
            result = run("mod_suspend_apply\nmod_suspend_detect")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            calls = dkms_calls(result)
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
            self.assertEqual(last_line(result), "applied")

    def test_a_failed_build_leaves_suspend_masked_and_unloaded(self):
        for run in self.each_backend():
            result = run("mod_suspend_apply", "FAIL_DKMS_BUILD=1\n")
            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertNotIn(UNMASK_SUSPEND, result.stdout)
            self.assertNotIn("MODPROBE", result.stdout)
            self.assertFalse((Path(result.tmp) / "modules-load.d/imac5k-xhci-d0.conf").exists())

    def test_a_failed_load_stops_before_suspend_is_unmasked(self):
        result = run_sleep("mod_suspend_apply", "FAIL_MODPROBE=1\n")
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertNotIn(UNMASK_SUSPEND, result.stdout)

    def test_apply_swaps_a_different_build_already_in_memory(self):
        result = run_sleep("mod_suspend_apply", '''
mkdir -p "$XHCI_FIX_SYSFS/parameters"
echo Y > "$XHCI_FIX_SYSFS/parameters/active"
''')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertLess(result.stdout.index("MODPROBE -r imac5k_xhci_d0"), result.stdout.index("MODPROBE imac5k_xhci_d0"))

    def test_remove_unloads_it_and_removes_every_dkms_version(self):
        for run in self.each_backend():
            result = run("mod_suspend_remove\nmod_suspend_detect", XHCI_FIX_INSTALLED)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("MODPROBE -r imac5k_xhci_d0", result.stdout)
            self.assertIn("DKMS remove imac5k-xhci-d0/1 --all", dkms_calls(result))
            self.assertFalse((Path(result.tmp) / "modules-load.d/imac5k-xhci-d0.conf").exists())
            self.assertEqual(last_line(result), "not-applied")

    def test_fedora_refuses_to_load_an_unsigned_module_under_secure_boot(self):
        env = "SB_STATE='SecureBoot enabled'\nMOK_ENROLLED=0\n"
        result = run_sleep("mod_suspend_apply", env, "fedora")
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("mokutil --import", result.stdout)
        self.assertNotIn("MODPROBE", result.stdout)
        self.assertNotIn(UNMASK_SUSPEND, result.stdout)
        self.assertIn("FEDORA_DEPS dkms kernel-devel-7.2.3-test", result.stdout)
        result = run_sleep("mod_suspend_apply", "SB_STATE='SecureBoot enabled'\n", "fedora")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("MODPROBE imac5k_xhci_d0", result.stdout)


class OtherModelTests(unittest.TestCase):
    """The 2014-2015 models sleep with the stock kernel and the iMac19,1 is
    untested, so the iMac18,3's fixes are n/a there. Earlier releases applied
    them to every model: whatever of that is left reports partial, and
    applying or removing the module takes it back out."""

    def each(self, models=OTHER_MODELS):
        for model in models:
            for backend in BACKENDS:
                with self.subTest(model=model, backend=backend):
                    yield (lambda code, env="", backend=backend, model=model:
                           run_sleep(code, f"PRODUCT={model}\n" + env, backend))

    def test_a_clean_system_is_n_a_and_apply_refuses(self):
        for run in self.each():
            result = run("mod_suspend_tier\nmod_suspend_detect\nmod_t2suspend_detect")
            self.assertEqual(result.stdout.split(), ["safe", "n/a", "n/a"], result.stderr)
            result = run("mod_suspend_apply")
            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertIn("not for this model", result.stdout)
            self.assertNotIn("SYSTEMCTL", result.stdout)
            self.assertNotRegex(dkms_calls(result), r"DKMS (add|build|install|remove)")
            self.assertFalse((Path(result.tmp) / "system-sleep/imac-tb-sleep-hook").exists())

    def test_what_an_earlier_release_installed_is_partial(self):
        leftovers = {
            "Thunderbolt hook": TB_HOOK_INSTALLED,
            "Wi-Fi hook": WIFI_HOOK_INSTALLED,
            "s2idle drop-in": DROP_IN_INSTALLED,
            "USB controller fix": XHCI_FIX_INSTALLED,
            "the old all-four mask": ALL_FOUR_MASKED,
            "a whole 0.2.x install": TARGETS_APPLIED + HOOK_INSTALLED + DROP_IN_INSTALLED,
        }
        for run in self.each():
            for case, env in leftovers.items():
                with self.subTest(leftover=case):
                    result = run("mod_suspend_detect", env)
                    self.assertEqual(result.stdout.strip(), "partial", result.stderr)

    def test_the_owners_own_masks_and_hibernation_are_not_leftovers(self):
        # Neither says an earlier release was here; the owner may have set
        # them up, and removing Omarchy's hibernation is the iMac18,3's call.
        for run in self.each():
            for env in (TARGETS_APPLIED, 'MASKED="suspend.target"\n', HIBERNATION_HOOK + HIBERNATION_DROPIN):
                with self.subTest(env=env):
                    result = run("mod_suspend_tier\nmod_suspend_detect", env)
                    self.assertEqual(result.stdout.split(), ["safe", "n/a"], result.stderr)

    def test_apply_or_remove_takes_an_earlier_install_back_out(self):
        earlier = (TARGETS_APPLIED + HOOK_INSTALLED + DROP_IN_INSTALLED + XHCI_FIX_INSTALLED
                   + HIBERNATION_HOOK + "omarchy-hibernation-remove() { echo SHOULD-NOT-RUN; }\n")
        for action in ("apply", "remove"):
            for run in self.each():
                with self.subTest(action=action):
                    result = run(f"mod_suspend_{action}\nmod_suspend_detect", earlier)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertIn(UNMASK_ALL, result.stdout)
                    self.assertNotIn("SYSTEMCTL mask", result.stdout)
                    self.assertIn("DKMS remove imac5k-xhci-d0/1 --all", dkms_calls(result))
                    self.assertNotRegex(dkms_calls(result), r"DKMS (add|build|install)")
                    tmp = Path(result.tmp)
                    for name in ("system-sleep/imac-tb-sleep-hook", "system-sleep/imac-wifi-sleep-hook",
                                 "sleep.conf.d/imac5k-s2idle.conf", "modules-load.d/imac5k-xhci-d0.conf"):
                        self.assertFalse((tmp / name).exists(), name)
                    # The owner's hibernation setup stays.
                    self.assertNotIn("SHOULD-NOT-RUN", result.stdout)
                    self.assertTrue((tmp / "omarchy_resume.conf").exists())
                    self.assertEqual(last_line(result), "n/a")

    def test_the_old_block_everything_mask_is_lifted(self):
        for run in self.each():
            result = run("mod_suspend_apply\nmod_suspend_detect", ALL_FOUR_MASKED)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn(UNMASK_ALL, result.stdout)
            self.assertEqual(last_line(result), "n/a")

    def test_a_leftover_idle_poll_is_cleaned_from_the_boot_config(self):
        result = run_sleep("mod_suspend_tier\nmod_suspend_detect", "PRODUCT=iMac17,1\n" + IDLE_POLL_DROPIN)
        self.assertEqual(result.stdout.split(), ["boot", "partial"], result.stderr)
        result = run_sleep("mod_suspend_apply\nmod_suspend_detect", "PRODUCT=iMac17,1\n" + IDLE_POLL_DROPIN)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("VERIFY present= absent=idle=poll", result.stdout)
        self.assertEqual(last_line(result), "n/a")
        result = run_sleep("mod_suspend_detect", "PRODUCT=iMac17,1\n", "fedora", grubby_has_arg=True)
        self.assertEqual(result.stdout.strip(), "partial", result.stderr)


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
T2_APPLIED = TARGETS_APPLIED + TB_HOOK_INSTALLED


class T2SuspendTests(unittest.TestCase):
    """T2 models (iMac Pro, 2020 iMacs) have their own module, t2suspend.

    linux-t2's t2bce stack suspends the T2 itself, so the module requires it
    bound to the T2 bridge, refuses while anything unloads the T2 driver
    around sleep, and keeps the kernel's sleep mode. Of the iMac18,3's fixes
    only the Thunderbolt hook comes along. Both backends are exercised against
    the same fakes.
    """

    def each(self, models=T2_MODELS):
        for model in models:
            for backend in BACKENDS:
                with self.subTest(model=model, backend=backend):
                    yield model, (lambda code, env="", backend=backend, model=model:
                                  run_sleep(code, f"PRODUCT={model}\n" + env, backend))

    def test_ready_t2_model_is_applied_with_only_the_thunderbolt_hook(self):
        for _, run in self.each():
            result = run("mod_t2suspend_detect", t2_bridge() + T2_APPLIED)
            self.assertEqual(result.stdout.strip(), "applied", result.stderr)
            # The iMac18,3's own files are leftovers on these models.
            for extra in (DROP_IN_INSTALLED, WIFI_HOOK_INSTALLED):
                result = run("mod_t2suspend_detect", t2_bridge() + T2_APPLIED + extra)
                self.assertEqual(result.stdout.strip(), "partial", result.stderr)
            result = run("mod_t2suspend_detect", t2_bridge() + TARGETS_APPLIED)
            self.assertEqual(result.stdout.strip(), "partial", result.stderr)

    def test_untouched_t2_model_detects_not_applied(self):
        for _, run in self.each():
            result = run("mod_t2suspend_tier\nmod_t2suspend_detect", t2_bridge())
            self.assertEqual(result.stdout.split(), ["safe", "not-applied"], result.stderr)

    def test_apply_keeps_the_kernel_sleep_mode_and_takes_out_the_imac18_3_files(self):
        # What the combined module of earlier releases left on a T2 model.
        earlier = HOOK_INSTALLED + DROP_IN_INSTALLED
        for _, run in self.each():
            # Older systemd is fine: MemorySleepMode= is not used.
            result = run("mod_t2suspend_apply\nmod_t2suspend_detect",
                         "SYSTEMD_VERSION=255\n" + t2_bridge() + earlier)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn(UNMASK_SUSPEND, result.stdout)
            self.assertIn(MASK_HIBERNATE, result.stdout)
            tmp = Path(result.tmp)
            self.assertEqual((tmp / "system-sleep/imac-tb-sleep-hook").read_text(), HOOK.read_text())
            self.assertFalse((tmp / "system-sleep/imac-wifi-sleep-hook").exists())
            self.assertFalse((tmp / "sleep.conf.d/imac5k-s2idle.conf").exists())
            # The USB controller fix is the iMac18,3's firmware's.
            self.assertEqual(dkms_calls(result), "")
            self.assertNotIn("MODPROBE", result.stdout)
            self.assertNotIn("SYNC_BOOT", result.stdout)
            self.assertEqual(last_line(result), "applied")

    def test_apply_refuses_without_t2bce_before_changing_anything(self):
        cases = {
            "apple-bce": (t2_bridge("apple-bce"), "driven by apple-bce"),
            "unbound": (t2_bridge(None), "driven by no driver"),
            "no bridge": ("", "no Apple T2 bridge"),
        }
        for _, run in self.each():
            for case, (env, message) in cases.items():
                with self.subTest(case=case):
                    result = run("mod_t2suspend_apply", env)
                    self.assertNotEqual(result.returncode, 0, result.stdout)
                    self.assertIn(message, result.stdout)
                    self.assertNotIn("SYSTEMCTL", result.stdout)
                    self.assertFalse((Path(result.tmp) / "system-sleep/imac-tb-sleep-hook").exists())
                    result = run("mod_t2suspend_detect", env + T2_APPLIED)
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
                    result = run("mod_t2suspend_apply", env)
                    self.assertNotEqual(result.returncode, 0, result.stdout)
                    self.assertIn("unloads the T2 driver", result.stdout)
                    self.assertIn(rel, result.stdout)
                    self.assertNotIn("SYSTEMCTL", result.stdout)
                    result = run("mod_t2suspend_detect", env + T2_APPLIED)
                    self.assertEqual(result.stdout.strip(), "partial", result.stderr)

    def test_files_that_only_load_or_mention_the_driver_are_not_unload_hooks(self):
        body = "#!/bin/sh\nmodprobe apple-bce\n# t2bce stays loaded; see rmmod-free notes\n"
        for _, run in self.each(("iMacPro1,1",)):
            result = run("mod_t2suspend_apply", t2_bridge() + write_file("etc-system-sleep/load-only", body))
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_remove_returns_every_target_and_file_to_stock(self):
        for _, run in self.each():
            result = run("mod_t2suspend_remove\nmod_t2suspend_detect",
                         t2_bridge() + T2_APPLIED + WIFI_HOOK_INSTALLED + DROP_IN_INSTALLED)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn(UNMASK_ALL, result.stdout)
            tmp = Path(result.tmp)
            for name in ("system-sleep/imac-tb-sleep-hook", "system-sleep/imac-wifi-sleep-hook",
                         "sleep.conf.d/imac5k-s2idle.conf"):
                self.assertFalse((tmp / name).exists(), name)
            self.assertEqual(last_line(result), "not-applied")

    def test_omarchy_cleanup_is_the_same_as_on_the_imac18_3(self):
        env = (t2_bridge() + IDLE_POLL_DROPIN + HIBERNATION_HOOK +
               'omarchy-hibernation-remove() { rm -f "$HIBERNATE_HOOK_CONF"; echo OMARCHY-HIBERNATION-REMOVE; }\n')
        result = run_sleep("mod_t2suspend_tier\nmod_t2suspend_detect", "PRODUCT=iMacPro1,1\n" + env)
        self.assertEqual(result.stdout.split(), ["boot", "partial"], result.stderr)
        result = run_sleep("mod_t2suspend_apply\nmod_t2suspend_detect", "PRODUCT=iMacPro1,1\n" + env)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("VERIFY present= absent=idle=poll", result.stdout)
        self.assertIn("OMARCHY-HIBERNATION-REMOVE", result.stdout)
        self.assertEqual(last_line(result), "applied")

    def test_the_suspend_module_leaves_t2_models_alone(self):
        # Whatever an earlier release installed here is t2suspend's to manage:
        # removing suspend must not take the Thunderbolt hook it installed.
        env = t2_bridge() + ALL_FOUR_MASKED + HOOK_INSTALLED + DROP_IN_INSTALLED
        for _, run in self.each():
            result = run("mod_suspend_tier\nmod_suspend_detect", env)
            self.assertEqual(result.stdout.split()[-1], "n/a", result.stderr)
            for action in ("apply", "remove"):
                result = run(f"mod_suspend_{action}", env)
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertIn(f"--{action} t2suspend", result.stdout)
                self.assertNotIn("SYSTEMCTL", result.stdout)
                self.assertTrue((Path(result.tmp) / "system-sleep/imac-tb-sleep-hook").exists())

    def test_t2suspend_is_n_a_everywhere_else(self):
        env = TB_HOOK_INSTALLED + TARGETS_APPLIED
        for model in ("iMac18,3",) + OTHER_MODELS:
            for backend in BACKENDS:
                with self.subTest(model=model, backend=backend):
                    result = run_sleep("mod_t2suspend_detect", f"PRODUCT={model}\n" + env, backend)
                    self.assertEqual(result.stdout.strip(), "n/a", result.stderr)
                    for action in ("apply", "remove"):
                        result = run_sleep(f"mod_t2suspend_{action}", f"PRODUCT={model}\n" + env, backend)
                        self.assertNotEqual(result.returncode, 0, result.stdout)
                        self.assertIn("T2 models", result.stdout)
                        self.assertNotIn("SYSTEMCTL", result.stdout)
                        self.assertTrue((Path(result.tmp) / "system-sleep/imac-tb-sleep-hook").exists())


class StartupAuditTests(unittest.TestCase):
    def audit(self, model, states):
        code = shell_function(PATCHER, "startup_deps_note") + f'''
declare -A MODULE_STATES=({" ".join(f"[{m}]={s}" for m, s in states.items())})
MODULES=({" ".join(states)})
KREL=7.2.3-test
PRODUCT={model}
imac_is_fedora() {{ return 1; }}
imac_is_kde() {{ return 1; }}
imac_is_arch_grub() {{ return 1; }}
imac_xhci_fix_supported() {{ [[ $PRODUCT == iMac18,3 ]]; }}
xhci_fix_target_kernels() {{ :; }}
startup_need_headers() {{ STARTUP_NEEDS_HEADERS=1; }}
hibernation_setup_present() {{ return 0; }}
PATH=/nonexistent
startup_deps_note
echo "MISSING=${{STARTUP_MISSING_TOOLS[*]}}"
'''
        result = subprocess.run(["bash", "-c", code], text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_the_hibernation_remover_is_never_sent_to_the_package_manager(self):
        # It ships inside the omarchy package: asking pacman for it by name
        # fails the whole prerequisite install ("target not found").
        out = self.audit("iMacPro1,1", {"suspend": "n/a", "t2suspend": "partial"})
        self.assertIn("MISSING=systemctl", out)
        self.assertNotIn("omarchy-hibernation-remove", out)

    def test_only_the_models_own_sleep_module_is_audited(self):
        out = self.audit("iMacPro1,1", {"suspend": "n/a", "t2suspend": "not-applied"})
        self.assertIn("  t2suspend missing dependencies: systemctl\n", out)
        self.assertNotIn("  suspend missing", out)
        out = self.audit("iMac18,3", {"suspend": "not-applied", "t2suspend": "n/a"})
        self.assertIn("  suspend missing dependencies: systemctl dkms", out)
        self.assertNotIn("t2suspend missing", out)
        # A model that needs neither lists neither.
        out = self.audit("iMac17,1", {"suspend": "n/a", "t2suspend": "n/a"})
        self.assertNotIn("missing dependencies", out)


if __name__ == "__main__":
    unittest.main()
