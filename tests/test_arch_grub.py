"""Arch-family module overrides against temporary boot files and fake tools."""
from pathlib import Path
import unittest

import test_grub as fixture
from test_patcher_menu import shell_function

ROOT = Path(__file__).resolve().parents[1]
PATCHER = (ROOT / "scripts/imac-patcher").read_text()


class ArchGrubTests(unittest.TestCase):
    setUp = fixture.GrubLibTests.setUp
    mkconfig_calls = fixture.GrubLibTests.mkconfig_calls

    def run_backend(self, code):
        base = "\n".join(shell_function(PATCHER, name) for name in (
            "mod_suspend_tier", "mod_suspend_detect", "mod_suspend_apply", "mod_suspend_remove",
            "hibernation_setup_present", "suspend_remove_hibernation",
            "suspend_ensure_s2idle", "suspend_drop_s2idle",
            "mod_5k_apply", "mod_5k_remove"))
        return fixture.GrubLibTests.run_grub(self, base + f'''
SCRIPT_DIR="{ROOT / 'scripts'}"
NO_CSTATES_PARAM=idle=poll
S2IDLE_PARAM=mem_sleep_default=s2idle
VIDEO_4K='video=eDP-1:3840x2160@60e'
HIBERNATE_TARGETS=(hibernate.target hybrid-sleep.target suspend-then-hibernate.target)
TB_SLEEP_HOOK="{self.tmp.name}/imac-tb-sleep-hook"
HIBERNATE_HOOK_CONF="{self.tmp.name}/omarchy_resume.conf"
HIBERNATE_DROPIN="{self.tmp.name}/resume.conf"
sudo() {{ "$@"; }}
mkinitcpio() {{ printf 'mkinitcpio %s\\n' "$*" >> "$GRUB_CALLS"; }}
limine-mkinitcpio() {{ echo WRONG_BACKEND >&2; return 99; }}
systemctl() {{ if [[ $1 == is-enabled ]]; then if [[ $2 == suspend.target ]]; then echo static; else echo masked; fi; else echo "systemctl $*"; fi; }}
source "$SCRIPT_DIR/lib/arch-grub.sh"
''' + code)

    def test_boot_repair_is_unavailable(self):
        result = self.run_backend("mod_boot_detect")
        self.assertEqual(result.stdout.strip(), "n/a", result.stderr)
        result = self.run_backend("mod_boot_apply")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.mkconfig_calls(), "")

    def test_fallback_roundtrip_preserves_unrelated_video_options(self):
        self.default.write_text('GRUB_CMDLINE_LINUX_DEFAULT="quiet video=DP-2:1920x1080"\n')
        result = self.run_backend('add_4k_fallback && boot_config_has "$VIDEO_4K" && remove_4k_fallback')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("video=DP-2:1920x1080", self.default.read_text())
        self.assertNotIn("video=eDP-1", self.default.read_text())

    def test_suspend_cleans_stale_parameter_and_keeps_sleep_masks(self):
        self.default.write_text("GRUB_CMDLINE_LINUX_DEFAULT='quiet idle=poll'\n")
        # The stubbed grub-mkconfig only logs; seed grub.cfg the way a real
        # regeneration from the edited default would leave it.
        self.cfg.write_text(fixture.GRUB_CFG.replace("quiet", "quiet mem_sleep_default=s2idle"))
        result = self.run_backend("mod_suspend_tier; mod_suspend_detect; mod_suspend_apply")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines()[:2], ["boot", "partial"])
        self.assertIn("systemctl unmask suspend.target", result.stdout)
        self.assertIn("systemctl mask hibernate.target hybrid-sleep.target suspend-then-hibernate.target", result.stdout)
        self.assertNotIn("idle=poll", self.default.read_text())
        self.assertIn("mem_sleep_default=s2idle", self.default.read_text())
        self.assertIn("grub-mkconfig", self.mkconfig_calls())
        self.assertNotIn("mkinitcpio", self.mkconfig_calls())

    def test_clean_suspend_config_needs_no_grub_regeneration(self):
        self.default.write_text('GRUB_CMDLINE_LINUX_DEFAULT="quiet mem_sleep_default=s2idle"\n')
        result = self.run_backend('''
install -m755 /dev/null "$TB_SLEEP_HOOK"
mod_suspend_tier; mod_suspend_detect; mod_suspend_apply
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines()[:2], ["safe", "applied"])
        self.assertEqual(self.mkconfig_calls(), "")

    def test_missing_s2idle_default_is_added_with_regeneration(self):
        # The stubbed grub-mkconfig only logs; seed grub.cfg the way a real
        # regeneration from the edited default would leave it.
        self.cfg.write_text(fixture.GRUB_CFG.replace("quiet", "quiet mem_sleep_default=s2idle"))
        result = self.run_backend('''
install -m755 /dev/null "$TB_SLEEP_HOOK"
mod_suspend_tier; mod_suspend_detect; mod_suspend_apply
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines()[:2], ["boot", "partial"])
        self.assertIn("mem_sleep_default=s2idle", self.default.read_text())
        self.assertIn("grub-mkconfig", self.mkconfig_calls())
        self.assertNotIn("mkinitcpio", self.mkconfig_calls())

    def test_verification_checks_exact_tokens_and_rejects_missing_entry(self):
        for args, status in (("quiet ''", 0), ("qui ''", 1), ("'' qui", 0), ("'' quiet", 1)):
            with self.subTest(args=args):
                result = self.run_backend("verify_cmdline " + args)
                self.assertEqual(result.returncode, status, result.stderr)
        self.cfg.write_text("")
        result = self.run_backend("verify_cmdline '' amdgpu.tiled_stitch=1")
        self.assertNotEqual(result.returncode, 0)

    def test_sync_and_audio_never_invoke_installed_limine_tool(self):
        result = self.run_backend("sync_boot_files && audio_refresh_initramfs")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("WRONG_BACKEND", result.stderr)
        calls = self.mkconfig_calls().splitlines()
        self.assertEqual(calls[0], "mkinitcpio -P")
        self.assertTrue(calls[1].startswith("grub-mkconfig -o "))
        self.assertEqual(calls[2], "mkinitcpio -P")

    def test_rebuild_failure_stops_sync_before_grub_regeneration(self):
        result = self.run_backend("mkinitcpio() { return 1; }; sync_boot_files")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.mkconfig_calls(), "")

    def test_5k_apply_propagates_failed_rebuild(self):
        result = self.run_backend('''
mod_5k_preflight() { return 0; }
confirm() { return 0; }
INSTALLER_5K=true
LOGDIR="$(dirname "$GRUB_CALLS")"
mkinitcpio() { return 1; }
mod_5k_apply
''')
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("reboot to activate", result.stdout)

    def test_5k_remove_uses_grub_cleanup_and_propagates_verification_failure(self):
        self.default.write_text('GRUB_CMDLINE_LINUX_DEFAULT="amdgpu.tiled_stitch=1"\n')
        self.cfg.write_text(fixture.GRUB_CFG.replace("quiet", "quiet amdgpu.tiled_stitch=1"))
        result = self.run_backend('''
INSTALLER_5K=true
confirm() { return 1; }
mod_5k_remove
''')
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("amdgpu.tiled_stitch=1", self.default.read_text())
        self.assertNotIn("reboot to return to stock", result.stdout)
        self.assertNotIn("unbound variable", result.stderr)


