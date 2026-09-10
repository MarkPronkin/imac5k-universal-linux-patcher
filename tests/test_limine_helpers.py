"""Protect package-named default UKIs without running boot tools."""
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest

from test_patcher_menu import shell_function

ROOT = Path(__file__).resolve().parents[1]
ALT = (ROOT / "scripts/imac-alt-entry").read_text()


class LimineNamesTests(unittest.TestCase):
    def run_helper(self, code):
        functions = "\n".join(shell_function(ALT, name) for name in (
            "check_name", "uki_path", "check_limine_name", "repin_orphans", "marker"))
        return subprocess.run(["bash", "-c", functions + "\n" + '''
set -euo pipefail
die() { echo "$*" >&2; exit 1; }
say() { :; }
''' + code], text=True, capture_output=True, timeout=10)

    def test_default_kernel_and_single_test_slot_cannot_be_used_as_alt_names(self):
        for pkgbase, name, allowed in (("linux-t2", "t2", False),
                                       ("linux-lts", "lts", False),
                                       ("linux", "5ktest", False),
                                       ("linux-t2", "pro-fix", True),
                                       ("linux", "t2", True)):
            with self.subTest(pkgbase=pkgbase, name=name):
                result = self.run_helper(f'''
UKIDIR=/tmp/fake-esp/EFI/Linux
DEFAULT_UKI="$UKIDIR/omarchy_{pkgbase}.efi"
check_limine_name {name}
''')
                self.assertEqual(result.returncode == 0, allowed, result.stderr)
        # Every mutating Limine entry point must pass the guard before I/O.
        dispatch = ALT[ALT.index('case "${1:-list}" in', ALT.index('imac_has_limine ||')):]
        for action, end in (("add", "promote"), ("promote", "drop"), ("drop", "list")):
            body = dispatch.split(f"\n{action})\n", 1)[1].split(f"\n{end})\n", 1)[0]
            self.assertIn('check_limine_name "$NAME"', body)

    def test_repin_preserves_the_linux_t2_default_and_the_single_test_slot(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            conf = root / "limine.conf"
            conf.write_text("  cmdline: quiet amdgpu.tiled_stitch=1\n")
            for name in ("t2", "5ktest", "pro-fix"):
                (root / f"omarchy_linux-{name}.efi").write_text(name)
            result = self.run_helper(f'''
UKIDIR={shlex.quote(tmp)}
CONF={shlex.quote(str(conf))}
DEFAULT_UKI="$UKIDIR/omarchy_linux-t2.efi"
add_entry() {{ echo "PIN $1"; }}
repin_orphans
''')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.splitlines(), ["PIN pro-fix"])
            self.assertEqual((root / "omarchy_linux-t2.efi").read_text(), "t2")
