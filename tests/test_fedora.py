"""Offline tests: no host boot files, package installation or root required."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("display", ROOT / "scripts/kde-display.py")
display = importlib.util.module_from_spec(spec)
spec.loader.exec_module(display)


class DisplayTests(unittest.TestCase):
    def test_active_mode_not_available_mode(self):
        output = {"currentModeId": "small", "modes": [
            {"id": "small", "size": {"width": 2560, "height": 2880}},
            {"id": "big", "size": {"width": 5120, "height": 2880}}]}
        self.assertFalse(display.is_5k(output))
        output["currentModeId"] = "big"
        self.assertTrue(display.is_5k(output))

    def test_internal_panel_only(self):
        panel = {"name": "eDP-1", "connected": True, "enabled": True}
        external = {"name": "DP-2", "connected": True, "enabled": True}
        self.assertEqual(display.panel({"outputs": [external, panel]}), panel)

    def test_color_ignores_external_and_hdr_profiles(self):
        text = "Output: 2 DP-2\n Color profile source: ICC\n\x1b[32mOutput: 1 eDP-1\x1b[0m\n Color profile source: sRGB\n HDR color profile source: EDID\n"
        self.assertEqual(display.profile(text, 1), "sRGB")

    def test_color_round_trip_preserves_icc_selection(self):
        with tempfile.TemporaryDirectory() as tmp:
            current = ["ICC"]
            def doctor(*args):
                if args == ("--json",):
                    return json.dumps({"outputs": [{"id": 1, "name": "eDP-1", "connected": True}]})
                if args == ("--outputs",):
                    return f"Output: 1 eDP-1\n Color profile source: {current[0]}\n"
                current[0] = args[0].split(".")[-1]
                return ""
            env = {"XDG_STATE_HOME": tmp, "XDG_SESSION_TYPE": "wayland", "WAYLAND_DISPLAY": "wayland-0"}
            with patch.dict(os.environ, env), patch.object(display, "doctor", doctor):
                with patch("sys.argv", ["kde-display.py", "--apply"]):
                    self.assertEqual(display.main(), 0)
                self.assertEqual(current[0], "EDID")
                with patch("sys.argv", ["kde-display.py", "--remove"]):
                    self.assertEqual(display.main(), 0)
                self.assertEqual(current[0], "ICC")
                self.assertFalse((Path(tmp) / "imac-patcher/kde-color.json").exists())


    # A mock KScreen: one internal panel whose identity and profile can change
    # under the script, the way the 5K stitch reboot changes them for real.
    def kscreen(self, uuid="old-identity", current="sRGB"):
        state = {"uuid": uuid, "profile": current}

        def doctor(*args):
            if args == ("--json",):
                return json.dumps({"outputs": [{"id": 1, "name": "eDP-1", "connected": True}]})
            if args == ("--outputs",):
                return f"Output: 1 eDP-1 {state['uuid']}\n Color profile source: {state['profile']}\n"
            state["profile"] = args[0].split(".")[-1]
            return ""
        return state, doctor

    def run_display(self, tmp, doctor, action):
        env = {"XDG_STATE_HOME": tmp, "XDG_SESSION_TYPE": "wayland", "WAYLAND_DISPLAY": "wayland-0"}
        with patch.dict(os.environ, env), patch.object(display, "doctor", doctor):
            with patch("sys.argv", ["kde-display.py", "--" + action]):
                return display.main()

    def test_panel_identity_is_read_from_the_output_header(self):
        self.assertEqual(display.identity("Output: 1 eDP-1 516d0d05-b646\n x\n", 1), "516d0d05-b646")
        # Older KScreen builds print no identity; absence must not look like one.
        self.assertEqual(display.identity("Output: 1 eDP-1\n x\n", 1), "")

    def test_setting_saved_before_the_stitch_is_not_restored_onto_the_new_panel(self):
        """KWin keys the profile to the panel's EDID, which the 5K stitch rewrites."""
        with tempfile.TemporaryDirectory() as tmp:
            panel, doctor = self.kscreen()
            state = Path(tmp) / "imac-patcher/kde-color.json"
            self.assertEqual(self.run_display(tmp, doctor, "apply"), 0)
            self.assertEqual(panel["profile"], "EDID")
            self.assertEqual(json.loads(state.read_text())["uuid"], "old-identity")
            # The stitch reboot: same connector, new panel, KDE's own defaults.
            panel.update(uuid="new-identity", profile="sRGB")
            self.assertEqual(self.run_display(tmp, doctor, "remove"), 0)
            # Nothing of ours is on this panel, so nothing is written to it.
            self.assertEqual(panel["profile"], "sRGB")
            self.assertFalse(state.exists())

    def test_applying_after_the_stitch_records_the_panel_that_is_actually_there(self):
        with tempfile.TemporaryDirectory() as tmp:
            panel, doctor = self.kscreen()
            state = Path(tmp) / "imac-patcher/kde-color.json"
            self.assertEqual(self.run_display(tmp, doctor, "apply"), 0)
            panel.update(uuid="new-identity", profile="ICC")
            self.assertEqual(self.run_display(tmp, doctor, "apply"), 0)
            # The stale pre-stitch save must not survive to be restored later.
            self.assertEqual(json.loads(state.read_text()),
                             {"output": "eDP-1", "uuid": "new-identity", "profile": "ICC"})
            self.assertEqual(self.run_display(tmp, doctor, "remove"), 0)
            self.assertEqual(panel["profile"], "ICC")

    def test_state_files_written_before_identities_were_recorded_still_restore(self):
        with tempfile.TemporaryDirectory() as tmp:
            panel, doctor = self.kscreen(current="EDID")
            state = Path(tmp) / "imac-patcher/kde-color.json"
            state.parent.mkdir(parents=True)
            state.write_text(json.dumps({"output": "eDP-1", "profile": "ICC"}) + "\n")
            self.assertEqual(self.run_display(tmp, doctor, "remove"), 0)
            self.assertEqual(panel["profile"], "ICC")
            self.assertFalse(state.exists())

    def test_an_unreadable_state_file_does_not_wedge_apply(self):
        with tempfile.TemporaryDirectory() as tmp:
            panel, doctor = self.kscreen()
            state = Path(tmp) / "imac-patcher/kde-color.json"
            state.parent.mkdir(parents=True)
            state.write_text("{ truncated")
            self.assertEqual(self.run_display(tmp, doctor, "apply"), 0)
            self.assertEqual(panel["profile"], "EDID")
            self.assertEqual(json.loads(state.read_text())["profile"], "sRGB")


