"""Exercise the real menu with mock modules, without changing the host."""
from pathlib import Path
import subprocess
import unittest


PATCHER = Path(__file__).resolve().parents[1] / "scripts/imac-patcher"


class MenuTests(unittest.TestCase):
    def run_menu(self, answer):
        source = PATCHER.read_text()
        confirm = next(line for line in source.splitlines() if line.startswith("confirm(){"))
        interactive = source[source.index("# ── interactive"):]
        mocks = r'''
set -uo pipefail
HAVE_GUM=0
MODULES=(5k)
show_status() { :; }
say() { printf '%s\n' "$*"; }
mod_5k_detect() { echo not-applied; }
mod_5k_title() { echo 'Native 5K display'; }
mod_5k_tier() { echo boot; }
run_module() {
    [[ $1 == apply && $2 == 5k ]] || return 1
    confirm 'Build and install 5K?' || return 1
    echo BUILD_STARTED
    # A child installer must inherit the same input, too.
    bash -c 'read -r token; [[ $token == installer-input ]]' || return 1
    echo INSTALLER_INPUT_OK
}
'''
        return subprocess.run(
            ["bash", "-c", mocks + confirm + "\n" + interactive],
            input="2\n1\n" + answer, text=True, capture_output=True, timeout=5,
        )

    def test_selected_patch_and_installer_receive_user_input(self):
        result = self.run_menu("y\ninstaller-input\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("BUILD_STARTED", result.stdout)
        self.assertIn("INSTALLER_INPUT_OK", result.stdout)

    def test_declining_does_not_start_build(self):
        result = self.run_menu("n\n")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("BUILD_STARTED", result.stdout)

    def test_missing_confirmation_does_not_start_build(self):
        result = self.run_menu("")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("BUILD_STARTED", result.stdout)


if __name__ == "__main__":
    unittest.main()
