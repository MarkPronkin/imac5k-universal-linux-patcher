"""Status snapshots save probes; actions still observe current module state."""
import subprocess
import unittest

from test_patcher_menu import driver


MOCKS = r'''
set -uo pipefail
MODULES=(audio eq)
product=iMac18,3
KREL=test
hdr() { :; }
startup_deps_note() { :; }
say() { printf '%s\n' "$*"; }
warn() { printf '%s\n' "$*"; }
mod_audio_title() { echo Audio; }
mod_audio_tier() { echo safe; }
mod_audio_detect() { echo PROBE_AUDIO >&2; echo not-applied; }
mod_eq_title() { echo EQ; }
mod_eq_tier() { echo safe; }
mod_eq_detect() { echo PROBE_EQ >&2; echo not-applied; }
eq_have_lv2() { return 1; }
'''


class DriverTests(unittest.TestCase):
    def run_shell(self, code):
        return subprocess.run(["bash", "-c", driver() + MOCKS + code],
                              text=True, capture_output=True, timeout=5)

    def test_status_checks_each_module_once_including_eq_hint(self):
        result = self.run_shell("show_status")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr.count("PROBE_AUDIO"), 1)
        self.assertEqual(result.stderr.count("PROBE_EQ"), 1)
        self.assertIn("eq needs", result.stdout)

    def test_unavailable_eq_does_not_recommend_installing_plugins(self):
        result = self.run_shell("mod_eq_detect() { echo n/a; }\nshow_status")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("eq needs", result.stdout)

    def test_actions_recheck_after_an_earlier_module_changes_prerequisites(self):
        result = self.run_shell('''
eq_available=0
mod_eq_detect() { ((eq_available)) && echo not-applied || echo n/a; }
mod_audio_apply() { eq_available=1; }
mod_eq_apply() { echo EQ_APPLIED; }
show_status
run_modules apply audio eq
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("EQ_APPLIED", result.stdout)

    def test_safe_batch_rechecks_tiers_after_displaying_status(self):
        result = self.run_shell('''
show_status
mod_audio_tier() { echo boot; }
run_module() { echo "RUN $*"; }
run_safe_modules apply
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("RUN apply audio", result.stdout)
        self.assertIn("RUN apply eq", result.stdout)

    def test_batch_continues_and_reports_failure(self):
        result = self.run_shell('''
run_module() { echo "RUN $*"; [[ $2 != audio ]]; }
run_modules remove audio eq
''')
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["RUN remove audio", "RUN remove eq"])


if __name__ == "__main__":
    unittest.main()
