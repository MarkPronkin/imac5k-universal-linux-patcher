"""The HDR (EDR) module: wrapper configuration, launcher, detection, ownership.

Hyprland, ldd and the build are simulated; nothing touches the desktop. The
wrapper configuration runs in a real Lua interpreter when one is installed,
and the session entry is checked by uwsm's own validation when uwsm is.
"""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("hypr_edr", ROOT / "scripts/hypr-edr.py")
edr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(edr)
LUA = shutil.which("lua5.5") or shutil.which("lua")
UWSM = Path("/usr/share/uwsm/modules")
LIBRARIES = {"libhyprutils.so.13": "/usr/lib/libhyprutils.so.0.14.2",
             "libaquamarine.so.14": "/usr/lib/libaquamarine.so.0.15.0",
             "libc.so.6": "/usr/lib/libc.so.6"}
PROFILE = {"cm": "edr", "bitdepth": 10, "supports_hdr": -1, "output": "eDP-1"}

# Records every hl.monitor call. Hyprland resolves require() of an absolute
# path itself; plain Lua needs a searcher for that.
HARNESS = r'''
local calls = {}
hl = { monitor = function(rule) calls[#calls + 1] = rule end }
table.insert(package.searchers, 2, function(name)
  if name:sub(1, 1) == "/" then
    local loader, problem = loadfile(name)
    return loader or problem, name
  end
end)
dofile(arg[1])
if LATER then LATER() end
for _, rule in ipairs(calls) do
  local keys, parts = {}, {}
  for key in pairs(rule) do keys[#keys + 1] = key end
  table.sort(keys)
  for _, key in ipairs(keys) do
    local value = rule[key]
    parts[#parts + 1] = string.format("%q:%s", key, type(value) == "string" and string.format("%q", value) or tostring(value))
  end
  print("{" .. table.concat(parts, ",") .. "}")
end
'''


@unittest.skipUnless(LUA, "needs a Lua interpreter")
class WrapperConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        (self.dir / "hypr").mkdir()
        self.user = self.dir / "hypr/hyprland.lua"
        self.harness = self.dir / "harness.lua"
        self.harness.write_text(HARNESS)
        self.wrapper = self.dir / "wrapper.lua"
        self.wrapper.write_text(edr.render_config(self.user))

    def rules(self, user, **modules):
        self.user.write_text(textwrap.dedent(user))
        for name, text in modules.items():
            (self.dir / f"hypr/{name}.lua").write_text(textwrap.dedent(text))
        result = subprocess.run([LUA, str(self.harness), str(self.wrapper)], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        return [json.loads(line) for line in result.stdout.splitlines()]

    def test_panel_rule_keeps_user_fields_and_gains_the_profile(self):
        rules = self.rules('''
            hl.monitor({ output = "", mode = "preferred", position = "auto", scale = "auto" })
            local rule = { output = "eDP-1", mode = "preferred", position = "auto", scale = "auto", cm = "dp3" }
            hl.monitor(rule)
            assert(rule.cm == "dp3", "the user's own table must not change")
        ''')
        self.assertEqual(rules, [
            {"output": "", "mode": "preferred", "position": "auto", "scale": "auto"},
            {**PROFILE, "mode": "preferred", "position": "auto", "scale": "auto",
             "max_luminance": 500, "sdr_max_luminance": 200},
        ])

    def test_catch_all_alone_gets_a_panel_rule_built_from_it(self):
        rules = self.rules('hl.monitor({ output = "", mode = "preferred", position = "auto", scale = 2 })\n')
        self.assertEqual(rules, [
            {"output": "", "mode": "preferred", "position": "auto", "scale": 2},
            {**PROFILE, "mode": "preferred", "position": "auto", "scale": 2,
             "max_luminance": 500, "sdr_max_luminance": 200},
        ])

    def test_no_monitor_rules_at_all(self):
        self.assertEqual(self.rules("-- nothing\n"), [
            {**PROFILE, "mode": "preferred", "position": "auto", "scale": "auto",
             "max_luminance": 500, "sdr_max_luminance": 200},
        ])

    def test_user_luminances_win_but_colour_mode_and_depth_are_forced(self):
        rules = self.rules('''
            hl.monitor({ output = "eDP-1", mode = "preferred", position = "0x0", scale = 1.5, cm = "srgb",
                         bitdepth = 8, supports_hdr = 1, sdr_max_luminance = 160, max_luminance = 450 })
        ''')
        self.assertEqual(rules, [
            {**PROFILE, "mode": "preferred", "position": "0x0", "scale": 1.5,
             "max_luminance": 450, "sdr_max_luminance": 160},
        ])

    def test_other_outputs_pass_through_unchanged(self):
        rules = self.rules('''
            hl.monitor({ output = "DP-1", mode = "preferred", position = "auto", scale = "auto" })
            hl.monitor({ output = "HDMI-A-1", mode = "preferred", position = "auto", scale = 1, cm = "hdr" })
            hl.monitor({ output = "eDP-1", mode = "preferred", position = "auto", scale = 2 })
        ''')
        self.assertEqual(rules[:2], [
            {"output": "DP-1", "mode": "preferred", "position": "auto", "scale": "auto"},
            {"output": "HDMI-A-1", "mode": "preferred", "position": "auto", "scale": 1, "cm": "hdr"},
        ])
        self.assertEqual(len(rules), 3)
        self.assertEqual(rules[2]["cm"], "edr")

    def test_relative_modules_resolve_from_the_user_directory(self):
        rules = self.rules('require("monitors")\n', monitors='''
            hl.monitor({ output = "eDP-1", mode = "preferred", position = "auto", scale = 2, cm = "dp3" })
        ''')
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0]["cm"], "edr")

    def test_rules_added_after_loading_still_get_the_profile(self):
        rules = self.rules('''
            hl.monitor({ output = "eDP-1", mode = "preferred", position = "auto", scale = 2 })
            function LATER() hl.monitor({ output = "eDP-1", mode = "preferred", position = "auto", scale = 1 }) end
        ''')
        self.assertEqual([(rule["scale"], rule["cm"]) for rule in rules], [(2, "edr"), (1, "edr")])


