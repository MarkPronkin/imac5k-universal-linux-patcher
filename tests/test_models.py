"""Model admission and module compatibility, without touching host settings."""
from pathlib import Path
import subprocess
import unittest

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


if __name__ == "__main__":
    unittest.main()
