"""Exercise the startup dependency gate against a stub PATH, installing nothing."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest


PATCHER = Path(__file__).resolve().parents[1] / "scripts/imac-patcher"
REAL = "/usr/bin"

# say/warn/confirm come from the patcher; the gate is the part under test.
HARNESS = """
set -uo pipefail
HAVE_GUM=0
say()  { printf '==> %s\\n' "$*"; }
warn() { printf '!! %s\\n' "$*"; }
confirm(){ read -rp "$1 [y/N] " a; [[ $a == [yY]* ]]; }
"""


def gate():
    source = PATCHER.read_text()
    start = source.index("# ── core dependencies")
    return source[start:source.index("# ═══════════════════════ module: audio", start)]


class DepsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.bin = Path(self.tmp.name) / "bin"
        self.bin.mkdir()
        # A PATH holding only what the gate itself needs, so anything else can
        # be added or withheld per test.
        for name in ("bash", "grep", "sed", "awk", "ln", "readlink"):
            (self.bin / name).symlink_to(f"{REAL}/{name}")
        self.stub("sudo", 'exec "$@"')
        # A package manager that reports what it was asked for and, for the
        # packages named here, actually delivers the command.
        self.stub("pacman", f'''echo "PACMAN: $*"
for p in "$@"; do
    case $p in
        findutils) {REAL}/ln -sf {REAL}/find "{self.bin}/find" ;;
        coreutils) {REAL}/ln -sf {REAL}/install "{self.bin}/install" ;;
    esac
done
exit 0''')

    def stub(self, name, body):
        path = self.bin / name
        path.write_text(f"#!{REAL}/bash\n{body}\n")
        path.chmod(0o755)

    def provide(self, *names):
        for name in names:
            (self.bin / name).symlink_to(f"{REAL}/{name}")

    def run_gate(self, answer=""):
        return subprocess.run(
            [f"{REAL}/bash", "-c", HARNESS + gate()], input=answer, text=True,
            capture_output=True, timeout=10, env={**os.environ, "PATH": str(self.bin)},
        )

    def test_complete_dependencies_pass_silently(self):
        self.provide("find", "install")
        result = self.run_gate()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")

    def test_missing_dependency_is_installed_after_confirmation(self):
        result = self.run_gate("y\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("PACMAN: -S --needed --noconfirm findutils coreutils", result.stdout)
        self.assertIn("dependencies installed", result.stdout)

    def test_declining_stops_the_run(self):
        result = self.run_gate("n\n")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("PACMAN:", result.stdout)
        self.assertIn("cannot run without", result.stdout)

    def test_install_that_delivers_nothing_is_reported(self):
        self.stub("pacman", 'echo "PACMAN: $*"; exit 0')
        result = self.run_gate("y\n")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("still missing after the install", result.stdout)

    def test_without_a_package_manager_the_packages_are_named(self):
        (self.bin / "pacman").unlink()
        result = self.run_gate()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("install these as root, then re-run: findutils coreutils", result.stdout)

    def test_missing_sudo_is_not_installed_with_sudo(self):
        self.provide("find", "install")
        (self.bin / "sudo").unlink()
        result = self.run_gate("y\n")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("PACMAN:", result.stdout)
        self.assertIn("install these as root, then re-run: sudo", result.stdout)


if __name__ == "__main__":
    unittest.main()
