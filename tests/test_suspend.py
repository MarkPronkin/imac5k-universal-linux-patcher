"""Suspend module: suspend.target unmasked, the hibernate family masked, the
retired idle=poll cleaned up, and on Omarchy the hibernation setup removed with
omarchy-hibernation-remove.

The Omarchy module is exercised with stubbed systemctl/sudo/boot helpers and a
stubbed omarchy-hibernation-remove; the Fedora override with a stubbed grubby.
Nothing touches the host.
"""
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PATCHER = (ROOT / "scripts/imac-patcher").read_text()
FEDORA = (ROOT / "scripts/lib/fedora.sh").read_text()

CONSTS = "\n".join(line for line in PATCHER.splitlines()
                   if re.match(r"^(HIBERNATE_TARGETS|NO_CSTATES_PARAM|S2IDLE_PARAM|TB_SLEEP_HOOK)=", line))

UNMASK_SUSPEND = "SYSTEMCTL unmask suspend.target"
MASK_HIBERNATE = ("SYSTEMCTL mask hibernate.target"
                  " hybrid-sleep.target suspend-then-hibernate.target")
UNMASK_ALL = ("SYSTEMCTL unmask suspend.target hibernate.target"
              " hybrid-sleep.target suspend-then-hibernate.target")


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
systemctl() { printf 'SYSTEMCTL %s\n' "$*"; }
# Mirror the real helper: the parameter can sit in either file.
boot_config_has() { grep -qs -- "$1" "$LIMINE_DEFAULT" "$LIMINE_DROPIN_DIR"/*.conf; }
sync_boot_files() { printf 'SYNC_BOOT\n'; }
verify_cmdline() { printf 'VERIFY present=%s absent=%s\n' "${1:-}" "${2:-}"; }
sudo() { "$@"; }
'''


class OmarchySuspendTests(unittest.TestCase):
    def run_module(self, code, env=""):
        tmp = tempfile.mkdtemp()
        prelude = STUBS + CONSTS + f'''
LIMINE_DEFAULT={tmp}/limine-default
LIMINE_DROPIN_DIR={tmp}/dropins
NO_CSTATES_DROPIN={tmp}/dropins/imac5k-no-cstates.conf
S2IDLE_DROPIN={tmp}/dropins/imac5k-s2idle.conf
HIBERNATE_HOOK_CONF={tmp}/omarchy_resume.conf
HIBERNATE_DROPIN={tmp}/dropins/resume.conf
TB_SLEEP_HOOK={tmp}/system-sleep/imac-tb-sleep-hook
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
            "mod_suspend_detect",
            env='''
systemctl() {
    case "$2" in
        suspend.target) echo static ;;
        *) echo masked ;;
    esac
}
install -m755 /dev/null "$TB_SLEEP_HOOK"
printf 'KERNEL_CMDLINE[default]+=" mem_sleep_default=s2idle"\n' > "$S2IDLE_DROPIN"
''')
        self.assertEqual(result.stdout.strip(), "applied", result.stderr)

    def test_s2idle_param_in_limine_default_detects_applied(self):
        # The handoff-era manual step put the parameter in /etc/default/limine
        # instead of a drop-in; detect accepts it there too.
        result = self.run_module(
            "mod_suspend_detect",
            env='''
systemctl() {
    case "$2" in
        suspend.target) echo static ;;
        *) echo masked ;;
    esac
}
install -m755 /dev/null "$TB_SLEEP_HOOK"
printf 'KERNEL_CMDLINE[default]="quiet mem_sleep_default=s2idle"\n' > "$LIMINE_DEFAULT"
''')
        self.assertEqual(result.stdout.strip(), "applied", result.stderr)

    def test_missing_s2idle_default_detects_partial(self):
        # Targets right and the hook installed, but deep is still the default:
        # the first suspend would hit the S3 wake reset.
        result = self.run_module(
            "mod_suspend_detect",
            env='''
systemctl() {
    case "$2" in
        suspend.target) echo static ;;
        *) echo masked ;;
    esac
}
install -m755 /dev/null "$TB_SLEEP_HOOK"
''')
        self.assertEqual(result.stdout.strip(), "partial", result.stderr)

    def test_missing_hook_alone_detects_partial(self):
        # Targets right but the Thunderbolt sleep hook not installed.
        result = self.run_module(
            "mod_suspend_detect",
            env='''
systemctl() {
    case "$2" in
        suspend.target) echo static ;;
        *) echo masked ;;
    esac
}
''')
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
        result = self.run_module(
            "mod_suspend_apply",
            env='printf \'KERNEL_CMDLINE[default]+=" mem_sleep_default=s2idle"\\n\' > "$S2IDLE_DROPIN"\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(UNMASK_SUSPEND, result.stdout)
        self.assertIn(MASK_HIBERNATE, result.stdout)
        # s2idle already the default and no stale idle=poll: boot config
        # stays untouched.
        self.assertNotIn("SYNC_BOOT", result.stdout)
        hook = Path(result.tmp) / "system-sleep/imac-tb-sleep-hook"
        self.assertTrue(hook.exists())
        self.assertEqual(hook.read_text(),
                         (ROOT / "scripts/imac-tb-sleep-hook").read_text())

    def test_apply_writes_s2idle_dropin_and_rebuilds(self):
        result = self.run_module("mod_suspend_apply")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(UNMASK_SUSPEND, result.stdout)
        self.assertIn(MASK_HIBERNATE, result.stdout)
        dropin = Path(result.tmp) / "dropins/imac5k-s2idle.conf"
        self.assertIn("mem_sleep_default=s2idle", dropin.read_text())
        self.assertIn("SYNC_BOOT", result.stdout)
        self.assertIn("VERIFY present=mem_sleep_default=s2idle absent=", result.stdout)

    def test_remove_deletes_the_hook(self):
        result = self.run_module('''
install -m755 /dev/null "$TB_SLEEP_HOOK"
mod_suspend_remove
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(UNMASK_ALL, result.stdout)
        self.assertFalse((Path(result.tmp) / "system-sleep/imac-tb-sleep-hook").exists())

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

    def test_remove_deletes_s2idle_dropin_and_rebuilds(self):
        # Without the hook an s2idle suspend would hang, so removing the
        # module returns the mem_sleep default to stock too.
        result = self.run_module('''
printf 'KERNEL_CMDLINE[default]+=" mem_sleep_default=s2idle"\\n' > "$S2IDLE_DROPIN"
mod_suspend_remove
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(UNMASK_ALL, result.stdout)
        self.assertFalse((Path(result.tmp) / "dropins/imac5k-s2idle.conf").exists())
        self.assertIn("SYNC_BOOT", result.stdout)
        self.assertIn("VERIFY present= absent=mem_sleep_default=s2idle", result.stdout)

    def test_remove_strips_s2idle_from_limine_default(self):
        result = self.run_module('''
printf 'KERNEL_CMDLINE[default]="quiet mem_sleep_default=s2idle"\\n' > "$LIMINE_DEFAULT"
mod_suspend_remove
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        default = (Path(result.tmp) / "limine-default").read_text()
        self.assertNotIn("mem_sleep_default=s2idle", default)
        self.assertTrue(list(Path(result.tmp).glob("limine-default.backup-s2idle-*")))
        self.assertIn("SYNC_BOOT", result.stdout)

    def test_tier_boot_while_s2idle_default_missing(self):
        result = self.run_module("mod_suspend_tier")
        self.assertEqual(result.stdout.strip(), "boot", result.stderr)

    def test_tier_safe_when_s2idle_present(self):
        result = self.run_module(
            "mod_suspend_tier",
            env='printf \'KERNEL_CMDLINE[default]+=" mem_sleep_default=s2idle"\\n\' > "$S2IDLE_DROPIN"\n')
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
printf 'KERNEL_CMDLINE[default]+=" mem_sleep_default=s2idle"\n' > "$S2IDLE_DROPIN"
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
printf 'KERNEL_CMDLINE[default]+=" mem_sleep_default=s2idle"\n' > "$S2IDLE_DROPIN"
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
printf 'KERNEL_CMDLINE[default]+=" mem_sleep_default=s2idle"\n' > "$S2IDLE_DROPIN"
omarchy-hibernation-remove() { echo SHOULD-NOT-RUN; }
mod_suspend_apply
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(UNMASK_SUSPEND, result.stdout)
        self.assertIn(MASK_HIBERNATE, result.stdout)
        self.assertNotIn("SHOULD-NOT-RUN", result.stdout)
        self.assertNotIn("SYNC_BOOT", result.stdout)


class FedoraSuspendTests(unittest.TestCase):
    def run_module(self, code, grubby_has_arg=False, grubby_has_s2idle=False):
        args = []
        if grubby_has_arg:
            args.append("idle=poll")
        if grubby_has_s2idle:
            args.append("mem_sleep_default=s2idle")
        arg_line = 'echo \'args="%s"\'' % " ".join(args) if args else ':'
        tmp = tempfile.mkdtemp()
        prelude = STUBS + CONSTS + f'''
KREL=7.2.2-test
TB_SLEEP_HOOK={tmp}/system-sleep/imac-tb-sleep-hook
SCRIPT_DIR={ROOT}/scripts
mkdir -p "$(dirname "$TB_SLEEP_HOOK")"
fedora_mutable() {{ return 0; }}
unset -f boot_config_has sync_boot_files verify_cmdline
grubby() {{
    if [[ $1 == --info ]]; then {arg_line}; else printf 'GRUBBY %s\n' "$*"; fi
}}
''' + fedora_module()
        result = subprocess.run(["bash", "-c", prelude + code],
                                text=True, capture_output=True, timeout=10)
        result.tmp = tmp
        return result

    def test_suspend_open_and_hibernate_masked_detects_applied(self):
        result = self.run_module('''
systemctl() {
    case "$2" in
        suspend.target) echo static ;;
        *) echo masked ;;
    esac
}
install -m755 /dev/null "$TB_SLEEP_HOOK"
mod_suspend_detect''', grubby_has_s2idle=True)
        self.assertEqual(result.stdout.strip(), "applied", result.stderr)

    def test_missing_s2idle_default_detects_partial(self):
        result = self.run_module('''
systemctl() {
    case "$2" in
        suspend.target) echo static ;;
        *) echo masked ;;
    esac
}
install -m755 /dev/null "$TB_SLEEP_HOOK"
mod_suspend_detect''')
        self.assertEqual(result.stdout.strip(), "partial", result.stderr)

    def test_all_four_masked_detects_partial(self):
        result = self.run_module(
            "systemctl() { echo masked; }; mod_suspend_detect")
        self.assertEqual(result.stdout.strip(), "partial", result.stderr)

    def test_stale_idle_poll_arg_detects_partial(self):
        result = self.run_module(
            "systemctl() { echo masked; }; mod_suspend_detect",
            grubby_has_arg=True, grubby_has_s2idle=True)
        self.assertEqual(result.stdout.strip(), "partial", result.stderr)

    def test_apply_unmasks_suspend_and_masks_hibernate_without_stale_arg(self):
        result = self.run_module("mod_suspend_apply", grubby_has_s2idle=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(UNMASK_SUSPEND, result.stdout)
        self.assertIn(MASK_HIBERNATE, result.stdout)
        self.assertNotIn("--update-kernel", result.stdout)
        self.assertTrue((Path(result.tmp) / "system-sleep/imac-tb-sleep-hook").exists())

    def test_apply_defaults_s2idle_when_missing(self):
        result = self.run_module("mod_suspend_apply")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(UNMASK_SUSPEND, result.stdout)
        self.assertIn(MASK_HIBERNATE, result.stdout)
        self.assertIn("GRUBBY --update-kernel /boot/vmlinuz-7.2.2-test --args mem_sleep_default=s2idle",
                      result.stdout)

    def test_apply_removes_stale_idle_poll_arg(self):
        result = self.run_module("mod_suspend_apply", grubby_has_arg=True, grubby_has_s2idle=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(UNMASK_SUSPEND, result.stdout)
        self.assertIn(MASK_HIBERNATE, result.stdout)
        self.assertIn("GRUBBY --update-kernel /boot/vmlinuz-7.2.2-test --remove-args idle=poll",
                      result.stdout)
        self.assertNotIn("--args idle=poll", result.stdout)

    def test_remove_unmasks_all_four_and_removes_stale_arg(self):
        result = self.run_module("mod_suspend_remove", grubby_has_arg=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(UNMASK_ALL, result.stdout)
        self.assertIn("GRUBBY --update-kernel /boot/vmlinuz-7.2.2-test --remove-args idle=poll",
                      result.stdout)

    def test_remove_drops_s2idle_default(self):
        result = self.run_module("mod_suspend_remove", grubby_has_s2idle=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(UNMASK_ALL, result.stdout)
        self.assertIn("GRUBBY --update-kernel /boot/vmlinuz-7.2.2-test --remove-args mem_sleep_default=s2idle",
                      result.stdout)

    def test_tier_safe_when_s2idle_present(self):
        result = self.run_module("mod_suspend_tier", grubby_has_s2idle=True)
        self.assertEqual(result.stdout.strip(), "safe", result.stderr)

    def test_tier_boot_while_s2idle_default_missing(self):
        result = self.run_module("mod_suspend_tier")
        self.assertEqual(result.stdout.strip(), "boot", result.stderr)

    def test_tier_boot_while_stale_grub_arg_remains(self):
        result = self.run_module("mod_suspend_tier", grubby_has_arg=True, grubby_has_s2idle=True)
        self.assertEqual(result.stdout.strip(), "boot", result.stderr)


if __name__ == "__main__":
    unittest.main()
