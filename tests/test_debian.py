"""Debian source ABI and install/restore transactions, using only scratch files."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
KREL = "6.12.113+deb13-amd64"
MENU = """menuentry 'Debian GNU/Linux' --class debian $menuentry_id_option 'gnulinux-simple' {
    search --no-floppy --fs-uuid --set=root keep-root-uuid
    linux /@/boot/vmlinuz-6.12.113+deb13-amd64 root=UUID=keep ro quiet video=eDP-1:3840x2160@60e video=DP-2:1920x1080
    initrd /@/boot/intel-ucode.img /@/boot/initrd.img-6.12.113+deb13-amd64
}
menuentry 'Older Debian' --id 'older' {
    linux /boot/vmlinuz-old root=UUID=keep ro quiet
    initrd /boot/initrd.img-old
}
"""

MOCK = r'''#!/usr/bin/env python3
import json, os, pathlib, sys
name, args = pathlib.Path(sys.argv[0]).name, sys.argv[1:]
root = pathlib.Path(os.environ['TEST_ROOT'])
with (root / 'calls').open('a') as log:
    log.write(json.dumps([name, *args]) + '\n')
if name == 'modinfo':
    if '-n' in args:
        print(root / 'modules/updates/imac5k/amdgpu.ko.xz')
    elif 'vermagic' in args:
        print(('bad-kernel' if args[-1].endswith('bad.ko') else os.environ['KREL']) + ' SMP mod_unload modversions ')
    elif 'name' in args:
        print('amdgpu')
    elif 'parm' in args:
        print('tiled_stitch:Enable stitched mode (int)')
elif name == 'mkinitramfs':
    assert args[0] == '-o' and args[2] == os.environ['KREL']
    pathlib.Path(args[1]).write_text('partial' if os.environ.get('FAIL_INITRAMFS') else 'rebuilt')
    if os.environ.get('FAIL_INITRAMFS'): sys.exit(1)
elif name == 'lsinitramfs':
    if not os.environ.get('MISSING_MODULE'):
        print('usr/lib/modules/' + os.environ['KREL'] + '/updates/imac5k/amdgpu.ko.xz')
elif name == 'grub-mkconfig':
    cfg = pathlib.Path(args[args.index('-o') + 1])
    cfg.write_text('partial' if os.environ.get('FAIL_GRUB') else '')
    if os.environ.get('FAIL_GRUB'): sys.exit(1)
    if (root / 'entry').exists():
        with cfg.open('a') as out: out.write('\n'.join((root / 'entry').read_text().splitlines()[2:]))
    with cfg.open('a') as out: out.write('\n' + (root / 'normal-menu').read_text())
elif name == 'mokutil':
    if args == ['--sb-state']:
        print('SecureBoot enabled' if os.environ.get('SECURE_BOOT') else 'SecureBoot disabled')
    elif '--test-key' in args:
        sys.exit(0 if os.environ.get('ENROLLED') else 1)
elif name == 'dpkg-query':
    metadata = os.environ.get('HEADER_METADATA', 'installed linux 6.12.113-1')
    if args[-1].startswith('linux-source-'): metadata = os.environ.get('SOURCE_METADATA', metadata)
    print(metadata, end='')
'''


class AptBackendMixin:
    distro = "debian"
    krel = KREL
    series = "6.12"
    version = "6.12.113-1"
    port = "imac5k-debian-6.12.patch"
    dkms_cert = "/var/lib/dkms/mok.pub"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.menu = MENU.replace(KREL, self.krel).replace("Debian", self.distro.title())
        bindir = self.root / "bin"
        bindir.mkdir()
        for name in ("modinfo", "depmod", "mkinitramfs", "lsinitramfs", "grub-mkconfig", "mokutil", "strip", "dpkg-query"):
            path = bindir / name
            path.write_text(MOCK)
            path.chmod(0o755)
        for name, data in (("initrd.img-" + self.krel, "stock"), ("vmlinuz-" + self.krel, "kernel"), ("good.ko", "module"), ("bad.ko", "bad"),
                           ("grub.cfg", self.menu), ("normal-menu", self.menu)):
            (self.root / name).write_text(data)

    def run_backend(self, command, **env):
        code = r'''
source "$REPO/scripts/$TEST_DISTRO-imac5k"
export PATH="$TEST_ROOT/bin:$PATH"
export KREL=$TEST_KREL
KSERIES=$TEST_KSERIES
DEST=$TEST_ROOT/modules/updates/imac5k/amdgpu.ko.xz
DEPMOD_CONF=$TEST_ROOT/depmod/imac5k.conf
STATE=$TEST_ROOT/state
INITRD=$TEST_ROOT/initrd.img-$KREL
KERNEL=$TEST_ROOT/vmlinuz-$KREL
ENTRY=$TEST_ROOT/entry
INITRAMFS_HOOK=$TEST_ROOT/hooks/imac5k
GRUB_CFG=$TEST_ROOT/grub.cfg
need_root() { :; }
imac_has_grub() { return 0; }
imac_has_limine() { return 1; }
# Keep the production parser, with the Debian image names that our scratch
# kernel/initramfs stand in for.
check_layout() { grub_kernel_entry "vmlinuz-$KREL" "initrd.img-$KREL" >/dev/null; }
'''
        return subprocess.run(["bash", "-c", code + command], text=True, capture_output=True,
                              timeout=20, env={**os.environ, "REPO": str(ROOT), "TEST_ROOT": str(self.root),
                                   "TEST_DISTRO": self.distro, "TEST_KREL": self.krel,
                                   "TEST_KSERIES": self.series, "HEADER_METADATA": "installed linux " + self.version, **env})

    def calls(self):
        path = self.root / "calls"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def assert_stock(self):
        self.assertEqual((self.root / ("initrd.img-" + self.krel)).read_text(), "stock")
        self.assertEqual((self.root / "grub.cfg").read_text(), self.menu)
        self.assertFalse((self.root / "modules/updates/imac5k/amdgpu.ko.xz").exists())
        self.assertFalse((self.root / "depmod/imac5k.conf").exists())
        self.assertFalse((self.root / "entry").exists())
        self.assertFalse((self.root / "hooks/imac5k").exists())

    def test_install_and_restore_preserve_fallback_kernel_arguments(self):
        result = self.run_backend('install_module "$TEST_ROOT/good.ko"')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.root / ("initrd.img-" + self.krel)).read_text(), "rebuilt")
        self.assertEqual((self.root / "state/initramfs.stock").read_text(), "stock")
        self.assertIn(self.krel, (self.root / "hooks/imac5k").read_text())
        entry = (self.root / "entry").read_text()
        self.assertIn("iMac 5K - " + self.krel, entry)
        self.assertIn("/@/boot/initrd.img-" + self.krel, entry)
        self.assertIn("/@/boot/intel-ucode.img", entry)
        self.assertIn("root=UUID=keep", entry)
        self.assertIn("video=DP-2:1920x1080", entry)
        self.assertNotIn("video=eDP-1:", entry)
        self.assertIn("amdgpu.tiled_stitch=1", entry)
        self.assertEqual((self.root / "grub.cfg").read_text().count("amdgpu.tiled_stitch=1"), 1)
        self.assertIn(self.menu, (self.root / "grub.cfg").read_text())
        result = self.run_backend("restore_module")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.root / "grub.cfg").read_text().strip(), self.menu.strip())
        self.assertFalse((self.root / "entry").exists())
        self.assertFalse((self.root / "modules/updates/imac5k/amdgpu.ko.xz").exists())
        self.assertFalse((self.root / "state/installed").exists())

    def test_build_failures_restore_the_original_boot_files(self):
        for failure in ("FAIL_INITRAMFS", "MISSING_MODULE", "FAIL_GRUB"):
            with self.subTest(failure=failure):
                result = self.run_backend('install_module "$TEST_ROOT/good.ko"', **{failure: "1"})
                self.assertNotEqual(result.returncode, 0)
                self.assert_stock()
                self.assertFalse((self.root / "state/installed").exists())

    def test_wrong_abi_never_changes_boot_or_creates_a_backup(self):
        result = self.run_backend('install_module "$TEST_ROOT/bad.ko"')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("vermagic", result.stderr)
        self.assertFalse((self.root / "state").exists())
        self.assert_stock()

    def test_headers_use_generated_abi_instead_of_upstream_make_version(self):
        headers = self.root / "headers"
        (headers / "include/generated").mkdir(parents=True)
        for name in (".config", "Module.symvers"):
            (headers / name).touch()
        release = headers / "include/generated/utsrelease.h"
        release.write_text(f'#define UTS_RELEASE "{self.krel}"\n')
        command = r'''
BUILD=$TEST_ROOT/headers
need_tools() { :; }
make() { echo unexpected_make_call >&2; return 1; }
check
'''
        result = self.run_backend(command)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("unexpected_make_call", result.stderr)
        release.write_text('#define UTS_RELEASE "wrong-abi"\n')
        result = self.run_backend(command)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("headers do not match", result.stderr)

    def test_missing_grub_entry_stops_before_installation(self):
        (self.root / "grub.cfg").write_text("no matching entry\n")
        result = self.run_backend('install_module "$TEST_ROOT/good.ko"')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.root / "state").exists())
        self.assertEqual((self.root / ("initrd.img-" + self.krel)).read_text(), "stock")

    def test_reinstall_preserves_first_stock_backup(self):
        for _ in range(2):
            result = self.run_backend('install_module "$TEST_ROOT/good.ko"')
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.root / "state/initramfs.stock").read_text(), "stock")

    def test_reapply_refreshes_from_the_normal_entry_instead_of_cloning_itself(self):
        self.assertEqual(self.run_backend('install_module "$TEST_ROOT/good.ko"').returncode, 0)
        updated = self.menu.replace("root=UUID=keep", "root=UUID=new-root")
        (self.root / "normal-menu").write_text(updated)
        entry = "\n".join((self.root / "entry").read_text().splitlines()[2:])
        (self.root / "grub.cfg").write_text(entry + "\n" + updated)
        result = self.run_backend('install_module "$TEST_ROOT/good.ko"')
        self.assertEqual(result.returncode, 0, result.stderr)
        entry = (self.root / "entry").read_text()
        self.assertIn("root=UUID=new-root", entry)
        self.assertNotIn("root=UUID=keep", entry)

    def test_initramfs_hook_includes_amdgpu_only_for_its_own_kernel(self):
        self.assertEqual(self.run_backend('install_module "$TEST_ROOT/good.ko"').returncode, 0)
        calls = self.root / "hook-calls"
        library = self.root / "hook-functions"
        library.write_text(f'manual_add_modules() {{ printf "%s\\n" "$*" >> "{calls}"; }}\n')
        hook = self.root / "test-hook"
        hook.write_text((self.root / "hooks/imac5k").read_text().replace(
            "/usr/share/initramfs-tools/hook-functions", str(library)))
        for version, args in ((self.krel, ["prereqs"]), ("other-kernel", []), (self.krel, [])):
            result = subprocess.run(["sh", str(hook), *args], text=True, capture_output=True,
                                    env={**os.environ, "version": version}, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls.read_text(), "amdgpu\n")

    def test_failed_reinstall_restores_the_working_patch_and_menu(self):
        self.assertEqual(self.run_backend('install_module "$TEST_ROOT/good.ko"').returncode, 0)
        paths = [self.root / "grub.cfg", self.root / "entry", self.root / ("initrd.img-" + self.krel),
                 self.root / "modules/updates/imac5k/amdgpu.ko.xz"]
        before = {path: path.read_bytes() for path in paths}
        result = self.run_backend('install_module "$TEST_ROOT/good.ko"', FAIL_GRUB="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual({path: path.read_bytes() for path in paths}, before)
        self.assertTrue((self.root / "state/installed").exists())
        self.assertFalse((self.root / "state/recovery-needed").exists())

    def test_restore_grub_failure_keeps_a_complete_menu(self):
        self.assertEqual(self.run_backend('install_module "$TEST_ROOT/good.ko"').returncode, 0)
        menu = (self.root / "grub.cfg").read_bytes()
        result = self.run_backend("restore_module", FAIL_GRUB="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.root / "grub.cfg").read_bytes(), menu)
        self.assertEqual((self.root / ("initrd.img-" + self.krel)).read_text(), "rebuilt")
        self.assertTrue((self.root / "state/recovery-needed").exists())

    def test_failed_restore_keeps_stock_image_and_is_retryable(self):
        self.assertEqual(self.run_backend('install_module "$TEST_ROOT/good.ko"').returncode, 0)
        result = self.run_backend("restore_module", FAIL_INITRAMFS="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.root / ("initrd.img-" + self.krel)).read_text(), "stock")
        self.assertTrue((self.root / "state/recovery-needed").exists())
        self.assertNotEqual(self.run_backend('install_module "$TEST_ROOT/good.ko"').returncode, 0)
        result = self.run_backend("restore_module")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.root / "state/recovery-needed").exists())

    def test_source_version_comes_from_headers_not_signed_image_or_abi(self):
        result = self.run_backend("source_version")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, self.version + "\n")
        query = next(call for call in self.calls() if call[0] == "dpkg-query")
        self.assertEqual(query[-1], "linux-headers-" + self.krel)
        for metadata in ("installed linux-signed-amd64 6.12.113-1", "config-files linux 6.12.113-1", "installed linux bogus/path"):
            with self.subTest(metadata=metadata):
                self.assertNotEqual(self.run_backend("source_version", HEADER_METADATA=metadata).returncode, 0)

    def test_secure_boot_requires_an_enrolled_certificate_before_mutation(self):
        result = self.run_backend('install_module "$TEST_ROOT/good.ko"', SECURE_BOOT="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("signing required", result.stderr)
        self.assertFalse((self.root / "state").exists())
        self.assert_stock()

    def test_later_7x_uses_the_same_lean_stack_as_arch_and_fedora(self):
        from test_patch_stacks import PatchStackTests
        result = self.run_backend("KSERIES=7.2; patch_stack")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), PatchStackTests().stack("fedora-imac5k"))

    def test_stock_kernel_port_is_shipped_and_old_kernels_are_refused(self):
        result = self.run_backend("patch_stack")
        self.assertEqual(result.stdout.strip(), self.port)
        self.assertTrue((ROOT / "patches" / self.port).is_file())
        self.assertNotEqual(self.run_backend("KSERIES=6.1; check").returncode, 0)
        self.assertNotEqual(self.run_backend("IMAC5K_STACK=verbose; patch_stack").returncode, 0)

    def module(self, code, **env):
        from test_patcher_menu import shell_function
        patcher = (ROOT / "scripts/imac-patcher").read_text()
        base = "\n".join(shell_function(patcher, name) for name in ("audio_kernel_supported", "mod_audio_detect"))
        return self.run_backend(base + r'''
product=iMac18,3
AUDIO_DKMS=snd_hda_macbookpro
source "$SCRIPT_DIR/lib/$TEST_DISTRO.sh"
sudo() { "$@"; }
''' + code, **env)

    def test_module_packages_are_installed_with_apt_and_rechecked(self):
        result = self.module(r'''
present=0
dpkg-query() { ((present)) && printf installed; }
confirm() { return 0; }
apt-get() { printf 'APT %s\n' "$*"; present=1; }
apt_deps dkms "linux-headers-$KREL"
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("APT install -y dkms linux-headers-" + self.krel, result.stdout)
        result = self.module(r'''
dpkg-query() { return 1; }
confirm() { return 0; }
apt-get() { return 0; }
apt_deps dkms
''')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("still missing", result.stderr)

    def test_declined_module_dependencies_do_not_run_apt(self):
        result = self.module(r'''
dpkg-query() { return 1; }
confirm() { return 1; }
apt-get() { echo UNEXPECTED_APT; }
apt_deps dkms
''')
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("UNEXPECTED_APT", result.stdout)

    def test_audio_on_a_newer_kernel_uses_dkms_and_initramfs_tools(self):
        result = self.module(r'''
KREL=7.2.2-debian-test
audio_check_hardware() { :; }
apt_deps() { printf 'DEPS %s\n' "$*"; }
apt_headers_ok() { :; }
ubuntu_audio_source_deps() { :; }
audio_install_driver() { echo DKMS_INSTALLED; }
xhci_fix_signing_ok() { :; }
update-initramfs() { printf 'INITRAMFS %s\n' "$*"; }
mod_audio_apply
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("linux-headers-7.2.2-debian-test", result.stdout)
        self.assertIn("build-essential", result.stdout)
        self.assertIn("initramfs-tools", result.stdout)
        self.assertIn("DKMS_INSTALLED\nINITRAMFS -u -k all", result.stdout)

    def test_dkms_enrollment_uses_the_distribution_certificate(self):
        result = self.module("xhci_fix_signing_ok", SECURE_BOOT="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(self.dkms_cert, result.stderr)
        result = self.module("xhci_fix_signing_ok", SECURE_BOOT="1", ENROLLED="1")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_arch_firmware_and_boot_repair_are_not_offered(self):
        result = self.module("mod_boot_detect; macos_backend_supported")
        self.assertEqual(result.stdout, "n/a\n")
        self.assertNotEqual(result.returncode, 0)


class DebianBackendTests(AptBackendMixin, unittest.TestCase):
    def test_stock_kernel_audio_is_unavailable_but_existing_installs_can_be_removed(self):
        result = self.module(r'''
modinfo() { return 1; }
dkms() { :; }
mod_audio_detect
mod_audio_apply
''')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "n/a\n")
        self.assertIn("requires Linux 6.17+", result.stderr)
        result = self.module(r'''
modinfo() { return 1; }
dkms() { echo registered; }
mod_audio_detect
audio_remove_driver() { echo removed; }
update-initramfs() { printf 'INITRAMFS %s\n' "$*"; }
mod_audio_remove
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(result.stdout.startswith("partial\nremoved\n"))
        self.assertIn("INITRAMFS -u -k all", result.stdout)


if __name__ == "__main__":
    unittest.main()