class Install:
    """A fake install in a temporary home, with Hyprland and ldd simulated."""

    def __init__(self, case):
        self.tmp = tempfile.TemporaryDirectory()
        case.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.desktop = edr.Desktop(base / "data", base / "config", base / "cache")
        self.desktop.user_config.parent.mkdir(parents=True)
        self.desktop.user_config.write_text("-- user configuration\n")
        self.stock = "0.56.2"
        self.libraries = dict(LIBRARIES)
        self.missing = []
        for patcher in (patch.object(edr, "stock_version", lambda *a, **k: self.stock),
                        patch.object(edr, "linked", lambda *a, **k: (dict(self.libraries), list(self.missing))),
                        patch.object(edr.Desktop, "platform_problems", lambda desktop: [])):
            patcher.start()
            case.addCleanup(patcher.stop)

    def write(self, entry=True):
        d = self.desktop
        d.root.mkdir(parents=True, exist_ok=True)
        d.binary.write_text("#!/bin/sh\n")
        d.binary.chmod(0o755)
        for path, (text, mode) in d.scripts().items():
            path.write_text(text)
            path.chmod(mode)
        d.record.write_text(json.dumps({"version": "0.56.2", "patch_sha256": edr.digest(edr.PATCH),
                                        "libraries": edr.abi(LIBRARIES)}))
        if entry:
            d.entry.parent.mkdir(parents=True, exist_ok=True)
            d.entry.write_text(edr.render_entry(d.launch))


