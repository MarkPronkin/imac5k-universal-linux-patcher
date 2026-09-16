"""The iMac18,3 USB controller fix ships consistently and keeps USB wake.

Apple's XHC1._PS3 resets the machine on the PCH xHCI's second D3 entry. The
module stops Linux from running XHC1's ACPI power methods; holding the
controller in D0 instead (PCI_DEV_FLAGS_NO_D3) was tried first and lost USB
keyboard wake. These checks read the shipped files; nothing is built.
"""
from pathlib import Path
import re
import subprocess
import unittest

from test_patcher_menu import shell_function

ROOT = Path(__file__).resolve().parents[1]
PATCHER = (ROOT / "scripts/imac-patcher").read_text()
PLATFORM = (ROOT / "scripts/lib/platform.sh").read_text()
MODULE = ROOT / "modules/imac5k-xhci-d0"
SOURCE = (MODULE / "imac5k_xhci_d0.c").read_text()


def patcher_constant(name):
    return re.search(rf'(?m)^{name}=(.+)$', PATCHER)[1].strip('"')


def dkms_conf():
    return dict(re.findall(r'(?m)^([A-Z_]+(?:\[0\])?)="([^"]*)"$', (MODULE / "dkms.conf").read_text()))


class PackagingTests(unittest.TestCase):
    def test_dkms_package_matches_the_patcher(self):
        conf = dkms_conf()
        self.assertEqual(conf["PACKAGE_NAME"], patcher_constant("XHCI_FIX_DKMS"))
        self.assertEqual(conf["PACKAGE_VERSION"], patcher_constant("XHCI_FIX_VERSION"))
        self.assertEqual(conf["BUILT_MODULE_NAME[0]"], patcher_constant("XHCI_FIX_MODULE"))
        # Rebuilt automatically for new kernels.
        self.assertEqual(conf["AUTOINSTALL"], "yes")

    def test_kbuild_and_boot_load_name_the_same_module(self):
        module = patcher_constant("XHCI_FIX_MODULE")
        self.assertRegex((MODULE / "Makefile").read_text(), rf"(?m)^obj-m\s*:?=\s*{module}\.o$")
        entries = [line.strip() for line in (ROOT / "configs/imac5k-xhci-d0.conf").read_text().splitlines()
                   if line.strip() and not line.startswith("#")]
        self.assertEqual(entries, [module])
        # systemd-modules-load reads only *.conf files there.
        self.assertRegex(PATCHER, r"(?m)^XHCI_FIX_LOAD_CONF=/etc/modules-load\.d/[\w.-]+\.conf$")

    def test_release_carries_the_module_sources(self):
        paths = re.search(r"(?m)^PATHS=\((.*)\)$", (ROOT / "scripts/make-release.sh").read_text())[1].split()
        self.assertIn("modules", paths)
        self.assertEqual(patcher_constant("XHCI_FIX_SRC"), "${REPO_DIR}/modules/imac5k-xhci-d0")


class ModuleSourceTests(unittest.TestCase):
    def test_it_skips_xhc1_acpi_power_methods_instead_of_holding_d0(self):
        self.assertIn("companion->flags.power_manageable = 0;", SOURCE)
        self.assertIn("companion->flags.power_manageable = 1;", SOURCE)   # restored on unload
        self.assertNotIn("PCI_DEV_FLAGS_NO_D3", SOURCE)                   # lost USB wake
        self.assertIn('acpi_has_method(companion->handle, "_PS3")', SOURCE)
        self.assertIn("module_param(acpi_pm_skipped, bool, 0444);", SOURCE)
        self.assertEqual(patcher_constant("XHCI_FIX_SYSFS"), "/sys/module/imac5k_xhci_d0")
        self.assertIn("acpi_pm_skipped", shell_function(PATCHER, "xhci_fix_live"))

    def test_only_the_verified_model_binds_without_force(self):
        table = SOURCE[SOURCE.index("affected[] = {"):SOURCE.index("};", SOURCE.index("affected[] = {"))]
        self.assertEqual(re.findall(r'DMI_PRODUCT_NAME, "([^"]+)"', table), ["iMac18,3"])
        self.assertIn('force && dmi_match(DMI_SYS_VENDOR, "Apple Inc.")', SOURCE)


class GateTests(unittest.TestCase):
    def run_shell(self, model, code):
        return subprocess.run(["bash", "-c", PLATFORM + f'''
set -uo pipefail
imac_product_name() {{ echo {model}; }}
''' + code], text=True, capture_output=True, timeout=10)

    def test_only_imac18_3_gets_the_fix(self):
        for model in ("iMac15,1", "iMac17,1", "iMac18,3", "iMac19,1", "iMac20,1", "iMac20,2", "iMacPro1,1"):
            with self.subTest(model=model):
                result = self.run_shell(model, "imac_xhci_fix_supported")
                self.assertEqual(result.returncode == 0, model == "iMac18,3")

    def test_startup_audit_lists_the_build_tools_only_where_the_fix_applies(self):
        audit = shell_function(PATCHER, "startup_deps_note") + '''
declare -A MODULE_STATES=([suspend]=partial)
MODULES=(suspend)
KREL=7.2.3-test
REPO_DIR=/nonexistent
imac_is_fedora() { return 1; }
imac_is_kde() { return 1; }
imac_is_arch_grub() { return 1; }
xhci_fix_target_kernels() { :; }
startup_need_headers() { STARTUP_NEEDS_HEADERS=1; }
PATH=/nonexistent
startup_deps_note
echo "MISSING=${STARTUP_MISSING_TOOLS[*]} HEADERS=$STARTUP_NEEDS_HEADERS"
'''
        result = self.run_shell("iMac18,3", audit)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("MISSING=systemctl dkms gcc make modinfo depmod modprobe HEADERS=1", result.stdout)
        result = self.run_shell("iMac17,1", audit)
        self.assertIn("MISSING=systemctl HEADERS=0", result.stdout)


if __name__ == "__main__":
    unittest.main()
