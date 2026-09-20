"""macOS mode: the set_os edit made to the UKI, the headless-i915 install, the
full-range brightness table and the gates that keep all of it away from the
machines it was never verified on.

The module runs against a temporary root with stubbed sudo, systemctl, udevadm
and boot helpers; the hook, the NVRAM writer and the table builder run for
real against fixtures. Nothing touches the host.
"""
import importlib.util
import os
from pathlib import Path
import re
import struct
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PATCHER = (ROOT / "scripts/imac-patcher").read_text()
PLATFORM = (ROOT / "scripts/lib/platform.sh").read_text()
SETOS = ROOT / "scripts/imac-setos"
NVRAM = ROOT / "scripts/imac-backlight-nvram"
MODELS = ("iMac15,1", "iMac17,1", "iMac18,3", "iMac19,1",
          "iMac20,1", "iMac20,2", "iMacPro1,1")

# The kernel's list, as apple_match_product_name() stores it: eight 15-byte
# slots, NUL padded. Verified byte for byte against 7.2.5-3-omarchy.
STOCK_MODELS = [b"MacBookPro11,3", b"MacBookPro11,5", b"MacBookPro13,3",
                b"MacBookPro14,3", b"MacBookPro15,1", b"MacBookPro15,3",
                b"MacBookPro16,1", b"MacBookPro16,4"]


def model_table(models):
    return b"".join(m.ljust(15, b"\0") for m in models)


def module_section():
    start = PATCHER.index("# ═══════════════════════ module: macos ")
    return PATCHER[start:PATCHER.index("# ═══════════════════════ module: 5k ", start)]


bcl_spec = importlib.util.spec_from_file_location("make_bcl_table", ROOT / "scripts/make-bcl-table.py")
BCL = importlib.util.module_from_spec(bcl_spec)
bcl_spec.loader.exec_module(BCL)

# One ABCL method in the shape Apple's PEG0GFX0 SSDT has: two leading entries
# (AC, battery) and levels 1..80.
STOCK_DSL = '''DefinitionBlock ("", "SSDT", 1, "APPLE ", "PEG0GFX0", 0x00001000)
{
    Scope (\\_SB.PCI0.PEG0.GFX0)
    {
        Method (ABCL, 0, NotSerialized)
        {
            Return (Package (0x52)
            {
                0x50,
                0x32,
                %s
            })
        }
    }
}
''' % (",\n                ".join("0x%02X" % i for i in range(1, 81)))


class GateTests(unittest.TestCase):
    """Who gets offered macOS mode, and who is told why not."""

    def run_shell(self, model, code, extra_env=None):
        env = dict(os.environ, **(extra_env or {}))
        return subprocess.run(
            ["bash", "-c", PLATFORM + f'''
set -uo pipefail
product=$1
REPO_DIR="{ROOT}"
SCRIPT_DIR="{ROOT}/scripts"
LIMINE_DROPIN_DIR=/nonexistent
imac_product_name() {{ printf '%s\\n' "$product"; }}
say() {{ printf '%s\\n' "$*"; }}
warn() {{ printf '%s\\n' "$*"; }}
''' + code, "test", model], text=True, capture_output=True, timeout=30, env=env)

    def test_only_the_imac18_3_is_offered_macos_mode(self):
        for model in MODELS:
            with self.subTest(model=model):
                result = self.run_shell(model, "imac_macos_mode_supported")
                self.assertEqual(result.returncode == 0, model == "iMac18,3", result.stderr)

    def test_the_imac_pro_is_told_it_has_no_integrated_gpu(self):
        """iMacPro1,1 is not merely untested: the Xeon W has no iGPU at all."""
        result = self.run_shell("iMacPro1,1", module_section() + "mod_macos_preflight")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no integrated GPU", result.stdout)
        self.assertNotIn("unchecked", result.stdout)

    def test_other_models_are_refused_as_unverified_not_as_impossible(self):
        for model in ("iMac15,1", "iMac17,1", "iMac19,1", "iMac20,1", "iMac20,2"):
            with self.subTest(model=model):
                result = self.run_shell(model, module_section() + "mod_macos_preflight")
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("verified only on iMac18,3", result.stdout)
                self.assertIn("unchecked", result.stdout)

    def test_the_grub_and_fedora_backends_are_refused(self):
        """The edit lands inside the UKI limine-mkinitcpio builds; no other
        backend here builds one."""
        for backend in ("imac_is_fedora() { return 0; }",
                        "imac_is_arch_grub() { return 0; }",
                        "imac_has_limine() { return 1; }"):
            with self.subTest(backend=backend):
                result = self.run_shell("iMac18,3", backend + "\n" + module_section() + "mod_macos_preflight")
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Omarchy/Limine boot path", result.stdout)


