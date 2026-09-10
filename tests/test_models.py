"""Model admission and module compatibility, without touching host settings."""
from pathlib import Path
import subprocess
import tempfile
import unittest

from test_patcher_menu import shell_function

ROOT = Path(__file__).resolve().parents[1]
PATCHER = (ROOT / "scripts/imac-patcher").read_text()
PLATFORM = (ROOT / "scripts/lib/platform.sh").read_text()
MODELS = ("iMac15,1", "iMac17,1", "iMac18,3", "iMac19,1",
          "iMac20,1", "iMac20,2", "iMacPro1,1")
OTHERS = ("iMac14,2", "iMac16,2", "iMac18,1", "iMac18,2",
          "iMac19,2", "iMac21,1", "Mac16,3", "MacBookPro14,3", "unknown")


def section(name, next_name):
    start = PATCHER.index(f"# ═══════════════════════ module: {name} ")
    return PATCHER[start:PATCHER.index(f"# ═══════════════════════ module: {next_name} ", start)]


class ModelTests(unittest.TestCase):
    def run_shell(self, model, code):
        return subprocess.run(
            ["bash", "-c", PLATFORM + '''
set -uo pipefail
product=$1
imac_product_name() { printf '%s\\n' "$product"; }
warn() { printf '%s\\n' "$*"; }
''' + code, "test", model], text=True, capture_output=True, timeout=10)

    def test_launcher_accepts_all_5k_models_and_rejects_other_macs(self):
        start = PATCHER.index("# ── hardware gate")
        gate = PATCHER[start:PATCHER.index("# ── core dependencies", start)]
        for model in MODELS + OTHERS:
            with self.subTest(model=model):
                result = self.run_shell(model, gate)
                self.assertEqual(result.returncode == 0, model in MODELS, result.stderr)

    def test_standalone_installer_uses_the_same_model_list(self):
        source = (ROOT / "install.sh").read_text()
        start = source.index("preflight() {")
        preflight = source[start:source.index("resolve_version() {", start)]
        for model in MODELS + OTHERS:
            with self.subTest(model=model):
                result = self.run_shell(model, preflight + '''
IMAC5K_ALLOW_ROOT=1
test_model=$product
cat() { printf '%s\\n' "$test_model"; }
preflight
''')
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual("patcher will refuse" in result.stdout, model in OTHERS)

    def test_audio_is_unavailable_on_other_models_before_any_install(self):
        audio = section("audio", "eq")
        for model in MODELS:
            with self.subTest(model=model):
                result = self.run_shell(model, "imac_audio_supported")
                self.assertEqual(result.returncode == 0, model == "iMac18,3")
                if model == "iMac18,3":
                    continue
                result = self.run_shell(model, f"CACHE=/tmp\nREPO_DIR='{ROOT}'\n" + audio + "mod_audio_detect\nmod_audio_apply")
                self.assertNotEqual(result.returncode, 0)
                self.assertTrue(result.stdout.startswith("n/a\n"), result.stdout)
                self.assertIn("existing audio driver", result.stdout)

    def test_eq_is_unavailable_on_the_imac_pro_whose_audio_is_the_t2(self):
        eq = section("eq", "color")
        for model in MODELS:
            with self.subTest(model=model):
                result = self.run_shell(model, "imac_eq_supported")
                self.assertEqual(result.returncode == 0, model != "iMacPro1,1")
        result = self.run_shell("iMacPro1,1", "SCRIPT_DIR=/nonexistent\nCACHE=/tmp\nLOGDIR=/tmp\nHOME=/tmp\npactl() { :; }\n" + eq + "mod_eq_detect\nmod_eq_apply")
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(result.stdout.startswith("n/a\n"), result.stdout)
        self.assertIn("T2 audio", result.stdout)

    def test_five_k_apply_sets_hyprland_to_10_bpc_on_the_active_output_only(self):
        start = PATCHER.index("# ═══════════════════════ module: 5k ")
        five_k = PATCHER[start:PATCHER.index("# ── boot helpers", start)]
        default = 'hl.monitor({ output = "", mode = "preferred", position = "auto", scale = omarchy_monitor_scale })\n'
        disabled = 'hl.monitor({ output = "DP-3", disabled = true })\n'
        cases = (("omarchy default", default + disabled, default.replace(" })", ", bitdepth = 10 })") + disabled),
                 ("already 8 bpc", default.replace(" })", ", bitdepth = 8 })"), default.replace(" })", ", bitdepth = 10 })")),
                 ("already 10 bpc", default.replace(" })", ", bitdepth = 10 })"), default.replace(" })", ", bitdepth = 10 })")))
        for name, before, after in cases:
            with self.subTest(case=name), tempfile.TemporaryDirectory() as tmp:
                lua = Path(tmp) / "monitors.lua"
                lua.write_text(before)
                result = self.run_shell("iMacPro1,1", f"MONITORS_LUA='{lua}'\nsay() {{ :; }}\n" + five_k + "five_k_set_10bpc && five_k_has_10bpc")
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(lua.read_text(), after)
        with tempfile.TemporaryDirectory() as tmp:
            result = self.run_shell("iMacPro1,1", f"MONITORS_LUA='{tmp}/absent.lua'\n" + five_k + "five_k_set_10bpc && five_k_has_10bpc")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for model, required in (("iMacPro1,1", 1), ("iMac18,3", 0)):
            with self.subTest(model=model), tempfile.TemporaryDirectory() as tmp:
                lua = Path(tmp) / "monitors.lua"; lua.write_text(default)
                result = self.run_shell(model, f"MONITORS_LUA='{lua}'\n" + five_k + "five_k_has_10bpc")
                self.assertEqual(result.returncode, required, f"{model}: 8 bpc must only count against the iMac Pro")

    def test_ten_bpc_ignores_comments_and_other_outputs(self):
        start = PATCHER.index("# ═══════════════════════ module: 5k ")
        five_k = PATCHER[start:PATCHER.index("# ── boot helpers", start)]
        active = 'hl.monitor({ output = "eDP-1", mode = "preferred", bitdepth = 8 })\n'
        unrelated = ('-- bitdepth = 10\n'
                     '--[[\nhl.monitor({ output = "eDP-1", bitdepth = 10 })\n]]\n'
                     'hl.monitor({ output = "DP-2", bitdepth = 10 })\n'
                     'hl.monitor({ output = "DP-3", disabled=true, bitdepth = 8 })\n'
                     'hl.monitor({ output = "", mode = "preferred", bitdepth = 8 })\n')
        with tempfile.TemporaryDirectory() as tmp:
            lua = Path(tmp) / "monitors.lua"
            before = unrelated + active
            lua.write_text(before)
            prelude = f"MONITORS_LUA='{lua}'\nsay() {{ :; }}\n" + five_k
            result = self.run_shell("iMacPro1,1", prelude + "five_k_has_10bpc")
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            result = self.run_shell("iMacPro1,1", prelude + "five_k_set_10bpc && five_k_has_10bpc")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(lua.read_text(), unrelated + active.replace("bitdepth = 8", "bitdepth = 10"))
            backups = list(Path(tmp).glob("*.bak-*"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_text(), before)
            self.assertEqual(self.run_shell("iMacPro1,1", prelude + "five_k_set_10bpc").returncode, 0)
            self.assertEqual(list(Path(tmp).glob("*.bak-*")), backups)

    def test_ten_bpc_keeps_other_models_monitor_settings(self):
        start = PATCHER.index("# ═══════════════════════ module: 5k ")
        five_k = PATCHER[start:PATCHER.index("# ── boot helpers", start)]
        with tempfile.TemporaryDirectory() as tmp:
            lua = Path(tmp) / "monitors.lua"
            before = 'hl.monitor({ output = "", bitdepth = 8 })\n'
            lua.write_text(before)
            for model in MODELS:
                if model == "iMacPro1,1":
                    continue
                with self.subTest(model=model):
                    result = self.run_shell(model, f"MONITORS_LUA='{lua}'\n" + five_k + "five_k_set_10bpc")
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(lua.read_text(), before)
            self.assertEqual(list(Path(tmp).glob("*.bak-*")), [])

    def test_ten_bpc_does_not_claim_success_for_an_unrecognised_panel_rule(self):
        start = PATCHER.index("# ═══════════════════════ module: 5k ")
        five_k = PATCHER[start:PATCHER.index("# ── boot helpers", start)]
        for before in ('-- bitdepth = 10\n',
                       'hl.monitor({ output = "eDP-1", disabled=true, bitdepth = 10 })\n',
                       'hl.monitor({\n output = "eDP-1", bitdepth = 8\n})\n'):
            with self.subTest(config=before), tempfile.TemporaryDirectory() as tmp:
                lua = Path(tmp) / "monitors.lua"
                lua.write_text(before)
                result = self.run_shell("iMacPro1,1", f"MONITORS_LUA='{lua}'\n" + five_k + "five_k_set_10bpc")
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(lua.read_text(), before)

    def test_default_uki_is_named_after_the_kernel_package(self):
        for pkgbase in ("linux", "linux-t2", "linux-lts"):
            with self.subTest(pkgbase=pkgbase):
                result = self.run_shell("iMacPro1,1", f"imac_kernel_pkgbase() {{ echo {pkgbase}; }}\nimac_default_uki 7.1.8-arch1-1")
                self.assertEqual(result.stdout.strip(), f"/boot/EFI/Linux/omarchy_{pkgbase}.efi")
        result = self.run_shell("iMac18,3", "imac_default_uki 0.0.0-nonexistent")
        self.assertEqual(result.stdout.strip(), "/boot/EFI/Linux/omarchy_linux.efi")

    def test_fedora_sets_panel_depth_only_after_a_successful_driver_install(self):
        start = PATCHER.index("# ═══════════════════════ module: 5k ")
        five_k = PATCHER[start:PATCHER.index("# ── boot helpers", start)]
        backend = (ROOT / "scripts/lib/fedora.sh").read_text()
        for status in (0, 1):
            with self.subTest(installer_status=status), tempfile.TemporaryDirectory() as tmp:
                lua = Path(tmp) / "monitors.lua"
                before = 'hl.monitor({ output = "eDP-1", bitdepth = 8 })\n'
                lua.write_text(before)
                installer = Path(tmp) / "fedora-imac5k"
                installer.write_text(f"#!/usr/bin/env bash\nexit {status}\n")
                installer.chmod(0o755)
                result = self.run_shell("iMacPro1,1", five_k + backend + f'''
MONITORS_LUA='{lua}'
SCRIPT_DIR='{tmp}'
LOGDIR='{tmp}'
KREL=test
say() {{ :; }}
confirm() {{ return 0; }}
mod_5k_preflight() {{ return 0; }}
mod_5k_apply
''')
                self.assertEqual(result.returncode, status, result.stdout + result.stderr)
                self.assertEqual(lua.read_text(), before if status else before.replace("8", "10"))

    def test_default_uki_rejects_invalid_kernel_metadata(self):
        result = self.run_shell("iMacPro1,1", "imac_kernel_pkgbase() { return 1; }\nimac_default_uki test")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_fedora_audio_retains_the_board_restriction(self):
        backend = (ROOT / "scripts/lib/fedora.sh").read_text()
        result = self.run_shell("iMac19,1", backend + '''
fedora_mutable() { return 0; }
fedora_deps() { echo UNEXPECTED-INSTALL; }
mod_audio_apply
''')
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("UNEXPECTED-INSTALL", result.stdout)
        self.assertIn("existing audio driver", result.stdout)

    def test_early_panel_is_not_forced_to_p3(self):
        result = self.run_shell("iMac15,1", section("color", "suspend") + "mod_color_detect\nmod_color_apply")
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(result.stdout.startswith("n/a\n"))
        self.assertIn("should not be forced", result.stdout)

    def test_display_preflight_rejects_other_gpu_drivers_before_dependencies(self):
        for backend in (PATCHER[PATCHER.index("mod_5k_preflight() {"):PATCHER.index("mod_5k_apply() {")],
                        (ROOT / "scripts/lib/fedora.sh").read_text()):
            with self.subTest(backend=backend[:40]):
                result = self.run_shell("iMac17,1", backend + '''
imac_has_amdgpu() { return 1; }
mod_5k_preflight
''')
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("requires a GPU using amdgpu", result.stdout)

    def test_fedora_display_gate_accepts_the_whole_family_and_allows_recovery(self):
        source = (ROOT / "scripts/fedora-imac5k").read_text()
        start = source.index('imac_is_retina5k || die')
        gate = source[start:source.index('case ${1:-} in', start)]
        for model in MODELS + OTHERS:
            with self.subTest(model=model):
                result = self.run_shell(model, '''
die() { echo "$*"; exit 1; }
imac_has_amdgpu() { return 0; }
''' + gate)
                self.assertEqual(result.returncode == 0, model in MODELS, result.stdout)
        result = self.run_shell("iMac17,1", '''
die() { echo "$*"; exit 1; }
imac_has_amdgpu() { return 1; }
set -- --restore
''' + gate)
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_gpu_probe_requires_amdgpu_instead_of_just_any_drm_device(self):
        for driver in ("amdgpu", "radeon", "i915", "nouveau"):
            with self.subTest(driver=driver):
                result = self.run_shell("iMac15,1", f'''
readlink() {{ echo /sys/bus/pci/drivers/{driver}; }}
imac_has_amdgpu
''')
                self.assertEqual(result.returncode == 0, driver == "amdgpu")


    def test_stitched_mode_probe_reads_the_panel_not_the_compositor(self):
        """The 5K module read `partial` on KDE because it probed hyprctl."""
        for modes, expected in (("5120x2880", 0), ("2560x2880", 1), ("", 1)):
            with self.subTest(modes=modes or "none"):
                with tempfile.TemporaryDirectory() as drm:
                    panel = Path(drm) / "card1-eDP-1"
                    panel.mkdir()
                    (panel / "modes").write_text(
                        modes + "\n1920x1080\n" if modes else "")
                    result = self.run_shell("iMac18,3",
                                            "IMAC_DRM_DIR=%s\nimac_panel_has_stitched_mode\n" % drm)
                    self.assertEqual(result.returncode, expected, result.stderr)

    def test_five_k_detect_reports_applied_without_a_compositor_query(self):
        detect = PATCHER[PATCHER.index("mod_5k_detect() {"):
                         PATCHER.index("mod_5k_preflight() {")]
        self.assertNotIn("hyprctl", detect)
        for stitched, expected in (("return 0", "applied"), ("return 1", "partial")):
            with self.subTest(stitched=stitched):
                result = self.run_shell("iMac18,3", detect + """
KREL=test
find() { echo /lib/modules/test/amdgpu.ko.zst.stock-backup; }
grep() { return 0; }
boot_config_has() { return 0; }
imac_panel_has_stitched_mode() { %s; }
mod_5k_detect
""" % stitched)
                self.assertEqual(result.stdout.strip(), expected, result.stderr)


    def test_eq_repo_plugin_is_named_per_distribution_and_queued_for_startup(self):
        """lsp-plugins-lv2 is the Arch name; Fedora ships it as lsp-plugins."""
        code = (shell_function(PATCHER, "eq_lsp_package") + "\n"
                + shell_function(PATCHER, "eq_prereq_note") + "\n")
        for fedora, expected in ((False, "lsp-plugins-lv2"), (True, "lsp-plugins")):
            with self.subTest(fedora=fedora):
                result = self.run_shell("iMac18,3", """
imac_is_fedora() { return %d; }
STARTUP_MISSING_PACKAGES=()
eq_have_lv2() { return 1; }
""" % (0 if fedora else 1) + code + """
eq_prereq_note not-applied
printf 'QUEUED %s\\n' "${STARTUP_MISSING_PACKAGES[*]}"
""")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(f"eq needs {expected} bankstown(built from source)", result.stdout)
                # Only the repository half is queued; bankstown is a source build.
                self.assertIn(f"QUEUED {expected}", result.stdout)
                self.assertNotIn("bankstown", result.stdout.split("QUEUED")[1])

    def test_colour_apply_refuses_while_the_stitch_is_only_configured(self):
        """Applied before the stitch reboot, KDE drops the profile with the old panel."""
        kde = (ROOT / "scripts/lib/kde.sh").read_text()
        cases = (("configured, not yet live", 0, 1, 1),
                 ("configured and live", 0, 0, 0),
                 ("never configured", 1, 1, 0))
        for name, configured, stitched, expected in cases:
            with self.subTest(case=name):
                result = self.run_shell("iMac18,3", """
SCRIPT_DIR=/nonexistent
boot_config_has() { return %d; }
imac_panel_has_stitched_mode() { return %d; }
python3() { echo APPLIED; }
""" % (configured, stitched) + kde + """
mod_color_apply
""")
                self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
                if expected:
                    self.assertIn("5K stitch is configured but not active yet", result.stdout)
                    self.assertIn("--apply color", result.stdout)
                    self.assertNotIn("APPLIED", result.stdout)
                else:
                    self.assertIn("APPLIED", result.stdout)

    def test_applying_5k_tells_kde_users_to_re_apply_colour_after_the_reboot(self):
        kde = (ROOT / "scripts/lib/kde.sh").read_text()
        for state, expected in (("applied", True), ("not-applied", False)):
            with self.subTest(colour=state):
                result = self.run_shell("iMac18,3", """
SCRIPT_DIR=/nonexistent
mod_color_detect() { echo %s; }
""" % state + kde + """
mod_color_detect() { echo %s; }
color_note_after_5k
""" % state)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual("Re-apply the colour module" in result.stdout, expected)

if __name__ == "__main__":
    unittest.main()
