"""lib/grub.sh: /etc/default/grub cmdline edits and 40_custom test entries.

Everything runs against tempdir fixtures with a stubbed grub-mkconfig; nothing
touches the host's boot configuration.
"""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
GRUB_LIB = ROOT / "scripts/lib/grub.sh"

GRUB_CFG = """### BEGIN /etc/grub.d/10_linux ###
menuentry 'Arch Linux' --class arch --class gnu-linux $menuentry_id_option 'gnulinux-simple-abc123' {
	load_video
	set gfxpayload=keep
	insmod gzio
	insmod part_gpt
	insmod ext2
	search --no-floppy --fs-uuid --set=root abc123
	linux	/vmlinuz-linux root=UUID=abc123 rw loglevel=3 quiet
	initrd	/amd-ucode.img /initramfs-linux.img
}
submenu 'Advanced options for Arch Linux' $menuentry_id_option 'gnulinux-advanced-abc123' {
	menuentry 'Arch Linux, with Linux linux (fallback)' {
		linux	/vmlinuz-linux root=UUID=abc123 rw loglevel=3 quiet
		initrd	/amd-ucode.img /initramfs-linux-fallback.img
	}
}
"""

CUSTOM_HEADER = """#!/bin/sh
exec tail -n +3 $0
# This file provides an easy way to add custom menu entries.
"""


class GrubLibTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        t = Path(self.tmp.name)
        self.default = t / "default-grub"
        self.cfg = t / "grub.cfg"
        self.custom = t / "40_custom"
        self.calls = t / "calls.log"
        self.default.write_text(
            '# stock-ish /etc/default/grub\n'
            'GRUB_TIMEOUT=5\n'
            'GRUB_CMDLINE_LINUX_DEFAULT="loglevel=3 quiet"\n'
            '#GRUB_CMDLINE_LINUX_DEFAULT="idle=poll"\n'
            'GRUB_CMDLINE_LINUX=""\n')
        self.cfg.write_text(GRUB_CFG)
        self.custom.write_text(CUSTOM_HEADER)
        self.custom.chmod(0o755)

    def run_grub(self, code):
        env = dict(os.environ)
        env.update({
            "GRUB_DEFAULT_FILE": str(self.default),
            "GRUB_CFG": str(self.cfg),
            "GRUB_CUSTOM": str(self.custom),
            "GRUB_CALLS": str(self.calls),
            "GRUB_SUDO": "",
            "GRUB_BOOT_DIR": "/boot",
        })
        prelude = f'''
set -uo pipefail
say()  {{ printf 'SAY %s\\n' "$*"; }}
warn() {{ printf 'WARN %s\\n' "$*" >&2; }}
grub-mkconfig() {{ printf 'grub-mkconfig %s\\n' "$*" >> "$GRUB_CALLS"; }}
KREL=7.2.2-test
imac_kernel_pkgbase() {{ echo linux; }}
source "{GRUB_LIB}"
''' + code
        return subprocess.run(["bash", "-c", prelude],
                              text=True, capture_output=True, timeout=10, env=env)

    def mkconfig_calls(self):
        return self.calls.read_text() if self.calls.exists() else ""

    def test_has_matches_active_tokens_only(self):
        result = self.run_grub(
            'grub_cmdline_has quiet && echo HAS-QUIET; '
            'grub_cmdline_has idle=poll || echo NO-IDLEPOLL; '
            'grub_cmdline_has qui || echo NO-PARTIAL')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("HAS-QUIET", result.stdout)
        self.assertIn("NO-IDLEPOLL", result.stdout)   # commented line must not match
        self.assertIn("NO-PARTIAL", result.stdout)    # substring must not match

    def test_add_appends_to_the_existing_line_and_regenerates(self):
        result = self.run_grub("grub_cmdline_add amdgpu.tiled_stitch=1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('GRUB_CMDLINE_LINUX_DEFAULT="loglevel=3 quiet amdgpu.tiled_stitch=1"',
                      self.default.read_text())
        self.assertIn("grub-mkconfig -o", self.mkconfig_calls())
        self.assertTrue(list(self.default.parent.glob("default-grub.backup-*")),
                        "a timestamped backup is taken before editing")

    def test_add_is_idempotent_and_creates_a_missing_line(self):
        result = self.run_grub(
            'grub_cmdline_add amdgpu.tiled_stitch=1 && grub_cmdline_add amdgpu.tiled_stitch=1')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.default.read_text().count("amdgpu.tiled_stitch=1"), 1)
        self.assertEqual(self.mkconfig_calls().count("grub-mkconfig"), 1)
        self.default.write_text('GRUB_TIMEOUT=5\n')
        self.calls.unlink()
        result = self.run_grub("grub_cmdline_add amdgpu.tiled_stitch=1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('GRUB_CMDLINE_LINUX_DEFAULT="amdgpu.tiled_stitch=1"',
                      self.default.read_text())

    def test_remove_covers_first_middle_only_and_linux_lines(self):
        for value in ('idle=poll loglevel=3 quiet', 'loglevel=3 idle=poll quiet', 'idle=poll'):
            with self.subTest(value=value):
                self.default.write_text(
                    f'GRUB_CMDLINE_LINUX_DEFAULT="{value}"\n')
                result = self.run_grub("grub_cmdline_remove idle=poll")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertNotIn("idle=poll", self.default.read_text())
                if "loglevel" in value:
                    self.assertIn("loglevel=3", self.default.read_text())
        # Also honored on GRUB_CMDLINE_LINUX (not only _DEFAULT).
        self.default.write_text('GRUB_CMDLINE_LINUX_DEFAULT="quiet"\nGRUB_CMDLINE_LINUX="idle=poll"\n')
        result = self.run_grub("grub_cmdline_remove idle=poll")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('GRUB_CMDLINE_LINUX=""', self.default.read_text())

    def test_remove_absent_param_is_a_noop(self):
        before = self.default.read_text()
        result = self.run_grub("grub_cmdline_remove idle=poll")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.default.read_text(), before)
        self.assertEqual(self.mkconfig_calls(), "")

    def test_clone_entry_retitles_and_swaps_only_the_initramfs(self):
        result = self.run_grub("grub_clone_entry 5ktest /boot/initramfs-linux-imac-5ktest.img")
        self.assertEqual(result.returncode, 0, result.stderr)
        custom = self.custom.read_text()
        self.assertIn("# >>> imac-patcher test entry: 5ktest >>>", custom)
        self.assertIn("menuentry '/Test - 5ktest'", custom)
        self.assertIn("search --no-floppy --fs-uuid --set=root abc123", custom)
        # Microcode image kept, distribution initramfs replaced.
        self.assertIn("initrd\t/amd-ucode.img /initramfs-linux-imac-5ktest.img", custom)
        self.assertNotIn("/initramfs-linux-fallback.img",
                         custom.split("5ktest >>>")[1].split("<<<")[0])
        self.assertIn("grub-mkconfig -o", self.mkconfig_calls())

    def test_clone_entry_handles_a_single_image_initrd_line(self):
        self.cfg.write_text(GRUB_CFG.replace(
            "\tinitrd\t/amd-ucode.img /initramfs-linux.img", "\tinitrd\t/initramfs-linux.img"))
        result = self.run_grub("grub_clone_entry 5ktest /boot/initramfs-linux-imac-5ktest.img")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("initrd\t/initramfs-linux-imac-5ktest.img", self.custom.read_text())

    def test_clone_entry_requires_the_exec_tail_header(self):
        self.custom.write_text("# hand-written file without the stock header\n")
        result = self.run_grub("grub_clone_entry 5ktest /boot/initramfs-linux-imac-5ktest.img")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("exec tail", result.stderr)
        self.assertNotIn("5ktest", self.custom.read_text())
        # A missing 40_custom is created with the header and made executable.
        self.custom.unlink()
        result = self.run_grub("grub_clone_entry 5ktest /boot/initramfs-linux-imac-5ktest.img")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(os.access(self.custom, os.X_OK))
        self.assertIn("exec tail -n +3", self.custom.read_text())

    def test_drop_entry_removes_only_its_own_block(self):
        result = self.run_grub(
            "grub_clone_entry alpha /boot/initramfs-linux-imac-alpha.img && grub_clone_entry beta /boot/initramfs-linux-imac-beta.img "
            "&& grub_drop_entry alpha")
        self.assertEqual(result.returncode, 0, result.stderr)
        custom = self.custom.read_text()
        self.assertNotIn("alpha", custom)
        self.assertIn("/Test - 'beta'".replace("'", ""), custom.replace("'", ""))
        # Dropping twice is a no-op without a regeneration.
        self.calls.unlink()
        result = self.run_grub("grub_drop_entry alpha")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.mkconfig_calls(), "")

    def test_list_entries_prints_names(self):
        result = self.run_grub(
            "grub_clone_entry alpha /boot/initramfs-linux-imac-alpha.img && grub_clone_entry beta /boot/initramfs-linux-imac-beta.img "
            "&& grub_list_entries")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines()[-2:], ["alpha", "beta"])

    def test_single_quotes_indentation_and_comments_preserve_cachyos_arguments(self):
        self.default.write_text(
            "  GRUB_CMDLINE_LINUX_DEFAULT='nowatchdog zswap.enabled=0 quiet splash' # keep\n"
            "GRUB_CMDLINE_LINUX='cryptdevice=UUID=abc:root'\n")
        result = self.run_grub("grub_cmdline_add amdgpu.tiled_stitch=1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("'nowatchdog zswap.enabled=0 quiet splash amdgpu.tiled_stitch=1' # keep", self.default.read_text())
        result = self.run_grub("grub_cmdline_remove amdgpu.tiled_stitch=1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("'nowatchdog zswap.enabled=0 quiet splash' # keep", self.default.read_text())
        self.assertIn("cryptdevice=UUID=abc:root", self.default.read_text())

    def test_last_assignment_wins_and_unquoted_values_are_preserved(self):
        self.default.write_text('GRUB_CMDLINE_LINUX_DEFAULT="idle=poll"\nGRUB_CMDLINE_LINUX_DEFAULT=quiet\n')
        result = self.run_grub("grub_cmdline_has idle=poll")
        self.assertEqual(result.returncode, 1, result.stderr)
        result = self.run_grub("grub_cmdline_add idle=poll")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('GRUB_CMDLINE_LINUX_DEFAULT="quiet idle=poll"', self.default.read_text())
        result = self.run_grub("grub_cmdline_remove idle=poll")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("idle=poll", self.default.read_text())

    def test_computed_values_fail_without_overwriting_or_executing_them(self):
        marker = self.default.parent / "executed"
        for value in (f'"$(touch {marker}) quiet"', '"$GRUB_CMDLINE_LINUX_DEFAULT quiet"', '"quiet; true"'):
            with self.subTest(value=value):
                original = f'GRUB_CMDLINE_LINUX_DEFAULT={value}\n'
                self.default.write_text(original)
                result = self.run_grub("grub_cmdline_add amdgpu.tiled_stitch=1")
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.default.read_text(), original)
                self.assertFalse(marker.exists())
                self.assertEqual(self.mkconfig_calls(), "")

    def test_failed_generation_restores_config_and_generated_menu(self):
        original = self.default.read_text()
        result = self.run_grub('''
grub-mkconfig() { echo broken > "$GRUB_CFG"; return 1; }
grub_cmdline_add amdgpu.tiled_stitch=1
''')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.default.read_text(), original)
        self.assertEqual(self.cfg.read_text(), GRUB_CFG)
        result = self.run_grub("grub_cmdline_add amdgpu.tiled_stitch=1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("grub-mkconfig", self.mkconfig_calls())

    def test_clone_preserves_root_and_btrfs_boot_paths(self):
        for directory in ("/boot/", "/@/boot/"):
            with self.subTest(directory=directory):
                self.cfg.write_text(GRUB_CFG.replace("/vmlinuz-linux", directory + "vmlinuz-linux")
                                    .replace("/initramfs-linux", directory + "initramfs-linux"))
                result = self.run_grub("grub_clone_entry alpha /boot/initramfs-linux-imac-alpha.img")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(directory + "initramfs-linux-imac-alpha.img", self.custom.read_text())
                self.assertIn(directory + "vmlinuz-linux", self.custom.read_text())
                self.assertEqual(self.custom.read_text().count("# >>>"), 1)

    def test_clone_selects_cachyos_kernel_even_when_nested_and_not_first(self):
        cachy = GRUB_CFG.split("submenu")[0].replace("/vmlinuz-linux", "/vmlinuz-linux-cachyos").replace("/initramfs-linux", "/initramfs-linux-cachyos")
        self.cfg.write_text(GRUB_CFG + "submenu 'More kernels' {\n" +
                            "\n".join("\t" + line for line in cachy.splitlines()) + "\n}\n")
        result = self.run_grub('''
imac_kernel_pkgbase() { echo linux-cachyos; }
grub_clone_entry alpha /boot/initramfs-linux-cachyos-imac-alpha.img
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("/vmlinuz-linux-cachyos", self.custom.read_text())
        self.assertIn("/initramfs-linux-cachyos-imac-alpha.img", self.custom.read_text())
        self.assertNotIn("/vmlinuz-linux ", self.custom.read_text())

    def test_clone_uses_unique_id_and_does_not_save_test_as_default(self):
        self.cfg.write_text(GRUB_CFG.replace("\tload_video", "\tsavedefault\n\tload_video"))
        result = self.run_grub("grub_clone_entry alpha /boot/initramfs-linux-imac-alpha.img")
        self.assertEqual(result.returncode, 0, result.stderr)
        custom = self.custom.read_text()
        self.assertIn("--id 'imac-patcher-linux-alpha'", custom)
        self.assertNotIn("gnulinux-simple-abc123", custom)
        self.assertNotIn("savedefault", custom)
        for backup in self.custom.parent.glob("40_custom.backup-*"):
            self.assertFalse(os.access(backup, os.X_OK), "GRUB must never execute backups as generators")

    def test_missing_matching_kernel_or_initramfs_leaves_custom_unchanged(self):
        for config in (GRUB_CFG.replace("vmlinuz-linux", "vmlinuz-linux-lts"),
                       GRUB_CFG.replace("initrd", "# initrd")):
            with self.subTest(config=config):
                self.cfg.write_text(config)
                result = self.run_grub("grub_clone_entry alpha /boot/initramfs-linux-imac-alpha.img")
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.custom.read_text(), CUSTOM_HEADER)
                self.assertEqual(self.mkconfig_calls(), "")

    def test_failed_entry_update_preserves_other_entries(self):
        result = self.run_grub("grub_clone_entry alpha /boot/initramfs-linux-imac-alpha.img")
        self.assertEqual(result.returncode, 0, result.stderr)
        original = self.custom.read_text()
        result = self.run_grub('grub-mkconfig() { return 1; }; grub_drop_entry alpha')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.custom.read_text(), original)

    def test_malformed_markers_cannot_delete_unrelated_custom_entries(self):
        original = CUSTOM_HEADER + "# >>> imac-patcher test entry: alpha >>>\nmenuentry 'Keep me' {}\n"
        self.custom.write_text(original)
        result = self.run_grub("grub_drop_entry alpha")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.custom.read_text(), original)

    def test_image_builder_requests_amdgpu_and_private_module_root(self):
        result = self.run_grub('''
mkinitcpio() { printf 'MKINITCPIO %s\n' "$*"; }
grub_build_image /tmp/test.img /tmp/private-root
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--kernel 7.2.2-test", result.stdout)
        self.assertIn("--addmodules amdgpu", result.stdout)
        self.assertIn("--moduleroot /tmp/private-root", result.stdout)

    def test_failed_update_restores_a_symlinked_config_target(self):
        original = self.default.read_text()
        target = self.default.parent / "shared-grub-config"
        self.default.rename(target)
        self.default.symlink_to(target)
        result = self.run_grub('grub-mkconfig() { return 1; }; grub_cmdline_add idle=poll')
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(self.default.is_symlink())
        self.assertEqual(target.read_text(), original)
        for backup in self.default.parent.glob("default-grub.backup-*"):
            self.assertFalse(backup.is_symlink())
            self.assertEqual(backup.read_text(), original)

    def test_failed_clone_restores_disabled_custom_file_permissions(self):
        self.custom.chmod(0o644)
        result = self.run_grub('grub-mkconfig() { return 1; }; grub_clone_entry alpha /boot/initramfs-linux-imac-alpha.img')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.custom.stat().st_mode & 0o777, 0o644)
        self.assertEqual(self.custom.read_text(), CUSTOM_HEADER)

    def test_custom_pkgbase_punctuation_is_literal_in_initramfs_replacement(self):
        self.cfg.write_text(GRUB_CFG.replace("/vmlinuz-linux", "/vmlinuz-linux-custom+test")
                            .replace("/initramfs-linux", "/initramfs-linux-custom+test"))
        result = self.run_grub("imac_kernel_pkgbase() { echo linux-custom+test; }; "
                               "grub_clone_entry alpha /boot/initramfs-linux-custom+test-imac-alpha.img")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("/initramfs-linux-custom+test-imac-alpha.img", self.custom.read_text())


if __name__ == "__main__":
    unittest.main()
