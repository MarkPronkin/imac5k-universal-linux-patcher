"""Exercise helper lifecycles with fake modules, archives and boot commands.

Every writable path is under a TemporaryDirectory; no host GRUB, initramfs
builder, kernel build, package manager or root access is used.
"""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from test_grub import GRUB_CFG, CUSTOM_HEADER
from test_patcher_menu import shell_function

ROOT = Path(__file__).resolve().parents[1]
KREL = "7.2.2-cachyos-test"
MODREL = "kernel/drivers/gpu/drm/amd/amdgpu/amdgpu.ko.zst"


class GrubHelperTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.boot = self.root / "boot"
        self.boot.mkdir()
        self.modules = self.root / "modules"
        self.module = self.modules / KREL / MODREL
        self.module.parent.mkdir(parents=True)
        self.module.write_text("installed-test-module")
        (self.modules / KREL / "vmlinuz").write_text("kernel")
        (self.boot / "vmlinuz-linux-cachyos").write_text("kernel")
        self.image = self.boot / "initramfs-linux-cachyos.img"
        self.image.write_text("installed-test-module")
        self.presets = self.root / "presets"
        self.presets.mkdir()
        (self.presets / "linux-cachyos.preset").touch()
        self.cfg = self.boot / "grub.cfg"
        self.cfg.write_text(GRUB_CFG.replace("/vmlinuz-linux", "/vmlinuz-linux-cachyos")
                            .replace("/initramfs-linux", "/initramfs-linux-cachyos"))
        self.custom = self.root / "40_custom"
        self.custom.write_text(CUSTOM_HEADER)
        self.default = self.root / "grub-default"
        self.default.write_text('GRUB_CMDLINE_LINUX_DEFAULT="quiet amdgpu.tiled_stitch=1"\n')
        self.good = self.root / "good.ko.zst.stock-backup"
        self.good.write_text("known-good-module")

    def run_helper(self, script, code, **env):
        source = (ROOT / "scripts" / script).read_text()
        # The GRUB backend functions are indented once inside its dispatch.
        source = "\n".join(line.removeprefix("\t") for line in source.splitlines())
        names = ("grub_stage", "grub_promote", "grub_drop") if script == "imac-test-entry" else ("grub_add", "grub_promote", "grub_drop")
        functions = "\n".join(shell_function(source, name) for name in names)
        prelude = r'''
set -euo pipefail
say() { echo "$*"; }
warn() { echo "$*" >&2; }
die() { warn "$*"; exit 1; }
need_root() { :; }
check_name() { [[ $1 =~ ^[a-zA-Z0-9][a-zA-Z0-9._-]{0,31}$ ]] || die "bad name"; }
imac_kernel_pkgbase() { echo linux-cachyos; }
source "$REPO/scripts/lib/grub.sh"
PKGBASE=linux-cachyos
MODULE="$GRUB_MODULES_DIR/$KREL/$MODREL"
DEFAULT_IMG="$GRUB_BOOT_DIR/initramfs-$PKGBASE.img"
TESTNAME=5ktest
TESTIMG=$(grub_image_path "$TESTNAME")
modinfo() {
    if [[ $(cat "${@: -1}") == wrong-kernel ]]; then echo wrong-release; else echo "$KREL SMP"; fi
}
depmod() { echo "depmod $*" >> "$TEST_ROOT/calls"; }
sync() { :; }
rsync() { cp -a "${@: -2:1}" "${@: -1}"; }
# The fake archive contains the fake module bytes, stored as .ko.zst.
lsinitcpio() {
    [[ $1 == --extract && $2 == --cpio ]] || return 99
    mkdir -p "usr/lib/modules/$KREL/$(dirname "$MODREL")"
    local path="usr/lib/modules/$KREL/$MODREL"
    [[ ${IMAGE_UNCOMPRESSED:-0} == 0 ]] || path=${path%.zst}
    cp "$3" "$path"
}
zstd() {
    if [[ $1 == -dcf ]]; then cat "$2"; return; fi
    local src= dest=
    while (($#)); do
        case $1 in -o) dest=$2; shift ;; -*) ;; *) src=$1 ;; esac
        shift
    done
    if [[ -n $dest ]]; then cp "$src" "$dest"; else cat "$src"; fi
}
mkinitcpio() {
    echo "mkinitcpio $*" >> "$TEST_ROOT/calls"
    if [[ $1 == -P ]]; then
        [[ ${FAIL_DEFAULT:-0} == 0 ]] || return 1
        cp "$MODULE" "$DEFAULT_IMG"
        return
    fi
    [[ ${FAIL_BUILD:-0} == 0 ]] || return 1
    local out= root="$GRUB_MODULES_DIR" amdgpu=0
    while (($#)); do
        case $1 in
            -g) out=$2; shift ;;
            --kernel) [[ $2 == "$KREL" ]] || return 99; shift ;;
            --moduleroot) root="$2/usr/lib/modules"; shift ;;
            --addmodules) [[ $2 == amdgpu ]] || return 99; amdgpu=1; shift ;;
            *) return 99 ;;
        esac
        shift
    done
    ((amdgpu)) || return 99
    cp "$root/$KREL/$MODREL" "$out"
}
grub-mkconfig() {
    echo "grub-mkconfig $*" >> "$TEST_ROOT/calls"
    [[ ${FAIL_GRUB:-0} == 0 ]]
}
grub_status() { :; }
grub_list() { :; }
module_desc() { cat "$1"; }
'''
        return subprocess.run(["bash", "-c", prelude + functions + "\n" + code],
                              text=True, capture_output=True, timeout=10,
                              env={**os.environ, "REPO": str(ROOT), "TEST_ROOT": str(self.root),
                                   "KREL": KREL, "MODREL": MODREL, "GOOD_INPUT": str(self.good),
                                   "GRUB_BOOT_DIR": str(self.boot), "GRUB_CFG": str(self.cfg),
                                   "GRUB_MODULES_DIR": str(self.modules), "GRUB_PRESET_DIR": str(self.presets),
                                   "GRUB_CUSTOM": str(self.custom), "GRUB_DEFAULT_FILE": str(self.default),
                                   "GRUB_SUDO": "", **env})

    def test_stage_preserves_test_build_and_promote_restores_it(self):
        result = self.run_helper("imac-test-entry", 'grub_stage "$GOOD_INPUT"')
        self.assertEqual(result.returncode, 0, result.stderr)
        test = self.boot / "initramfs-linux-cachyos-imac-5ktest.img"
        self.assertEqual(test.read_text(), "installed-test-module")
        self.assertEqual(self.module.read_text(), "known-good-module")
        self.assertEqual(self.image.read_text(), "known-good-module")
        self.assertIn("/initramfs-linux-cachyos-imac-5ktest.img", self.custom.read_text())
        result = self.run_helper("imac-test-entry", "grub_promote")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.image.read_text(), "installed-test-module")
        self.assertEqual(Path(str(self.module) + ".prev-promote").read_text(), "known-good-module")
        self.assertFalse(test.exists())
        self.assertNotIn("5ktest", self.custom.read_text())

    def test_stage_rejects_wrong_kernel_before_changing_default(self):
        self.good.write_text("wrong-kernel")
        result = self.run_helper("imac-test-entry", 'grub_stage "$GOOD_INPUT"')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.module.read_text(), "installed-test-module")
        self.assertEqual(self.image.read_text(), "installed-test-module")
        self.assertEqual(self.custom.read_text(), CUSTOM_HEADER)
        self.assertFalse((self.root / "calls").exists())

    def test_pending_kernel_update_refuses_before_any_build_or_install(self):
        (self.boot / "vmlinuz-linux-cachyos").write_text("newer-kernel")
        result = self.run_helper("imac-test-entry", 'grub_stage "$GOOD_INPUT"')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("reboot into the installed kernel", result.stderr)
        self.assertFalse((self.root / "calls").exists())

    def test_missing_mkinitcpio_preset_refuses_dracut_layout(self):
        (self.presets / "linux-cachyos.preset").unlink()
        result = self.run_helper("imac-test-entry", 'grub_stage "$GOOD_INPUT"')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("mkinitcpio preset", result.stderr)
        self.assertFalse((self.root / "calls").exists())

    def test_failed_test_build_does_not_replace_default_or_create_entry(self):
        result = self.run_helper("imac-test-entry", 'grub_stage "$GOOD_INPUT"', FAIL_BUILD="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.module.read_text(), "installed-test-module")
        self.assertEqual(self.image.read_text(), "installed-test-module")
        self.assertEqual(self.custom.read_text(), CUSTOM_HEADER)

    def test_alt_entry_uses_private_modules_until_promoted(self):
        result = self.run_helper("imac-alt-entry", 'grub_add trial "$GOOD_INPUT"')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.module.read_text(), "installed-test-module")
        self.assertEqual(self.image.read_text(), "installed-test-module")
        test = self.boot / "initramfs-linux-cachyos-imac-trial.img"
        self.assertEqual(test.read_text(), "known-good-module")
        result = self.run_helper("imac-alt-entry", "grub_promote trial")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.image.read_text(), "known-good-module")
        self.assertEqual(Path(str(self.module) + ".prev-promote").read_text(), "installed-test-module")
        self.assertFalse(test.exists())

    def test_failed_promotion_keeps_test_entry_image_and_previous_module(self):
        result = self.run_helper("imac-alt-entry", 'grub_add trial "$GOOD_INPUT"')
        self.assertEqual(result.returncode, 0, result.stderr)
        result = self.run_helper("imac-alt-entry", "grub_promote trial", FAIL_DEFAULT="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("/Test - trial", self.custom.read_text())
        self.assertTrue((self.boot / "initramfs-linux-cachyos-imac-trial.img").exists())
        self.assertEqual(Path(str(self.module) + ".prev-promote").read_text(), "installed-test-module")

    def test_failed_grub_drop_keeps_referenced_image(self):
        result = self.run_helper("imac-alt-entry", 'grub_add trial "$GOOD_INPUT"')
        self.assertEqual(result.returncode, 0, result.stderr)
        result = self.run_helper("imac-alt-entry", "grub_drop trial", FAIL_GRUB="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("/Test - trial", self.custom.read_text())
        self.assertTrue((self.boot / "initramfs-linux-cachyos-imac-trial.img").exists())

    def test_decompressed_module_inside_initramfs_can_be_promoted(self):
        result = self.run_helper("imac-test-entry", 'grub_stage "$GOOD_INPUT"', IMAGE_UNCOMPRESSED="1")
        self.assertEqual(result.returncode, 0, result.stderr)
        result = self.run_helper("imac-test-entry", 'grub_promote', IMAGE_UNCOMPRESSED="1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.image.read_text(), "installed-test-module")
