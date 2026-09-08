"""Suspend module: sleep without C-states, hibernation masked off.

The Omarchy module is exercised with stubbed systemctl/sudo/boot helpers; the
Fedora override with a stubbed grubby. Nothing touches the host.
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
                   if re.match(r"^(SLEEP_TARGETS|HIBERNATE_TARGETS|NO_CSTATES_PARAM)=", line))


def omarchy_module():
    start = PATCHER.index("# ═══════════════════════ module: suspend ")
    end = PATCHER.index("# ═══════════════════════ module: boot ", start)
    return PATCHER[start:end]


def fedora_module():
    start = FEDORA.index("mod_suspend_desc()")
    end = FEDORA.index("mod_audio_apply()", start)
    return FEDORA[start:end]


STUBS = r'''
set -uo pipefail
say() { printf '%s\n' "$*"; }
warn() { printf '%s\n' "$*"; }
systemctl() { printf 'SYSTEMCTL %s\n' "$*"; }
boot_config_has() { return "${BOOT_CONF_HAS:-1}"; }
grep() { return "${LIVE_HAS_PARAM:-1}"; }
'''


class OmarchySuspendTests(unittest.TestCase):
    def run_module(self, code, env=""):
        tmp = tempfile.mkdtemp()
        prelude = STUBS + CONSTS + f'''
LIMINE_DEFAULT={tmp}/limine-default
LIMINE_DROPIN_DIR={tmp}/dropins
NO_CSTATES_DROPIN={tmp}/dropins/imac5k-no-cstates.conf
{env}
''' + omarchy_module()
        result = subprocess.run(["bash", "-c", prelude + code],
                                text=True, capture_output=True, timeout=10)
        result.tmp = tmp
        return result

    def test_applied_state_detects_applied(self):
        result = self.run_module(
            "mod_suspend_detect",
            env='''
systemctl() {
    case "$2" in
        suspend.target) echo static ;;
        *) echo masked ;;
    esac
}
boot_config_has() { return 0; }
grep() { return 0; }
''')
        self.assertEqual(result.stdout.strip(), "applied", result.stderr)

    def test_old_block_everything_state_detects_partial(self):
        # All four targets masked, no kernel parameter: the pre-change behaviour.
        result = self.run_module(
            "mod_suspend_detect",
            env='systemctl() { echo masked; }\n')
        self.assertEqual(result.stdout.strip(), "partial", result.stderr)

    def test_untouched_system_detects_not_applied(self):
        result = self.run_module(
            "mod_suspend_detect",
            env='systemctl() { echo static; }\n')
        self.assertEqual(result.stdout.strip(), "not-applied", result.stderr)

    def test_applied_but_not_yet_rebooted_detects_partial(self):
        result = self.run_module(
            "mod_suspend_detect",
            env='''
systemctl() {
    case "$2" in
        suspend.target) echo static ;;
        *) echo masked ;;
    esac
}
boot_config_has() { return 0; }
grep() { return 1; }
''')
        self.assertEqual(result.stdout.strip(), "partial", result.stderr)

    def test_apply_masks_only_hibernation_and_adds_idle_poll(self):
        result = self.run_module('''
sudo() { "$@"; }
sync_boot_files() { return 0; }
verify_cmdline() { return 0; }
mod_suspend_apply
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SYSTEMCTL mask hibernate.target hybrid-sleep.target suspend-then-hibernate.target",
                      result.stdout)
        self.assertIn("SYSTEMCTL unmask suspend.target", result.stdout)
        # The mask line must name exactly the three hibernation targets.
        self.assertNotIn("suspend.target hibernate", result.stdout)
        dropin = Path(result.tmp) / "dropins/imac5k-no-cstates.conf"
        self.assertIn('KERNEL_CMDLINE[default]+=" idle=poll"', dropin.read_text())

    def test_remove_unmasks_everything_and_drops_idle_poll(self):
        result = self.run_module('''
sudo() { "$@"; }
sync_boot_files() { return 0; }
verify_cmdline() { [[ -z $1 && $2 == idle=poll ]]; }
mkdir -p "$LIMINE_DROPIN_DIR"
printf 'KERNEL_CMDLINE[default]+=" idle=poll"\n' > "$NO_CSTATES_DROPIN"
touch "$LIMINE_DEFAULT"
mod_suspend_remove
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SYSTEMCTL unmask suspend.target hibernate.target hybrid-sleep.target suspend-then-hibernate.target",
                      result.stdout)
        self.assertFalse((Path(result.tmp) / "dropins/imac5k-no-cstates.conf").exists())


class FedoraSuspendTests(unittest.TestCase):
    def run_module(self, code):
        prelude = STUBS + CONSTS + '''
KREL=7.2.2-test
fedora_mutable() { return 0; }
sudo() { "$@"; }
grubby() { printf 'GRUBBY %s\n' "$*"; }
''' + fedora_module()
        return subprocess.run(["bash", "-c", prelude + code],
                              text=True, capture_output=True, timeout=10)

    def test_apply_adds_idle_poll_and_keeps_suspend_unmasked(self):
        result = self.run_module("mod_suspend_apply")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SYSTEMCTL mask hibernate.target hybrid-sleep.target suspend-then-hibernate.target",
                      result.stdout)
        self.assertIn("SYSTEMCTL unmask suspend.target", result.stdout)
        self.assertIn("GRUBBY --update-kernel /boot/vmlinuz-7.2.2-test --args idle=poll",
                      result.stdout)

    def test_remove_restores_everything(self):
        result = self.run_module("mod_suspend_remove")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SYSTEMCTL unmask suspend.target hibernate.target hybrid-sleep.target suspend-then-hibernate.target",
                      result.stdout)
        self.assertIn("GRUBBY --update-kernel /boot/vmlinuz-7.2.2-test --remove-args idle=poll",
                      result.stdout)


if __name__ == "__main__":
    unittest.main()