class ModuleTests(unittest.TestCase):
    """Apply, detect and remove against a temporary root."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.home = self.root / "home"
        self.bin = self.root / "repo-scripts"
        self.home.mkdir()
        self.bin.mkdir()
        (self.home / ".config/hypr").mkdir(parents=True)
        # Stand-ins for the files the module installs from the repo.
        for name in ("imac-setos", "imac-backlight-nvram"):
            (self.bin / name).write_text("#!/bin/sh\nexit 0\n")
            (self.bin / name).chmod(0o755)
        # The image mkinitcpio has just rebuilt, with the hook's edit in it.
        self.uki = self.root / "uki.efi"
        self.uki.write_bytes(b"prefix" + model_table(STOCK_MODELS[:-1] + [b"iMac18,3"]))
        self.calls = self.root / "calls"

    def bcl_stub(self, ok=True):
        """Stand in for make-bcl-table.py, which needs real ACPI tables."""
        path = self.bin / "make-bcl-table.py"
        body = ("import sys, pathlib\n"
                "pathlib.Path(sys.argv[1]).parent.mkdir(parents=True, exist_ok=True)\n"
                "pathlib.Path(sys.argv[1]).write_bytes(b'AML')\n" if ok
                else "import sys\nsys.exit(4)\n")
        path.write_text(body)
        return path

    def overrides(self, **kwargs):
        paths = {
            "MACOS_HOOK": self.root / "etc/initcpio/post/imac-setos",
            "MACOS_MKI": self.root / "etc/mkinitcpio.conf.d/zz-imac-igpu.conf",
            "MACOS_DROPIN": self.root / "etc/limine-entry-tool.d/imac5k-macos.conf",
            "MACOS_VBT_DIR": self.root / "usr/lib/firmware/imac18-3",
            "MACOS_VBT": self.root / "usr/lib/firmware/imac18-3/headless-vbt.bin",
            "MACOS_AML": self.root / "etc/initcpio/acpi_override/imac-bcl100.aml",
            "MACOS_NVRAM_BIN": self.root / "usr/local/bin/imac-backlight-nvram",
            "MACOS_NVRAM_UNIT": self.root / "etc/systemd/system/imac-backlight-nvram.service",
            "MACOS_HYPR": self.home / ".config/hypr/imac-gpu.lua",
            "MACOS_HYPR_MAIN": self.home / ".config/hypr/hyprland.lua",
            "MACOS_IGPU": self.root / "sys/igpu",
            "MACOS_ACPI_INSTALL_HOOKS": None,   # set as an array below
            "UDEV_DIR": self.root / "etc/udev/rules.d",
        }
        paths.update(kwargs)
        lines = [f'{k}="{v}"' for k, v in paths.items() if v is not None]
        lines.append(f'MACOS_ACPI_INSTALL_HOOKS=("{self.root}/acpi_override_hook")')
        return "\n".join(lines) + "\n"

    def run_module(self, code, *, iasl=True, acpi_hook=True, dropin_has="",
                   igpu=False, enabled="disabled", bcl_ok=True, product="iMac18,3"):
        self.bcl_stub(bcl_ok)
        if acpi_hook:
            (self.root / "acpi_override_hook").write_text("hook")
        if igpu:
            (self.root / "sys").mkdir(exist_ok=True)
            (self.root / "sys/igpu").write_text("")
        stubs = f'''
set -uo pipefail
export HOME="{self.home}"
product={product}
SCRIPT_DIR="{self.bin}"
REPO_DIR="{ROOT}"
MACOS_CFG="{ROOT}/configs/macos"
LIMINE_DROPIN_DIR="{self.root}/etc/limine-entry-tool.d"
LIMINE_DEFAULT="{self.root}/etc/default/limine"
UKI_PATH="{self.uki}"
say()  {{ printf '%s\\n' "$*"; }}
warn() {{ printf '%s\\n' "$*"; }}
confirm() {{ return 0; }}
sudo() {{ "$@"; }}
# Tools the preflight looks for. Defining them as functions is enough:
# command -v finds a function.
limine-mkinitcpio() {{ :; }}
mkinitcpio() {{ :; }}
objcopy() {{ :; }}
udevadm() {{ echo "UDEVADM $*" >> "{self.calls}"; }}
systemctl() {{
    echo "SYSTEMCTL $*" >> "{self.calls}"
    [[ $1 == is-enabled ]] && printf '{enabled}\\n'
    return 0
}}
pacman() {{ return 0; }}   # intel-media-driver already installed
imac_pkg_installer() {{ return 1; }}
imac_macos_mode_supported() {{ [[ $product == iMac18,3 ]]; }}
imac_has_limine() {{ return 0; }}
imac_is_fedora() {{ return 1; }}
imac_is_arch_grub() {{ return 1; }}
imac_tool_package() {{ printf '%s\\n' "$1"; }}
boot_config_has() {{ [[ -n "{dropin_has}" ]] && [[ "{dropin_has}" == *"$1"* ]]; }}
sync_boot_files() {{ echo "SYNC" >> "{self.calls}"; }}
verify_cmdline() {{ echo "VERIFY ${{1:-}} ${{2:-}}" >> "{self.calls}"; }}
'''
        if iasl:
            stubs += "iasl() { :; }\n"
        script = stubs + module_section() + self.overrides() + code
        # The installed rules live under a test-owned udev directory.
        script = script.replace('"/etc/udev/rules.d/${rule}"', '"${UDEV_DIR}/${rule}"')
        script = script.replace('"/etc/udev/rules.d/${MACOS_RULES[0]}"', '"${UDEV_DIR}/${MACOS_RULES[0]}"')
        script = script.replace('"/etc/udev/rules.d/${MACOS_RULES[1]}"', '"${UDEV_DIR}/${MACOS_RULES[1]}"')
        return subprocess.run(["bash", "-c", script], text=True, capture_output=True, timeout=60)

    # ── detection ──────────────────────────────────────────────────────────
    def test_nothing_installed_reads_as_not_applied(self):
        result = self.run_module("mod_macos_detect")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "not-applied")

    def test_an_untouched_unsupported_machine_reads_as_na(self):
        result = self.run_module("mod_macos_detect", product="iMac19,1")
        self.assertEqual(result.stdout.strip(), "n/a")

    def test_an_installed_module_stays_removable_on_a_machine_that_lost_its_gate(self):
        """n/a must never strand files: an install on a model the gate later
        rejects still reports a state --remove can act on."""
        result = self.run_module("mod_macos_apply >/dev/null; product=iMac19,1; mod_macos_detect")
        self.assertEqual(result.stdout.strip(), "partial", result.stdout)

    def test_applying_leaves_partial_until_the_reboot_then_applied(self):
        applied = "i915.vbt_firmware=imac18-3"
        pending = self.run_module("mod_macos_apply >/dev/null; mod_macos_detect",
                                  dropin_has=applied, enabled="enabled")
        self.assertEqual(pending.stdout.strip(), "partial", pending.stdout)
        booted = self.run_module("mod_macos_apply >/dev/null; mod_macos_detect",
                                 dropin_has=applied, enabled="enabled", igpu=True)
        self.assertEqual(booted.stdout.strip(), "applied", booted.stdout)

    def test_an_acpi_hook_without_its_table_is_not_a_complete_install(self):
        """A drop-in asking for acpi_override with no .aml fails every later
        initramfs build, so it must never read as applied."""
        result = self.run_module(
            'mod_macos_apply >/dev/null; rm -f "$MACOS_AML"; macos_initramfs_conf_ok && echo ok || echo broken',
            dropin_has="i915.vbt_firmware=imac18-3", enabled="enabled")
        self.assertEqual(result.stdout.strip(), "broken", result.stdout)

    # ── the boot configuration ─────────────────────────────────────────────
    def test_the_kernel_parameters_are_appended_by_a_dropin(self):
        """Omarchy's /etc/default/limine assigns with '+=', so editing that
        line in place silently matches nothing. The parameters go in a
        limine-entry-tool.d drop-in that appends, like the 5K one."""
        result = self.run_module("mod_macos_apply >/dev/null")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        dropin = (self.root / "etc/limine-entry-tool.d/imac5k-macos.conf").read_text()
        self.assertRegex(dropin, re.compile(r'^KERNEL_CMDLINE\[default\]\+=" ', re.M))
        for option in ("snd_hda_core.gpu_bind=0", "i915.disable_display=1",
                       "i915.vbt_firmware=imac18-3/headless-vbt.bin",
                       "module_blacklist=i2c_i801"):
            self.assertIn(option, dropin)
        # /etc/default/limine is never edited: on Omarchy it appends with '+=',
        # which an in-place edit of that line would silently miss.
        self.assertFalse((self.root / "etc/default/limine").exists())

    def test_apply_installs_every_piece_and_rebuilds_the_boot_image(self):
        result = self.run_module("mod_macos_apply")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for path in ("etc/initcpio/post/imac-setos",
                     "usr/lib/firmware/imac18-3/headless-vbt.bin",
                     "etc/udev/rules.d/61-imac-dri-names.rules",
                     "etc/udev/rules.d/62-imac-smbus-acpi.rules",
                     "etc/mkinitcpio.conf.d/zz-imac-igpu.conf",
                     "usr/local/bin/imac-backlight-nvram",
                     "etc/systemd/system/imac-backlight-nvram.service"):
            self.assertTrue((self.root / path).exists(), path)
        calls = self.calls.read_text()
        self.assertIn("SYNC", calls)
        self.assertIn("SYSTEMCTL enable --now imac-backlight-nvram.service", calls)
        # The VBT must be the committed binary, not a copy of something else.
        self.assertEqual((self.root / "usr/lib/firmware/imac18-3/headless-vbt.bin").read_bytes(),
                         (ROOT / "configs/macos/headless-vbt.bin").read_bytes())

    def test_a_uki_that_lost_the_edit_fails_the_apply(self):
        """The whole feature is that one edit; a rebuild without it must not
        report success."""
        self.uki.write_bytes(b"prefix" + model_table(STOCK_MODELS))
        result = self.run_module("mod_macos_apply")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("does not list iMac18,3", result.stdout)

    def test_a_patched_uki_passes_the_apply(self):
        result = self.run_module("mod_macos_apply")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("set_os model list entry", result.stdout)

    # ── the optional brightness table ──────────────────────────────────────
    def test_without_iasl_the_firmware_range_is_kept_and_no_hook_is_asked_for(self):
        result = self.run_module("mod_macos_apply", iasl=False)
        self.assertIn("keeping the firmware's brightness range", result.stdout)
        self.assertNotIn("acpi_override", (self.root / "etc/mkinitcpio.conf.d/zz-imac-igpu.conf").read_text())
        self.assertFalse((self.root / "etc/initcpio/acpi_override/imac-bcl100.aml").exists())

    def test_a_table_that_cannot_be_built_safely_is_not_installed(self):
        result = self.run_module("mod_macos_apply", bcl_ok=False)
        self.assertIn("full-range brightness table was not built", result.stdout)
        self.assertNotIn("acpi_override", (self.root / "etc/mkinitcpio.conf.d/zz-imac-igpu.conf").read_text())

    def test_the_hook_is_enabled_only_together_with_a_built_table(self):
        result = self.run_module("mod_macos_apply")
        conf = (self.root / "etc/mkinitcpio.conf.d/zz-imac-igpu.conf").read_text()
        self.assertIn("HOOKS+=(acpi_override)", conf)
        self.assertTrue((self.root / "etc/initcpio/acpi_override/imac-bcl100.aml").exists())
        self.assertIn("levels 4..100", result.stdout)

    def test_a_mkinitcpio_without_the_override_hook_keeps_the_firmware_range(self):
        result = self.run_module("mod_macos_apply", acpi_hook=False)
        self.assertIn("no acpi_override hook", result.stdout)
        self.assertNotIn("acpi_override", (self.root / "etc/mkinitcpio.conf.d/zz-imac-igpu.conf").read_text())

    # ── the compositor pin ─────────────────────────────────────────────────
    def test_hyprland_is_pinned_before_the_monitors_require(self):
        (self.home / ".config/hypr/hyprland.lua").write_text(
            'require("default.hypr.omarchy")\nrequire("hypr.monitors")\n')
        self.run_module("mod_macos_apply >/dev/null")
        text = (self.home / ".config/hypr/hyprland.lua").read_text()
        self.assertLess(text.index('require("hypr.imac-gpu")'), text.index('require("hypr.monitors")'))
        self.assertTrue((self.home / ".config/hypr/imac-gpu.lua").exists())

    def test_hyprland_is_pinned_even_without_the_usual_anchor(self):
        (self.home / ".config/hypr/hyprland.lua").write_text('require("default.hypr.omarchy")\n')
        self.run_module("mod_macos_apply >/dev/null")
        self.assertIn('require("hypr.imac-gpu")',
                      (self.home / ".config/hypr/hyprland.lua").read_text())

    def test_a_second_apply_does_not_add_the_require_twice(self):
        (self.home / ".config/hypr/hyprland.lua").write_text('require("hypr.monitors")\n')
        self.run_module("mod_macos_apply >/dev/null; mod_macos_apply >/dev/null")
        text = (self.home / ".config/hypr/hyprland.lua").read_text()
        self.assertEqual(text.count('require("hypr.imac-gpu")'), 1)

    def test_no_hyprland_config_is_not_a_failure(self):
        result = self.run_module("mod_macos_apply")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertFalse((self.home / ".config/hypr/imac-gpu.lua").exists())

    # ── removal ────────────────────────────────────────────────────────────
    def test_remove_takes_back_everything_apply_installed(self):
        (self.home / ".config/hypr/hyprland.lua").write_text('require("hypr.monitors")\n')
        result = self.run_module("mod_macos_apply >/dev/null; mod_macos_remove")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for path in ("etc/initcpio/post/imac-setos",
                     "usr/lib/firmware/imac18-3/headless-vbt.bin",
                     "etc/udev/rules.d/61-imac-dri-names.rules",
                     "etc/udev/rules.d/62-imac-smbus-acpi.rules",
                     "etc/mkinitcpio.conf.d/zz-imac-igpu.conf",
                     "etc/initcpio/acpi_override/imac-bcl100.aml",
                     "etc/limine-entry-tool.d/imac5k-macos.conf",
                     "usr/local/bin/imac-backlight-nvram",
                     "etc/systemd/system/imac-backlight-nvram.service"):
            self.assertFalse((self.root / path).exists(), path)
        self.assertFalse((self.home / ".config/hypr/imac-gpu.lua").exists())
        self.assertNotIn("imac-gpu", (self.home / ".config/hypr/hyprland.lua").read_text())
        self.assertIn("SYSTEMCTL disable --now imac-backlight-nvram.service", self.calls.read_text())

    def test_remove_also_clears_parameters_left_in_the_limine_default(self):
        """An older layout appended them straight into /etc/default/limine."""
        default = self.root / "etc/default/limine"
        default.parent.mkdir(parents=True, exist_ok=True)
        opts = re.search(r'^MACOS_OPTS="([^"]+)"', module_section(), re.M)[1]
        default.write_text(f'KERNEL_CMDLINE[default]+="root=/dev/x {opts}"\n')
        result = self.run_module("mod_macos_remove")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(default.read_text(), 'KERNEL_CMDLINE[default]+="root=/dev/x"\n')


class SetOsHookTests(unittest.TestCase):
    """The 14-byte edit the mkinitcpio post hook makes to each UKI."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.dmi = self.root / "product_name"
        self.dmi.write_text("iMac18,3\n")

    def image(self, table=None, name="uki.efi"):
        path = self.root / name
        path.write_bytes(b"\x7fELF padding" + (table if table is not None
                                               else model_table(STOCK_MODELS)) + b"tail bytes")
        return path

    def run_hook(self, *images, product=None):
        env = dict(os.environ, IMAC_DMI_PRODUCT=str(product if product else self.dmi))
        return subprocess.run([str(SETOS), "7.2.5-test", *[str(i) for i in images]],
                              text=True, capture_output=True, timeout=30, env=env)

    def test_the_last_slot_becomes_this_imac(self):
        uki = self.image()
        result = self.run_hook(uki)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("iMac18,3 added", result.stdout)
        data = uki.read_bytes()
        self.assertIn(model_table(STOCK_MODELS[:-1] + [b"iMac18,3"]), data)
        # Only the one slot moved: everything around it is untouched.
        self.assertEqual(len(data), len(b"\x7fELF padding" + model_table(STOCK_MODELS) + b"tail bytes"))
        self.assertTrue(data.startswith(b"\x7fELF padding") and data.endswith(b"tail bytes"))

    def test_running_twice_changes_nothing(self):
        uki = self.image()
        self.run_hook(uki)
        first = uki.read_bytes()
        result = self.run_hook(uki)
        self.assertIn("already lists", result.stdout)
        self.assertEqual(uki.read_bytes(), first)

    def test_a_kernel_whose_list_moved_is_left_stock_without_failing_the_build(self):
        """A kernel update must never be stopped by this hook."""
        uki = self.image(table=model_table([b"MacBookPro99,9"] * 8))
        before = uki.read_bytes()
        result = self.run_hook(uki)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("WARNING", result.stdout)
        self.assertIn("stays hidden", result.stdout)
        self.assertEqual(uki.read_bytes(), before)

    def test_another_mac_is_left_alone(self):
        other = self.root / "other_product"
        other.write_text("MacBookPro16,4\n")
        uki = self.image()
        before = uki.read_bytes()
        result = self.run_hook(uki, product=other)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(uki.read_bytes(), before)
        self.assertEqual(result.stdout, "")

    def test_the_kernel_image_and_plain_initramfs_are_not_touched(self):
        """argv[1] is the kernel image and the rest may include a plain
        initramfs; only the UKI is patched."""
        initramfs = self.image(name="initramfs.img")
        before = initramfs.read_bytes()
        result = self.run_hook(initramfs)
        self.assertEqual(result.stdout, "")
        self.assertEqual(initramfs.read_bytes(), before)

    def test_an_unreadable_image_warns_instead_of_raising(self):
        missing = self.root / "gone.efi"
        result = self.run_hook(missing)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("WARNING", result.stdout)

    def test_the_hook_matches_the_list_in_the_running_kernel(self):
        """The eight models are a fact about the kernel, not a guess. Skipped
        where the image is unreadable (some distributions ship it root-only)."""
        vmlinuz = Path(f"/usr/lib/modules/{os.uname().release}/vmlinuz")
        if not vmlinuz.is_file() or not os.access(vmlinuz, os.R_OK):
            self.skipTest("no readable kernel image for this release")
        data = vmlinuz.read_bytes()
        if model_table(STOCK_MODELS) not in data:
            self.skipTest("this kernel does not carry the stock set_os model list")
        self.assertEqual(data.count(model_table(STOCK_MODELS)), 1)