MOCK = r'''#!/usr/bin/env python3
import json, os, pathlib, sys
name = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]
root = pathlib.Path(os.environ['TEST_ROOT'])
with (root / 'calls').open('a') as log:
    log.write(json.dumps([name, *args]) + '\n')
if name == 'modinfo':
    if '-n' in args:
        print(root / 'modules-alias/updates/imac5k/amdgpu.ko.xz')
    elif 'vermagic' in args:
        print(('wrong' if args[-1].endswith('bad.ko') else os.environ['KREL']) + ' SMP mod_unload modversions ')
    elif 'parm' in args:
        print('tiled_stitch:Enable stitched mode (bool)')
elif name == 'grubby':
    store = root / 'args'
    current = store.read_text().split()
    if '--info' in args:
        print('args="' + ' '.join(current) + '"')
    else:
        assert args[0] == '--update-kernel' and args[1] == str(root / 'vmlinuz')
        if '--remove-args' in args:
            remove = args[args.index('--remove-args') + 1].split()
            current = [x for x in current if x not in remove]
        if '--args' in args:
            current.extend(args[args.index('--args') + 1].split())
        store.write_text(' '.join(current))
elif name == 'dracut':
    if os.environ.get('FAIL_DRACUT'):
        sys.exit(1)
    assert args[-1] == os.environ['KREL']
    (root / 'initramfs').write_text('rebuilt')
elif name == 'mokutil':
    print('SecureBoot disabled')
'''


class FedoraInstallTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "modules-alias").symlink_to(self.root / "modules")
        bindir = self.root / "bin"
        bindir.mkdir()
        for name in ("modinfo", "grubby", "dracut", "depmod", "mokutil", "strip"):
            file = bindir / name
            file.write_text(MOCK)
            file.chmod(0o755)
        for name, content in (("initramfs", "stock"), ("vmlinuz", "kernel"), ("good.ko", "module"), ("bad.ko", "module"),
                              ("args", "root=UUID=keep quiet video=eDP-1:3840x2160@60e video=DP-2:1920x1080")):
            (self.root / name).write_text(content)
        self.original_args = (self.root / "args").read_text()

    def run_backend(self, command, **env):
        script = r'''
source "$REPO/scripts/fedora-imac5k"
export PATH="$TEST_ROOT/bin:$PATH"
export KREL=7.1.13-200.fc44.x86_64
# KSERIES too: it is derived from the host's own uname at source time,
# and these tests must not depend on the kernel the runner happens to boot.
KSERIES=7.1
DEST=$TEST_ROOT/modules/updates/imac5k/amdgpu.ko.xz
DEPMOD_CONF=$TEST_ROOT/depmod/imac5k.conf
STATE=$TEST_ROOT/state
INITRD=$TEST_ROOT/initramfs
KERNEL=$TEST_ROOT/vmlinuz
need_root() { :; }
check_signing() { :; }
'''
        return subprocess.run(["bash", "-c", script + command], text=True, capture_output=True,
                              env={**os.environ, "REPO": str(ROOT), "TEST_ROOT": str(self.root), **env})

    def test_install_and_restore_preserve_stock_and_other_arguments(self):
        result = self.run_backend('install_module "$TEST_ROOT/good.ko"')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.root / "modules/updates/imac5k/amdgpu.ko.xz").exists())
        self.assertEqual((self.root / "state/initramfs.stock").read_text(), "stock")
        self.assertEqual((self.root / "args").read_text(), "root=UUID=keep quiet video=DP-2:1920x1080 amdgpu.tiled_stitch=1")
        result = self.run_backend('restore_module')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(set((self.root / "args").read_text().split()), set(self.original_args.split()))
        self.assertFalse((self.root / "modules/updates/imac5k/amdgpu.ko.xz").exists())
        self.assertFalse((self.root / "depmod/imac5k.conf").exists())

    def test_failed_initramfs_rolls_back(self):
        result = self.run_backend('install_module "$TEST_ROOT/good.ko"', FAIL_DRACUT="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.root / "initramfs").read_text(), "stock")
        self.assertEqual(set((self.root / "args").read_text().split()), set(self.original_args.split()))
        self.assertFalse((self.root / "modules/updates/imac5k/amdgpu.ko.xz").exists())

    def test_wrong_vermagic_changes_nothing(self):
        result = self.run_backend('install_module "$TEST_ROOT/bad.ko"')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("vermagic", result.stderr)
        self.assertFalse((self.root / "state").exists())
        self.assertEqual((self.root / "initramfs").read_text(), "stock")
        self.assertEqual((self.root / "args").read_text(), self.original_args)

    def test_reinstall_keeps_first_stock_backup(self):
        for _ in range(2):
            result = self.run_backend('install_module "$TEST_ROOT/good.ko"')
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.root / "state/initramfs.stock").read_text(), "stock")
        result = self.run_backend('restore_module')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(set((self.root / "args").read_text().split()), set(self.original_args.split()))


if __name__ == "__main__":
    unittest.main()
