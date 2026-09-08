"""Exercise the real menu with mock modules, without changing the host."""
from pathlib import Path
import fcntl
import os
import pty
import subprocess
import termios
import unittest


PATCHER = Path(__file__).resolve().parents[1] / "scripts/imac-patcher"


def shell_function(source, name):
    """The named shell function, one-liner or not, lifted out of the script."""
    lines = source.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(f"{name}()"))
    if lines[start].rstrip().endswith("}"):
        return lines[start]
    end = next(i for i in range(start + 1, len(lines)) if lines[i] == "}")
    return "\n".join(lines[start:end + 1])


class MenuTests(unittest.TestCase):
    def run_menu(self, answer, picks="1\n2\n"):
        source = PATCHER.read_text()
        confirm = shell_function(source, "confirm")
        interactive = source[source.index("# ── interactive"):]
        mocks = self.mocks()
        return subprocess.run(
            ["bash", "-c", mocks + confirm + "\n" + interactive],
            input="2\n" + picks + answer, text=True, capture_output=True, timeout=5,
        )

    @staticmethod
    def mocks():
        return r'''
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
    echo "MODULE STDERR" >&2
}
'''

    def test_selected_patch_and_installer_receive_user_input(self):
        result = self.run_menu("y\ninstaller-input\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("BUILD_STARTED", result.stdout)
        self.assertIn("INSTALLER_INPUT_OK", result.stdout)

    def test_opening_the_terminal_for_the_picker_leaves_stderr_alone(self):
        """`exec 3</dev/tty 2>/dev/null` applies BOTH redirections to the shell
        and for good: every later error message, bash's own included, goes to
        /dev/null and the run dies in silence. Only a real terminal shows it --
        with a pipe on stdin the exec fails and stderr is left alone -- so this
        gives the shell a controlling terminal and keeps stderr on a pipe."""
        source = PATCHER.read_text()
        opener = next(line for line in source.splitlines()
                      if "3</dev/tty" in line and not line.lstrip().startswith("#"))
        master, slave = pty.openpty()

        def become_session_leader():
            os.setsid()
            fcntl.ioctl(0, termios.TIOCSCTTY, 0)

        proc = subprocess.Popen(
            ["bash", "-c", f"{opener}\n[[ -t 0 ]] || exit 9\necho MARKER >&2"],
            stdin=slave, stdout=slave, stderr=subprocess.PIPE, text=True,
            preexec_fn=become_session_leader)
        os.close(slave)
        errors = proc.stderr.read()
        proc.wait(timeout=10)
        os.close(master)
        self.assertEqual(proc.returncode, 0, "the shell had no controlling terminal")
        self.assertIn("MARKER", errors)

    def test_declining_does_not_start_build(self):
        result = self.run_menu("n\n")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("BUILD_STARTED", result.stdout)

    def test_missing_confirmation_does_not_start_build(self):
        result = self.run_menu("")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("BUILD_STARTED", result.stdout)

    def test_marking_a_patch_shows_it_as_selected(self):
        # Mark patch 1, then leave: the redrawn list carries the mark.
        result = self.run_menu("", picks="1\n3\n")
        self.assertIn("[x] 5k", result.stdout)
        self.assertNotIn("BUILD_STARTED", result.stdout)

    def test_exit_patcher_leaves_without_building(self):
        result = self.run_menu("", picks="3\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("BUILD_STARTED", result.stdout)

    def test_installing_nothing_builds_nothing(self):
        result = self.run_menu("", picks="2\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("nothing selected", result.stdout)
        self.assertNotIn("BUILD_STARTED", result.stdout)

    def test_marking_twice_clears_the_selection(self):
        result = self.run_menu("", picks="1\n1\n2\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("nothing selected", result.stdout)
        self.assertNotIn("BUILD_STARTED", result.stdout)


if __name__ == "__main__":
    unittest.main()
