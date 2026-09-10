"""Command validation happens before host probes, dependencies, or patch changes."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


PATCHER = Path(__file__).resolve().parents[1] / "scripts/imac-patcher"
SOURCE = PATCHER.read_text()
START = SOURCE.index("# ── command-line arguments")
PARSER = SOURCE[START:SOURCE.index("# ── version and upgrade", START)]


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)

    def launcher(self, *args):
        return subprocess.run(
            [str(PATCHER), *args], input="", text=True, capture_output=True,
            env={**os.environ, "HOME": str(self.home)}, timeout=5,
        )

    def parse(self, *args):
        return subprocess.run(
            ["bash", "-c", '''
set -uo pipefail
MODULES=(audio eq color suspend boot 5k)
warn() { printf '%s\\n' "$*"; }
''' + PARSER + '''
printf '%s\\n' "$ACTION" "$FORCE" "${REQUESTED_MODULES[@]}"
''', "test", *args], text=True, capture_output=True, timeout=5,
        )

    def test_help_is_available_without_creating_runtime_directories(self):
        for args in (("--help",), ("-h",), ("--force", "--help")):
            with self.subTest(args=args):
                result = self.launcher(*args)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("Usage: imac-patcher", result.stdout)
                self.assertIn("audio eq color suspend boot 5k", result.stdout)
                self.assertEqual(list(self.home.iterdir()), [])

    def test_version_does_not_create_runtime_directories(self):
        result = self.launcher("--version")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(result.stdout.strip())
        self.assertEqual(list(self.home.iterdir()), [])

    def test_force_can_appear_before_between_or_after_command_arguments(self):
        for args in (("--force", "--apply", "eq", "color"),
                     ("--apply", "eq", "--force", "color"),
                     ("--apply", "eq", "color", "--force")):
            with self.subTest(args=args):
                result = self.parse(*args)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.splitlines(), ["apply", "1", "eq", "color"])

    def test_interactive_status_and_safe_commands_parse(self):
        for args, expected in (((), ["interactive", "0"]),
                               (("--force",), ["interactive", "1"]),
                               (("--status", "--force"), ["status", "1"]),
                               (("--apply", "all"), ["apply", "0", "all"]),
                               (("--remove", "safe"), ["remove", "0", "safe"])):
            with self.subTest(args=args):
                result = self.parse(*args)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.splitlines(), expected)

    def test_invalid_arguments_stop_before_any_module_can_run(self):
        for args in (("--apply",), ("--remove",), ("--unknown",),
                     ("--apply", "eq", "typo"), ("--apply", "eq color"),
                     ("--apply", ""), ("--remove", "safe", "5k"),
                     ("--apply", "eq", "safe"), ("--apply", "all", "eq"),
                     ("--apply", "safe", "all"), ("--remove", "all"),
                     ("--status", "eq"),
                     ("--version", "unexpected"), ("--help", "--apply", "eq"),
                     ("--apply", "eq", "--remove", "color")):
            with self.subTest(args=args):
                result = self.launcher(*args)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertEqual(result.stdout, "")
                self.assertEqual(list(self.home.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