class StateTests(unittest.TestCase):
    def test_states_without_an_install(self):
        install = Install(self)
        self.assertEqual(install.desktop.state("iMac18,3"), "not-applied")
        for model in ("iMacPro1,1", "iMac17,1", "iMac19,1", ""):
            self.assertEqual(install.desktop.state(model), "n/a")

    def test_complete_install_is_applied_and_may_start(self):
        install = Install(self)
        install.write()
        self.assertEqual(install.desktop.check(), [])
        self.assertEqual(install.desktop.problems(), [])
        self.assertEqual(install.desktop.state("iMac18,3"), "applied")

    def test_install_on_another_model_stays_removable(self):
        install = Install(self)
        install.write()
        self.assertEqual(install.desktop.state("iMacPro1,1"), "partial")
        self.assertIn("remove", install.desktop.note("iMacPro1,1")[0])

    def test_upgraded_hyprland_stops_the_build_from_starting(self):
        install = Install(self)
        install.write()
        install.stock = "0.57.0"
        problems = install.desktop.check()
        self.assertEqual(len(problems), 1)
        self.assertIn("0.57.0", problems[0])
        self.assertEqual(install.desktop.state("iMac18,3"), "partial")

    def test_changed_or_missing_hyprland_libraries_stop_it_too(self):
        install = Install(self)
        install.write()
        install.libraries["libhyprutils.so.13"] = "/usr/lib/libhyprutils.so.0.14.3"
        self.assertIn("rebuild", install.desktop.check()[0])
        install.libraries = dict(LIBRARIES)
        install.missing = ["libhyprlang.so.2"]
        self.assertIn("libhyprlang.so.2", install.desktop.check()[0])

    def test_other_library_updates_do_not(self):
        install = Install(self)
        install.write()
        install.libraries["libc.so.6"] = "/usr/lib/libc-2.44.so"
        self.assertEqual(install.desktop.check(), [])

    def test_incomplete_install_is_partial_and_never_started(self):
        for missing in ("binary", "config", "record"):
            with self.subTest(missing=missing):
                install = Install(self)
                install.write()
                getattr(install.desktop, missing).unlink()
                self.assertTrue(install.desktop.check())
                self.assertEqual(install.desktop.state("iMac18,3"), "partial")

    def test_entry_and_release_mismatches_are_partial_but_may_start(self):
        install = Install(self)
        install.write(entry=False)
        self.assertEqual(install.desktop.state("iMac18,3"), "partial")
        install.desktop.entry.parent.mkdir(parents=True)
        install.desktop.entry.write_text(edr.render_entry(install.desktop.launch))
        install.desktop.launch.write_text("#!/bin/bash\n# from an older release\n")
        self.assertEqual(install.desktop.check(), [])
        self.assertIn("another imac-patcher release", " ".join(install.desktop.problems()))
        self.assertEqual(install.desktop.state("iMac18,3"), "partial")

    def test_build_from_an_earlier_patch_is_partial(self):
        install = Install(self)
        install.write()
        record = json.loads(install.desktop.record.read_text())
        install.desktop.record.write_text(json.dumps({**record, "patch_sha256": "0" * 64}))
        self.assertIn("earlier patch", " ".join(install.desktop.problems()))
        self.assertFalse(install.desktop.reusable())

    def test_foreign_entry_is_never_counted_as_ours(self):
        install = Install(self)
        install.desktop.entry.parent.mkdir(parents=True)
        install.desktop.entry.write_text("[Desktop Entry]\nName=Mine\nExec=/usr/bin/start-hyprland\n")
        self.assertEqual(install.desktop.state("iMac18,3"), "not-applied")
        install.write(entry=False)
        self.assertIn("not imac-patcher's", " ".join(install.desktop.problems()))


