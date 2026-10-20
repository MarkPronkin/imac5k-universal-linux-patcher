"""Independent Intel opt-in and brightness coexistence, on both boot backends."""
import unittest

import test_macos as fixtures
from test_patcher_menu import driver


BOOTED = '''
mkdir -p "$MACOS_IGPU/drm/card0" "${MACOS_IGPU%/*}/i915"
ln -sfn ../i915 "$MACOS_IGPU/driver"
'''


class IgpuTests(unittest.TestCase):
    def fixture(self, backend):
        fixture = backend()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        return fixture

    def run_module(self, fixture, code, **kwargs):
        if type(fixture) is fixtures.ModuleTests:
            code = '''
boot_config_has() { grep -qs -- "$1" "$LIMINE_DEFAULT" "$LIMINE_DROPIN_DIR"/*.conf; }
''' + code
            kwargs.setdefault("enabled", "enabled")
        result = fixture.run_module(code, **kwargs)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def test_igpu_is_an_experimental_opt_in_and_not_enabled_by_brightness(self):
        for backend in (fixtures.ModuleTests, fixtures.GrubModuleTests):
            with self.subTest(backend=backend.__name__):
                f = self.fixture(backend)
                result = self.run_module(f, "mod_macos_apply >/dev/null; mod_igpu_tier; mod_igpu_detect")
                self.assertEqual(result.stdout.splitlines(), ["experimental", "not-applied"])
                self.assertFalse((f.root / "etc/mkinitcpio.conf.d/zz-imac-igpu-experimental.conf").exists())

    def test_igpu_works_alone_without_brightness_table_or_nvram_service(self):
        for backend in (fixtures.ModuleTests, fixtures.GrubModuleTests):
            with self.subTest(backend=backend.__name__):
                f = self.fixture(backend)
                result = self.run_module(f, "mod_igpu_apply >/dev/null; " + BOOTED + '''
mod_igpu_detect
mod_macos_detect
''')
                self.assertEqual(result.stdout.splitlines(), ["applied", "not-applied"])
                for path in ("etc/mkinitcpio.conf.d/zz-imac-igpu.conf",
                             "etc/initcpio/acpi_override/imac-bcl100.aml",
                             "etc/systemd/system/imac-backlight-nvram.service",
                             "usr/local/bin/imac-backlight-nvram"):
                    self.assertFalse((f.root / path).exists(), path)
                self.assertNotIn("enable --now", f.calls.read_text())
                conf = (f.root / "etc/mkinitcpio.conf.d/zz-imac-igpu-experimental.conf").read_text()
                self.assertIn('MODULES=(i915 "${MODULES[@]}")', conf)
                self.assertNotIn("acpi_override", conf)

    def test_either_apply_order_retains_brightness_and_enables_intel(self):
        for backend in (fixtures.ModuleTests, fixtures.GrubModuleTests):
            for order in (("macos", "igpu"), ("igpu", "macos")):
                with self.subTest(backend=backend.__name__, order=order):
                    f = self.fixture(backend)
                    apply = "; ".join(f"mod_{module}_apply >/dev/null" for module in order)
                    result = self.run_module(f, apply + "; " + BOOTED + '''
mod_igpu_detect
mod_macos_detect
igpu_cmdline_present
''')
                    self.assertEqual(result.stdout.splitlines(), ["applied", "applied"])
                    self.assertTrue((f.root / "etc/initcpio/acpi_override/imac-bcl100.aml").exists())
                    self.assertTrue((f.root / "etc/systemd/system/imac-backlight-nvram.service").exists())
                    if backend is fixtures.GrubModuleTests:
                        self.assertNotIn("module_blacklist=i915", f.cfg.read_text())
                        self.assertIn("i915.vbt_firmware=", f.cfg.read_text().split("(recovery)")[1])

    def test_removing_igpu_keeps_brightness_and_requires_reboot_to_disable_intel(self):
        for backend in (fixtures.ModuleTests, fixtures.GrubModuleTests):
            with self.subTest(backend=backend.__name__):
                f = self.fixture(backend)
                result = self.run_module(f, '''
mod_macos_apply >/dev/null && mod_igpu_apply >/dev/null || exit 1
''' + BOOTED + '''
mod_igpu_remove >/dev/null || exit 1
mod_igpu_detect
mod_macos_detect
rm -f "$MACOS_IGPU/driver"
rm -rf "$MACOS_IGPU/drm"
mod_macos_detect
''')
                self.assertEqual(result.stdout.splitlines(), ["not-applied", "partial", "applied"])
                self.assertEqual((f.root / "etc/initcpio/acpi_override/imac-bcl100.aml").read_bytes(), b"AML")
                for path in ("etc/systemd/system/imac-backlight-nvram.service",
                             "usr/local/bin/imac-backlight-nvram", "etc/initcpio/post/imac-setos"):
                    self.assertTrue((f.root / path).exists(), path)
                self.assertNotIn("disable --now", f.calls.read_text())
                if backend is fixtures.GrubModuleTests:
                    self.assertIn("module_blacklist=i915,i2c_i801", f.cfg.read_text())
                    self.assertIn(f.EDITED, f.kernel.read_bytes())

    def test_removing_brightness_keeps_the_independent_igpu_install(self):
        for backend in (fixtures.ModuleTests, fixtures.GrubModuleTests):
            with self.subTest(backend=backend.__name__):
                f = self.fixture(backend)
                result = self.run_module(f, '''
mod_macos_apply >/dev/null && mod_igpu_apply >/dev/null || exit 1
''' + BOOTED + '''
mod_macos_remove >/dev/null || exit 1
mod_igpu_detect
mod_macos_detect
''')
                self.assertEqual(result.stdout.splitlines(), ["applied", "not-applied"])
                for path in ("etc/initcpio/acpi_override/imac-bcl100.aml",
                             "etc/systemd/system/imac-backlight-nvram.service"):
                    self.assertFalse((f.root / path).exists(), path)
                for path in ("etc/initcpio/post/imac-setos", "usr/lib/firmware/imac18-3/headless-vbt.bin",
                             "etc/udev/rules.d/61-imac-dri-names.rules",
                             "etc/udev/rules.d/62-imac-smbus-acpi.rules"):
                    self.assertTrue((f.root / path).exists(), path)
                if backend is fixtures.GrubModuleTests:
                    self.assertIn(f.EDITED, f.kernel.read_bytes())
                    self.assertNotIn("module_blacklist=i915", f.cfg.read_text())

    def test_removing_the_last_module_restores_plain_boot_in_either_order(self):
        for backend in (fixtures.ModuleTests, fixtures.GrubModuleTests):
            for order in (("macos", "igpu"), ("igpu", "macos")):
                with self.subTest(backend=backend.__name__, order=order):
                    f = self.fixture(backend)
                    remove = " && ".join(f"mod_{module}_remove >/dev/null" for module in order)
                    self.run_module(f, "mod_macos_apply >/dev/null && mod_igpu_apply >/dev/null && " + remove)
                    for path in ("etc/initcpio/post/imac-setos", "usr/lib/firmware/imac18-3/headless-vbt.bin",
                                 "etc/mkinitcpio.conf.d/zz-imac-igpu-experimental.conf",
                                 "etc/mkinitcpio.conf.d/zz-imac-igpu.conf"):
                        self.assertFalse((f.root / path).exists(), path)
                    if backend is fixtures.GrubModuleTests:
                        self.assertEqual(f.kernel.read_bytes(), f.stock)
                        self.assertNotIn("i915", f.cfg.read_text())

    def test_standalone_removal_restores_shared_files_and_kernel(self):
        for backend in (fixtures.ModuleTests, fixtures.GrubModuleTests):
            with self.subTest(backend=backend.__name__):
                f = self.fixture(backend)
                self.run_module(f, "mod_igpu_apply >/dev/null && mod_igpu_remove >/dev/null")
                self.assertFalse((f.root / "etc/initcpio/post/imac-setos").exists())
                self.assertFalse((f.root / "etc/mkinitcpio.conf.d/zz-imac-igpu-experimental.conf").exists())
                if backend is fixtures.GrubModuleTests:
                    self.assertEqual(f.kernel.read_bytes(), f.stock)

    def test_restore_failure_leaves_the_standalone_install_intact(self):
        for backend in (fixtures.ModuleTests, fixtures.GrubModuleTests):
            with self.subTest(backend=backend.__name__):
                f = self.fixture(backend)
                self.run_module(f, '''
mod_igpu_apply >/dev/null || exit 1
macos_restore_images() { return 1; }
if mod_igpu_remove; then exit 1; fi
[[ -f $IGPU_MKI && -x $MACOS_HOOK && -f $MACOS_VBT ]]
''')

    def test_unsupported_model_is_refused_before_installing_anything(self):
        for backend in (fixtures.ModuleTests, fixtures.GrubModuleTests):
            with self.subTest(backend=backend.__name__):
                f = self.fixture(backend)
                result = self.run_module(f, '''
product=iMac19,1
mod_igpu_detect
if mod_igpu_apply; then exit 1; fi
[[ ! -f $IGPU_MKI && ! -x $MACOS_HOOK ]]
''')
                self.assertEqual(result.stdout.splitlines()[0], "n/a")

    def test_all_skips_both_experiments_but_explicit_igpu_selection_runs(self):
        f = self.fixture(fixtures.ModuleTests)
        result = self.run_module(f, driver() + '''
MODULES=(macos igpu hdr)
mod_hdr_tier() { echo experimental; }
run_module() { echo "RUN $*"; }
run_all_modules
run_modules apply igpu
''')
        self.assertEqual(result.stdout.splitlines(), ["RUN apply macos", "RUN apply igpu"])

    def test_igpu_preflight_only_offers_video_packages_not_brightness_tools(self):
        f = self.fixture(fixtures.ModuleTests)
        result = self.run_module(f, '''
pacman() { return 1; }
macos_offer_packages() { echo "OFFER $*"; }
mod_igpu_preflight
''', iasl=False)
        self.assertIn("OFFER intel-media-driver libva-utils", result.stdout)
        self.assertNotIn("OFFER iasl", result.stdout)

    def test_failed_rebuild_is_not_reported_as_a_successful_igpu_apply(self):
        for backend in (fixtures.ModuleTests, fixtures.GrubModuleTests):
            with self.subTest(backend=backend.__name__):
                f = self.fixture(backend)
                self.run_module(f, '''
sync_boot_files() { return 1; }
if mod_igpu_apply; then exit 1; fi
mod_igpu_detect
''')

    def test_conflicting_grub_blacklist_fails_verification(self):
        f = self.fixture(fixtures.GrubModuleTests)
        self.run_module(f, '''
igpu_add_cmdline() {
    local opts=()
    read -ra opts <<< "$IGPU_OPTS"
    grub_cmdline_add_linux "${opts[@]}" module_blacklist=i915,i2c_i801
}
if mod_igpu_apply; then exit 1; fi
mod_igpu_detect
''')


if __name__ == "__main__":
    unittest.main()