class ArchGrubBuildTests(unittest.TestCase):
    """The real configure/build sections, with make and modinfo replaced."""

    def test_grub_uses_installed_kbuild_and_matching_toolchain(self):
        self.check_build(clang=False)
        self.check_build(clang=True)

    def test_mismatched_abi_flags_are_fatal(self):
        self.check_build(clang=True, mismatched=True)

    def check_build(self, clang, mismatched=False):
        import os
        import subprocess
        import tempfile

        source = (ROOT / "scripts/patch-imac5k-amdgpu.sh").read_text()
        toolchain = source[source.index("MAKE_ARGS=()"):source.index("# ── fetch matching")]
        configure = source[source.index('say "configuring to match'):source.index("# ── apply the 5K")]
        build = source[source.index("# ── build just"):source.index("# ── install (compressed")]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            module = root / "drivers/gpu/drm/amd/amdgpu/amdgpu.ko"
            module.parent.mkdir(parents=True)
            module.write_text("fake module")
            (root / ".config").write_text("DO NOT RECONFIGURE THE SOURCE TREE\n")
            prelude = r'''
set -euo pipefail
GRUB=1
KREL=7.2.2-cachyos-test
BUILDLINK="$PWD/installed-headers"
say() { echo "$*"; }
die() { echo "$*" >&2; exit 1; }
imac_kernel_uses_clang() { [[ $TEST_CLANG == 1 ]]; }
clang() { :; }
ld.lld() { :; }
llvm-ar() { :; }
llvm-nm() { :; }
llvm-objcopy() { :; }
llvm-objdump() { :; }
llvm-readelf() { :; }
llvm-strip() { :; }
make() {
    echo "$*" >> calls
    if [[ " $* " == *" kernelrelease "* ]]; then echo "$KREL"; fi
    return 0
}
modinfo() {
    if [[ $1 != -k && $MISMATCHED == 1 ]]; then echo "$KREL SMP"; else echo "$KREL SMP modversions"; fi
}
'''
            result = subprocess.run(["bash", "-c", prelude + toolchain + configure + build],
                                    cwd=root, text=True, capture_output=True, timeout=10,
                                    env={**os.environ, "TEST_CLANG": str(int(clang)),
                                         "MISMATCHED": str(int(mismatched))})
            self.assertEqual(result.returncode, int(mismatched), result.stderr)
            calls = (root / "calls").read_text().splitlines()
            self.assertEqual(len(calls), 2, calls)
            for call in calls:
                self.assertIn(f"-C {root}/installed-headers", call)
                self.assertEqual("LLVM=1" in call, clang)
                self.assertNotIn("olddefconfig", call)
                self.assertNotIn("modules_prepare", call)
            self.assertIn(f"M={root}/drivers/gpu/drm/amd/amdgpu", calls[1])
            self.assertEqual((root / ".config").read_text(), "DO NOT RECONFIGURE THE SOURCE TREE\n")

    def test_installer_finds_the_module_instead_of_a_helper_backup(self):
        import os
        import subprocess
        import tempfile

        source = (ROOT / "scripts/patch-imac5k-amdgpu.sh").read_text()
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "amdgpu"
            directory.mkdir()
            for name in ("amdgpu.ko.zst.prev-promote", "amdgpu.ko.zst.prev-stage",
                         "amdgpu.ko.zst.stock-backup", "amdgpu.ko.zst"):
                (directory / name).touch()
            result = subprocess.run(["bash", "-c", shell_function(source, "find_amdgpu") + "\nfind_amdgpu"],
                                    text=True, capture_output=True, timeout=5,
                                    env={**os.environ, "MODDIR": str(directory)})
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), str(directory / "amdgpu.ko.zst"))
