"""Suspend module: suspend.target unmasked, the hibernate family masked, the
Thunderbolt sleep hook and the s2idle systemd drop-in installed, the retired
idle=poll cleaned up, and on Omarchy the hibernation setup removed with
omarchy-hibernation-remove.

The Omarchy module is exercised with stubbed systemctl/sudo/boot helpers and a
stubbed omarchy-hibernation-remove; the Fedora override with a stubbed grubby.
Nothing touches the host.
"""
import configparser
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
                   if re.match(r"^(HIBERNATE_TARGETS|NO_CSTATES_PARAM)=", line))
# The helpers every backend shares; the Fedora override calls them too.
SHARED = "\n".join(shell_function(PATCHER, name) for name in (
    "suspend_systemd_ok", "suspend_install_sleep_files", "suspend_remove_sleep_files"))

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
HOOK_INSTALLED = 'install -m755 /dev/null "$TB_SLEEP_HOOK"\n'
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
        prelude = STUBS + CONSTS + f'''
LIMINE_DEFAULT={tmp}/limine-default
LIMINE_DROPIN_DIR={tmp}/dropins
NO_CSTATES_DROPIN={tmp}/dropins/imac5k-no-cstates.conf
HIBERNATE_HOOK_CONF={tmp}/omarchy_resume.conf
HIBERNATE_DROPIN={tmp}/dropins/resume.conf
TB_SLEEP_HOOK={tmp}/system-sleep/imac-tb-sleep-hook
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


class FedoraSuspendTests(unittest.TestCase):
    def run_module(self, code, grubby_has_arg=False):
        arg_line = 'echo \'args="idle=poll"\'' if grubby_has_arg else ':'
        tmp = tempfile.mkdtemp()
        prelude = STUBS + CONSTS + f'''
KREL=7.2.2-test
TB_SLEEP_HOOK={tmp}/system-sleep/imac-tb-sleep-hook
SLEEP_CONF_DROPIN={tmp}/sleep.conf.d/imac5k-s2idle.conf
SCRIPT_DIR={ROOT}/scripts
mkdir -p "$(dirname "$TB_SLEEP_HOOK")"
fedora_mutable() {{ return 0; }}
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
        self.assertIn("GRUBBY --update-kernel /boot/vmlinuz-7.2.2-test --remove-args idle=poll",
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
        self.assertIn("GRUBBY --update-kernel /boot/vmlinuz-7.2.2-test --remove-args idle=poll",
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


if __name__ == "__main__":
    unittest.main()