class PlatformTests(unittest.TestCase):
    def test_needs_lua_configuration_start_hyprland_and_uwsm(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            desktop = edr.Desktop(base / "data", base / "config", base / "cache")
            start = base / "start-hyprland"
            with patch.object(edr, "STOCK_START", str(start)), patch.object(edr.shutil, "which", lambda name: None):
                self.assertEqual(len(desktop.platform_problems()), 3)
                self.assertEqual(desktop.state("iMac18,3"), "n/a")
                desktop.user_config.parent.mkdir(parents=True)
                desktop.user_config.write_text("")
                start.write_text("")
                self.assertEqual(len(desktop.platform_problems()), 1)
            with patch.object(edr, "STOCK_START", str(start)), patch.object(edr.shutil, "which", lambda name: "/usr/bin/" + name):
                self.assertEqual(desktop.platform_problems(), [])


class ApplyRemoveTests(unittest.TestCase):
    def setUp(self):
        self.install = Install(self)
        self.desktop = self.install.desktop
        build = Path(self.install.tmp.name) / "build"
        self.built = build / "Hyprland"
        self.make_build()
        self.compiled = 0
        patcher = patch.dict(os.environ, {"VERIFY": "config ok"})
        patcher.start()
        self.addCleanup(patcher.stop)

        def compile(desktop, jobs):
            self.compiled += 1
            return build, self.built
        patcher = patch.object(edr.Desktop, "compile", compile)
        patcher.start()
        self.addCleanup(patcher.stop)

    def make_build(self):
        self.built.parent.mkdir()
        self.built.write_text('#!/bin/sh\n[ "$1" = --verify-config ] && echo "$VERIFY"\nexit 0\n')
        self.built.chmod(0o755)

    def apply(self):
        with patch("sys.stdout"):
            self.desktop.apply("iMac18,3", jobs=1)

    def test_apply_installs_everything_then_reuses_the_build(self):
        built = self.built.read_bytes()
        self.apply()
        self.assertEqual(self.compiled, 1)
        self.assertEqual(self.desktop.state("iMac18,3"), "applied")
        self.assertEqual(self.desktop.binary.read_bytes(), built)
        self.assertTrue(os.access(self.desktop.launch, os.X_OK))
        record = json.loads(self.desktop.record.read_text())
        self.assertEqual(record["libraries"], edr.abi(LIBRARIES))
        self.assertFalse(self.built.parent.exists(), "the build tree is removed after installing")
        self.apply()
        self.assertEqual(self.compiled, 1)
        self.assertEqual(json.loads(self.desktop.record.read_text())["built"], record["built"])

    def test_library_update_makes_apply_rebuild(self):
        self.apply()
        self.install.libraries["libaquamarine.so.14"] = "/usr/lib/libaquamarine.so.0.15.1"
        self.make_build()
        self.apply()
        self.assertEqual(self.compiled, 2)
        self.assertEqual(self.desktop.state("iMac18,3"), "applied")

    def test_configuration_that_does_not_verify_installs_nothing(self):
        os.environ["VERIFY"] = "error: something"
        with self.assertRaises(ValueError):
            self.apply()
        self.assertFalse(self.desktop.entry.exists())
        self.assertFalse(self.desktop.binary.exists())

    def test_preflight_refusals(self):
        with self.assertRaisesRegex(ValueError, "iMac18,3"):
            self.desktop.apply("iMacPro1,1")
        self.install.stock = "0.57.0"
        with self.assertRaisesRegex(ValueError, "0.57.0"):
            self.desktop.apply("iMac18,3")
        self.install.stock = "0.56.2"
        self.desktop.entry.parent.mkdir(parents=True)
        self.desktop.entry.write_text("[Desktop Entry]\nName=Mine\n")
        with self.assertRaisesRegex(ValueError, "your own session entry"):
            self.desktop.apply("iMac18,3")
        self.assertEqual(self.compiled, 0)
        self.assertEqual(self.desktop.entry.read_text(), "[Desktop Entry]\nName=Mine\n")

    def test_path_a_session_entry_cannot_hold_is_refused(self):
        base = Path(self.install.tmp.name)
        desktop = edr.Desktop(base / "my data", base / "config", base / "cache")
        with self.assertRaisesRegex(ValueError, "cannot start"):
            desktop.apply("iMac18,3")

    def test_remove_takes_out_everything_but_a_foreign_entry(self):
        self.apply()
        (self.desktop.cache / "downloads").mkdir(parents=True)
        with patch("sys.stdout"):
            self.desktop.remove()
        self.assertEqual(self.desktop.installed(), [])
        self.assertFalse(self.desktop.root.exists())
        self.assertFalse(self.desktop.cache.exists())
        self.assertEqual(self.desktop.state("iMac18,3"), "not-applied")
        self.desktop.entry.write_text("[Desktop Entry]\nName=Mine\n")
        with patch("sys.stdout"), patch("sys.stderr"):
            self.desktop.remove()
        self.assertTrue(self.desktop.entry.exists())


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.root = base / "hdr"
        self.root.mkdir()
        self.bin = base / "bin"
        self.bin.mkdir()
        self.log = base / "log"
        for name in ("start-hyprland", "setsid"):
            stub = self.bin / name
            stub.write_text(f'#!/bin/sh\nprintf "{name}" >>"{self.log}"\nfor a; do printf " [%s]" "$a" >>"{self.log}"; done\necho >>"{self.log}"\n')
            stub.chmod(0o755)
        launch = self.root / "launch"
        launch.write_text(edr.render_launch(self.root, stock=str(self.bin / "start-hyprland")))
        launch.chmod(0o755)

    def run_launch(self, check=None):
        if check is not None:
            (self.root / "hypr-edr.py").write_text(check)
        env = {**os.environ, "PATH": f"{self.bin}:{os.environ['PATH']}"}
        result = subprocess.run([str(self.root / "launch")], env=env, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        return self.log.read_text().splitlines()

    def test_passing_check_starts_the_build_with_the_wrapper(self):
        lines = self.run_launch("import sys; sys.exit(0)\n")
        self.assertEqual(lines, [f"start-hyprland [--path] [{self.root}/Hyprland] [--] [--config] [{self.root}/hyprland.lua]"])

    def test_failing_check_starts_stock_and_says_why(self):
        lines = self.run_launch("print('noise'); print('the system Hyprland is 0.57.0'); raise SystemExit(1)\n")
        self.assertEqual(lines[-1], "start-hyprland")
        self.assertIn("This login uses the stock compositor: the system Hyprland is 0.57.0.", lines[0])
        self.assertTrue(lines[0].startswith("setsid [-f] [sh]"))

    def test_missing_helper_starts_stock(self):
        self.assertEqual(self.run_launch()[-1], "start-hyprland")


class EntryTests(unittest.TestCase):
    def test_entry_shape(self):
        text = edr.render_entry(Path("/home/user/.local/share/imac-patcher/hdr/launch"))
        self.assertIn("Exec=/home/user/.local/share/imac-patcher/hdr/launch\n", text)
        self.assertNotIn("TryExec", text)
        self.assertIn("DesktopNames=Hyprland\n", text)
        self.assertTrue(text.rstrip().endswith(f"{edr.MARKER}=1"))

    @unittest.skipUnless((UWSM / "uwsm/main.py").is_file(), "needs uwsm")
    def test_uwsm_accepts_the_entry(self):
        # uwsm fails the login on an entry it rejects, so check with its own code.
        with tempfile.TemporaryDirectory() as tmp:
            launch = Path(tmp) / "launch"
            launch.write_text("#!/bin/sh\n")
            launch.chmod(0o755)
            entry = Path(tmp) / "hyprland.desktop"
            entry.write_text(edr.render_entry(launch))
            code = ("import sys; sys.argv = ['uwsm']; from uwsm.main import entry_parser_by_ids; "
                    f"print(entry_parser_by_ids('hyprland.desktop', {str(entry)!r}, 'hyprland.desktop', None)[0])")
            result = subprocess.run([sys.executable, "-c", code], env={**os.environ, "PYTHONPATH": str(UWSM)},
                                    capture_output=True, text=True, timeout=30)
            if "No module named 'xdg'" in result.stderr:
                self.skipTest("needs pyxdg")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip().splitlines()[-1], "return")


class LinkedTests(unittest.TestCase):
    def test_parses_ldd_output(self):
        output = ("\tlinux-vdso.so.1 (0x00007ffd)\n"
                  "\tlibhyprutils.so.13 => /usr/lib/libhyprutils.so.13 (0x00007f00)\n"
                  "\tlibhyprlang.so.2 => not found\n"
                  "\t/lib64/ld-linux-x86-64.so.2 => /usr/lib64/ld-linux-x86-64.so.2 (0x00007f01)\n")
        done = subprocess.CompletedProcess([], 0, output, "")
        with patch.object(edr.subprocess, "run", return_value=done), \
             patch.object(edr.os.path, "realpath", lambda path: path + ".real"):
            resolved, missing = edr.linked(Path("x"))
        self.assertEqual(missing, ["libhyprlang.so.2"])
        self.assertEqual(resolved["libhyprutils.so.13"], "/usr/lib/libhyprutils.so.13.real")
        self.assertEqual(edr.abi(resolved), {"libhyprutils.so.13": "/usr/lib/libhyprutils.so.13.real"})


if __name__ == "__main__":
    unittest.main()