class BrightnessTableTests(unittest.TestCase):
    """The ACPI table rewrite, checked on its text rather than on firmware."""

    def test_the_firmware_table_is_recognised_and_the_upgraded_one_is_not_redone(self):
        self.assertTrue(BCL.is_stock(STOCK_DSL))
        self.assertFalse(BCL.is_upgraded(STOCK_DSL))
        upgraded = BCL.rewrite_abcl(STOCK_DSL)
        self.assertTrue(BCL.is_upgraded(upgraded))
        self.assertFalse(BCL.is_stock(upgraded))

    def test_the_rewrite_covers_the_full_range_from_the_macos_floor(self):
        entries = BCL.abcl_entries(BCL.rewrite_abcl(STOCK_DSL))
        self.assertEqual(entries[:2], ["0x64", "0x32"])       # AC, battery
        self.assertEqual(entries[2], "0x04")                  # ~2176 raw, macOS's floor
        self.assertEqual(entries[-1], "0x64")                 # 100 * 655 = 65500
        self.assertEqual(len(entries), 2 + 97)

    def test_a_different_firmware_is_not_rewritten(self):
        """Only the exact table this was written against is touched: anything
        else keeps its own brightness range rather than getting a guess."""
        shorter = STOCK_DSL.replace(
            ",\n                ".join("0x%02X" % i for i in range(41, 81)), "0x28")
        no_method = STOCK_DSL.replace("Method (ABCL, 0, NotSerialized)",
                                      "Method (XBCL, 0, NotSerialized)")
        other_default = STOCK_DSL.replace("                0x50,", "                0x46,", 1)
        self.assertIsNone(BCL.abcl_entries(no_method))
        for table in (shorter, no_method, other_default):
            self.assertFalse(BCL.is_stock(table))
            self.assertFalse(BCL.is_upgraded(table))

    def test_the_oem_revision_is_raised_so_the_kernel_prefers_the_upgrade(self):
        self.assertIn('"PEG0GFX0", 0x00001001)', BCL.bump_oem_revision(STOCK_DSL))

    def test_only_the_abcl_package_and_the_revision_change(self):
        before = STOCK_DSL.replace("\n", " ").split()
        after = BCL.rewrite_abcl(BCL.bump_oem_revision(STOCK_DSL)).replace("\n", " ").split()
        self.assertEqual([w for w in before if "0x" not in w], [w for w in after if "0x" not in w])

    def test_recompile_noise_is_ignored_but_a_real_change_is_not(self):
        """iasl stamps its own creator ID and checksum; anything else differing
        means the round-trip is not faithful and no table gets written."""
        original = bytearray(b"SSDT" + bytes(60))
        rebuilt = bytearray(original)
        rebuilt[9] = 0x42                       # checksum
        rebuilt[28:36] = b"INTL\x01\x02\x03\x04"  # creator id and revision
        self.assertEqual(BCL.differing_offsets(bytes(original), bytes(rebuilt)), [])
        rebuilt[40] = 0xFF
        self.assertEqual(BCL.differing_offsets(bytes(original), bytes(rebuilt)), [40])
        self.assertIsNone(BCL.differing_offsets(bytes(original), bytes(rebuilt) + b"\0"))


