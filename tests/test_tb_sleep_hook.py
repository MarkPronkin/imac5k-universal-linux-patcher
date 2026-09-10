"""Offline tests for the Thunderbolt sleep hook: fake sysfs tree, no root."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "scripts/imac-tb-sleep-hook"
BDF = "0000:07:00.0"


class TbSleepHookTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.drv = Path(self.tmp.name) / "drivers/thunderbolt"
        self.drv.mkdir(parents=True)
        self.state = Path(self.tmp.name) / "state"
        # A "bound device" is a directory; unbind/bind are plain files that
        # record what was written.
        (self.drv / BDF).mkdir()
        (self.drv / "unbind").touch()
        (self.drv / "bind").touch()

    def run_hook(self, *args):
        env = dict(os.environ)
        env["IMAC_TB_DRV_DIR"] = str(self.drv)
        env["IMAC_TB_STATE_FILE"] = str(self.state)
        return subprocess.run(["bash", str(HOOK), *args], env=env,
                              capture_output=True, text=True)

    def test_pre_unbinds_bound_devices(self):
        result = self.run_hook("pre")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.drv / "unbind").read_text(), BDF + "\n")
        self.assertEqual(self.state.read_text(), BDF + "\n")
        self.assertIn("unbound " + BDF, result.stdout)

    def test_post_rebinds_and_clears_state(self):
        self.state.write_text(BDF + "\n")
        result = self.run_hook("post")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.drv / "bind").read_text(), BDF + "\n")
        self.assertFalse(self.state.exists())

    def test_post_without_state_is_a_noop(self):
        result = self.run_hook("post")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.drv / "bind").read_text(), "")

    def test_pre_with_no_devices_writes_nothing(self):
        (self.drv / BDF).rmdir()
        result = self.run_hook("pre")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.drv / "unbind").read_text(), "")
        self.assertEqual(self.state.read_text(), "")

    def test_a_failed_unbind_is_logged_and_not_recorded(self):
        # unbind as a directory makes the write fail. The hook must still exit
        # 0 and leave nothing for post to rebind.
        (self.drv / "unbind").unlink()
        (self.drv / "unbind").mkdir()
        result = self.run_hook("pre")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("could not unbind " + BDF, result.stdout)
        self.assertEqual(self.state.read_text(), "")

    def test_full_cycle(self):
        self.assertEqual(self.run_hook("pre").returncode, 0)
        # After a real unbind the device dir is gone from the driver dir.
        (self.drv / BDF).rmdir()
        self.assertEqual(self.run_hook("post").returncode, 0)
        self.assertEqual((self.drv / "unbind").read_text(), BDF + "\n")
        self.assertEqual((self.drv / "bind").read_text(), BDF + "\n")

    def test_no_arguments_exits_cleanly(self):
        self.assertEqual(self.run_hook().returncode, 0)


if __name__ == "__main__":
    unittest.main()