class BacklightNvramTests(unittest.TestCase):
    """The shutdown writer that tells the firmware what to light the panel at."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.backlight = self.root / "acpi_video0"
        self.backlight.mkdir()
        self.var = self.root / "backlight-level"
        self.stub_bin = self.root / "bin"
        self.stub_bin.mkdir()
        # efivarfs marks the variable immutable; chattr has no meaning here.
        (self.stub_bin / "chattr").write_text("#!/bin/sh\nexit 0\n")
        (self.stub_bin / "chattr").chmod(0o755)

    def write_var(self, attributes, raw):
        self.var.write_bytes(struct.pack("<IH", attributes, raw))

    def run_writer(self, brightness, maximum, attributes=0x80000007, raw=0):
        (self.backlight / "brightness").write_text(str(brightness))
        (self.backlight / "max_brightness").write_text(str(maximum))
        self.write_var(attributes, raw)
        env = dict(os.environ,
                   PATH=f"{self.stub_bin}:{os.environ['PATH']}",
                   IMAC_BACKLIGHT_DIR=str(self.backlight),
                   IMAC_BACKLIGHT_NVRAM=str(self.var))
        return subprocess.run([str(NVRAM)], text=True, capture_output=True, timeout=30, env=env)

    def stored(self):
        attributes, raw = struct.unpack("<IH", self.var.read_bytes())
        return attributes, raw

    def test_the_upgraded_table_maps_brightness_onto_the_controller_scale(self):
        result = self.run_writer(brightness=50, maximum=96)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.stored()[1], (50 + 4) * 655)

    def test_the_firmware_table_uses_its_own_offset(self):
        self.run_writer(brightness=50, maximum=79)
        self.assertEqual(self.stored()[1], (50 + 1) * 655)

    def test_the_top_of_the_range_is_what_macos_drives(self):
        """Level 100 is 65500 of the controller's 65535 -- 99.95%, against the
        52400 the firmware's own 80-level table tops out at."""
        self.run_writer(brightness=96, maximum=96)
        self.assertEqual(self.stored()[1], 100 * 655)

    def test_the_value_is_clamped_to_the_controller_and_the_macos_floor(self):
        # The firmware's own table starts at level 1 (655 raw), below the
        # level macOS treats as the panel's usable minimum.
        self.run_writer(brightness=0, maximum=79)
        self.assertEqual(self.stored()[1], 2176)
        # The upgraded table starts at 4, which is already above that floor.
        self.run_writer(brightness=0, maximum=96)
        self.assertEqual(self.stored()[1], 4 * 655)
        # A level past the table's end cannot overflow the 16-bit variable.
        self.run_writer(brightness=200, maximum=96)
        self.assertEqual(self.stored()[1], 65535)

    def test_apples_vendor_attribute_is_dropped_because_efivarfs_refuses_it(self):
        self.run_writer(brightness=50, maximum=96, attributes=0x80000007)
        self.assertEqual(self.stored()[0], 0x07)

    def test_an_unchanged_level_is_not_written_back(self):
        """Every write is firmware flash wear, so only a change earns one."""
        result = self.run_writer(brightness=50, maximum=96, raw=(50 + 4) * 655)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_an_unknown_backlight_range_is_left_alone(self):
        result = self.run_writer(brightness=5, maximum=255)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(self.stored()[1], 0)

    def test_a_machine_without_the_nvram_variable_is_a_no_op(self):
        (self.backlight / "brightness").write_text("50")
        (self.backlight / "max_brightness").write_text("96")
        env = dict(os.environ, IMAC_BACKLIGHT_DIR=str(self.backlight),
                   IMAC_BACKLIGHT_NVRAM=str(self.root / "absent"))
        result = subprocess.run([str(NVRAM)], text=True, capture_output=True, timeout=30, env=env)
        self.assertEqual(result.returncode, 0)


class PackagingTests(unittest.TestCase):
    """The release tarball has to carry what the module installs."""

    def test_every_installed_file_ships_in_the_release(self):
        paths = re.search(r"^PATHS=\(([^)]*)\)", (ROOT / "scripts/make-release.sh").read_text(), re.M)[1]
        shipped = set(paths.split())
        for path in ("configs/macos/61-imac-dri-names.rules",
                     "configs/macos/62-imac-smbus-acpi.rules",
                     "configs/macos/zz-imac-igpu.conf",
                     "configs/macos/imac-backlight-nvram.service",
                     "configs/macos/imac-gpu.lua",
                     "configs/macos/headless-vbt.bin",
                     "scripts/imac-setos",
                     "scripts/imac-backlight-nvram",
                     "scripts/make-bcl-table.py",
                     "scripts/imac-igpu-check"):
            self.assertTrue((ROOT / path).exists(), f"{path} is missing")
            self.assertIn(path.split("/")[0], shipped, path)

    def test_the_committed_vbt_is_the_generator_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "vbt.bin"
            subprocess.run(["python3", str(ROOT / "scripts/make-headless-vbt.py"), str(out)],
                           check=True, capture_output=True, timeout=30)
            self.assertEqual(out.read_bytes(), (ROOT / "configs/macos/headless-vbt.bin").read_bytes())

    def test_the_vbt_passes_the_checks_i915_makes_on_it(self):
        blob = (ROOT / "configs/macos/headless-vbt.bin").read_bytes()
        signature, _version, header_size, vbt_size, _checksum, _r, bdb_offset, _aim = \
            struct.unpack_from("<20sHHHBBI16s", blob)
        self.assertEqual(signature[:4], b"$VBT")
        self.assertLessEqual(vbt_size, len(blob))
        self.assertLessEqual(bdb_offset + 22, vbt_size)
        bdb_signature, _bv, bdb_header_size, bdb_size = struct.unpack_from("<16sHHH", blob, bdb_offset)
        self.assertEqual(bdb_signature, b"BIOS_DATA_BLOCK ")
        self.assertLessEqual(bdb_offset + bdb_size, vbt_size)
        # No block fits after the header, so intel_setup_outputs() finds no
        # child devices and creates no connectors: the point of the file.
        self.assertFalse(bdb_header_size + 3 < bdb_size)
        self.assertEqual(header_size, 48)


if __name__ == "__main__":
    unittest.main()
