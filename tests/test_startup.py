"""Launch the unmodified patcher with tools really absent from an isolated /usr/bin.

Bubblewrap makes the host read-only, hides host commands, and disables network
access. Only fake package managers can run. Ordinary unit tests still run when
Linux user namespaces or bubblewrap are unavailable.
"""
from pathlib import Path
import os
import pty
import shutil
import subprocess
import tempfile
import unittest

from test_deps import COREUTILS


ROOT = Path(__file__).resolve().parents[1]
BWRAP = shutil.which("bwrap")


class StartupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not BWRAP:
            cls.unavailable("bubblewrap is needed for isolated full-launcher tests")
        probe = subprocess.run(
            [BWRAP, "--unshare-all", "--ro-bind", "/", "/", "--", "/usr/bin/true"],
            text=True, capture_output=True, timeout=10,
        )
        if probe.returncode:
            cls.unavailable("bubblewrap user namespaces unavailable: " + probe.stderr.strip())
        # The sandbox maps only the calling user, so a checkout owned by another
        # user is unreadable inside it — the root-run CI job cannot traverse the
        # runner-owned home. Launch an unmodified copy of the checkout that this
        # user owns instead.
        checkout = tempfile.TemporaryDirectory()
        cls.addClassCleanup(checkout.cleanup)
        cls.repo = Path(checkout.name) / "repo"
        shutil.copytree(ROOT, cls.repo,
                        ignore=shutil.ignore_patterns(".git", "dist", "__pycache__", "hardware-private"))

    @staticmethod
    def unavailable(reason):
        if os.environ.get("IMAC5K_REQUIRE_STARTUP_TESTS") == "1":
            raise RuntimeError(reason)
        raise unittest.SkipTest(reason)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.available = self.root / "tools"
        self.available.mkdir()
        self.commands = {"bash", "env", "grep", "sed", "awk", "find", *COREUTILS}
        for command in self.commands:
            shutil.copy2(shutil.which(command), self.available / command)
        self.stub("uname", "echo 7.2.2-startup-test")
        self.stub("sudo", '''
case "$1" in
    pacman|dnf) exec "$@" ;;
    *) exit 1 ;;
esac''')
        self.package_manager("pacman")
        self.package_manager("dnf")
        self.sys = self.root / "sys"
        dmi = self.sys / "class/dmi/id"
        dmi.mkdir(parents=True)
        (dmi / "product_name").write_text("iMac18,3\n")
        gpu = self.sys / "class/drm/card0/device"
        gpu.mkdir(parents=True)
        (self.sys / "bus/pci/drivers/amdgpu").mkdir(parents=True)
        (gpu / "driver").symlink_to("/sys/bus/pci/drivers/amdgpu")
        self.os_release = self.root / "os-release"
        self.os_release.write_text("ID=arch\n")
        self.defaults = self.root / "default"
        self.defaults.mkdir()

    def stub(self, name, body):
        path = self.available / name
        path.write_text("#!/usr/bin/bash\n" + body + "\n")
        path.chmod(0o755)
        self.commands.add(name)

    def package_manager(self, name, mode="install"):
        self.stub(name, '''
echo "PACKAGE_MANAGER $0 $*"
''' + {"fail": "exit 1", "empty": "exit 0", "install": '''
for package in "$@"; do
    case "$package" in
        coreutils) tools="''' + " ".join(COREUTILS) + '''" ;;
        findutils) tools=find ;;
        gawk) tools=awk ;;
        grep|sed) tools=$package ;;
        *) continue ;;
    esac
    for tool in $tools; do
        [[ -x /usr/bin/$tool ]] || "$STARTUP_TEST_TOOLS/ln" -s "$STARTUP_TEST_TOOLS/$tool" "/usr/bin/$tool"
    done
done
'''}[mode])

    def launch(self, *args, missing=(), answer="", fedora=False, desktop="", terminal=False,
               symlink=False, gum=False, both_managers=False, distro="arch", grub=False, limine=False):
        self.os_release.write_text("ID=fedora\n" if fedora else f"ID={distro}\nID_LIKE=arch\n")
        for name, enabled in (("grub", grub), ("limine", limine)):
            path = self.defaults / name
            if enabled:
                path.write_text('GRUB_CMDLINE_LINUX_DEFAULT="quiet"\n' if name == "grub" else "")
            else:
                path.unlink(missing_ok=True)
        commands = self.commands - set(missing)
        if not both_managers:
            commands -= {"pacman"} if fedora else {"dnf"}
        launcher = self.repo / "scripts/imac-patcher"
        if symlink:
            link = self.root / "launcher"
            link.symlink_to(launcher)
            launcher = link
        if gum:
            self.stub("gum", '''
case "$1" in
    confirm) echo GUM_CONFIRM; exit 1 ;;
    style) exit 0 ;;
    choose) echo Quit ;;
esac''')
            commands.add("gum")
        cmd = [BWRAP, "--unshare-all", "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc",
               "--bind", str(self.root), str(self.root), "--tmpfs", "/usr/bin",
               "--ro-bind", str(self.available), str(self.available),
               "--ro-bind", str(self.sys), "/sys", "--ro-bind", str(self.os_release), "/etc/os-release",
               "--ro-bind", str(self.defaults), "/etc/default"]
        if Path("/usr/sbin").resolve() != Path("/usr/bin").resolve():
            cmd += ["--tmpfs", "/usr/sbin"]
        for command in sorted(commands):
            cmd += ["--symlink", str(self.available / command), "/usr/bin/" + command]
        cmd += ["--setenv", "STARTUP_TEST_TOOLS", str(self.available),
                "--setenv", "PATH", "/usr/bin:/usr/sbin", "--setenv", "HOME", str(self.root / "home"),
                "--setenv", "XDG_CURRENT_DESKTOP", desktop, "--setenv", "XDG_STATE_HOME", str(self.root / "state"),
                "--", "/usr/bin/bash", str(launcher), *args]
        if terminal:
            master, slave = pty.openpty()
            try:
                os.write(master, answer.encode())
                return subprocess.run(cmd, stdin=slave, stderr=slave, stdout=subprocess.PIPE,
                                      text=True, timeout=15)
            finally:
                os.close(slave)
                os.close(master)
        return subprocess.run(cmd, input=answer, text=True, capture_output=True, timeout=15)

    def test_plain_launch_reports_missing_module_tools_before_the_menu(self):
        result = self.launch(answer="n\n4\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Core dependencies: ready", result.stdout)
        for module, command in (("audio", "dkms"), ("eq", "pactl"), ("5k", "pahole"), ("suspend", "systemctl")):
            line = next(line for line in result.stdout.splitlines() if f"{module} missing dependencies:" in line)
            self.assertIn(command, line)
        self.assertIn("matching kernel development files", result.stdout)
        self.assertNotIn("PACKAGE_MANAGER", result.stdout)

    def test_required_tools_are_checked_before_status_apply_or_remove(self):
        for args in ((), ("--status",), ("--apply", "eq"), ("--remove", "eq")):
            with self.subTest(args=args):
                result = self.launch(*args, missing=("find",), answer="n\n")
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn("missing: find", result.stdout)
                self.assertIn("Install them now? [y/N]", result.stderr)
                self.assertNotIn("ids:", result.stdout)
                self.assertNotIn("PACKAGE_MANAGER", result.stdout)

    def test_all_bootstrap_tools_fail_with_an_actionable_message(self):
        for tool in ("readlink", "dirname", "cat", "uname"):
            with self.subTest(tool=tool):
                result = self.launch(missing=(tool,))
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn(f"Missing launcher tools: {tool}", result.stderr)
                self.assertIn("Install coreutils", result.stderr)
                self.assertNotIn("command not found", result.stderr)

    def test_pacman_and_dnf_install_then_recheck_before_continuing(self):
        for fedora in (False, True):
            with self.subTest(fedora=fedora):
                result = self.launch("--status", missing=("find", "mkdir", "head"), answer="y\n", fedora=fedora)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("Core dependencies installed and verified", result.stdout)
                manager = "dnf" if fedora else "pacman"
                self.assertRegex(result.stdout, rf"PACKAGE_MANAGER \S*/{manager} ")
                self.assertIn("ids:", result.stdout)

    def test_failed_and_ineffective_installs_never_reach_the_menu(self):
        for fedora in (False, True):
            for mode in ("fail", "empty"):
                with self.subTest(fedora=fedora, mode=mode):
                    self.package_manager("dnf" if fedora else "pacman", mode)
                    result = self.launch(missing=("find",), answer="y\n", fedora=fedora)
                    self.assertEqual(result.returncode, 1, result.stderr)
                    self.assertNotIn("ids:", result.stdout)
                    self.assertIn("installation failed" if mode == "fail" else "still missing after the install", result.stdout)

    def test_fedora_uses_dnf_even_when_pacman_is_installed(self):
        result = self.launch("--status", missing=("find",), answer="y\n", fedora=True, both_managers=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertRegex(result.stdout, r"PACKAGE_MANAGER \S*/dnf install -y findutils")
        self.assertNotRegex(result.stdout, r"PACKAGE_MANAGER \S*/pacman")

    def test_fedora_does_not_fall_back_to_pacman_when_dnf_is_missing(self):
        result = self.launch(missing=("find", "dnf"), answer="y\n", fedora=True, both_managers=True)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("install these as root", result.stdout)
        self.assertNotIn("PACKAGE_MANAGER", result.stdout)

    def test_eof_and_missing_sudo_or_package_manager_explain_why_startup_stops(self):
        for missing, expected in ((("find",), "cannot run without"),
                                  (("sudo",), "install these as root"),
                                  (("find", "pacman", "dnf"), "install these as root")):
            with self.subTest(missing=missing):
                result = self.launch(missing=missing)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn(expected, result.stdout)
                self.assertNotIn("PACKAGE_MANAGER", result.stdout)
                self.assertNotIn("ids:", result.stdout)

    def test_symlink_launcher_uses_the_same_dependency_gate(self):
        result = self.launch(missing=("find",), answer="n\n", symlink=True)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("missing: find", result.stdout)

    def test_gum_is_used_only_with_terminal_input_and_output(self):
        result = self.launch(missing=("find",), answer="n\n", gum=True)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("Install them now? [y/N]", result.stderr)
        self.assertNotIn("GUM_CONFIRM", result.stdout)
        result = self.launch(missing=("find",), gum=True, terminal=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn("GUM_CONFIRM", result.stdout)

    def test_fedora_kde_reports_missing_display_and_audio_tools(self):
        result = self.launch("--status", fedora=True, desktop="KDE")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("color missing dependencies: python3 kscreen-doctor", result.stdout)
        self.assertIn("grubby", result.stdout)
        self.assertIn("dracut", result.stdout)
        # No curl: the tuning is vendored, so applying eq needs no network.
        self.assertIn("eq missing dependencies: pactl pw-cli wpctl systemctl", result.stdout)
        self.assertNotIn("command not found", result.stderr)

    def test_arch_family_grub_uses_its_backend_and_dependencies(self):
        for distro in ("arch", "endeavouros", "cachyos"):
            with self.subTest(distro=distro):
                result = self.launch("--status", distro=distro, grub=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                line = next(line for line in result.stdout.splitlines() if "5k missing dependencies:" in line)
                self.assertIn("grub-mkconfig", line)
                self.assertIn("mkinitcpio", line)
                self.assertNotIn("limine", result.stdout)
                boot = next(line for line in result.stdout.splitlines() if "Boot config hygiene" in line)
                self.assertIn("n/a", boot)
                self.assertNotIn("command not found", result.stderr)

    def test_limine_takes_precedence_over_a_stale_grub_config(self):
        result = self.launch("--status", distro="cachyos", grub=True, limine=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("limine-mkinitcpio", result.stdout)
        self.assertNotIn("grub-mkconfig", result.stdout)

    def test_fedora_takes_precedence_over_arch_like_and_boot_configs(self):
        result = self.launch("--status", fedora=True, grub=True, limine=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("grubby", result.stdout)
        self.assertNotIn("grub-mkconfig", result.stdout)
        self.assertNotIn("limine-mkinitcpio", result.stdout)

    def test_help_and_version_do_not_offer_module_dependencies(self):
        for arg in ("--help", "--version"):
            with self.subTest(arg=arg):
                result = self.launch(arg, missing=("find", "sudo"))
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertNotIn("missing dependencies", result.stdout)
                self.assertNotIn("PACKAGE_MANAGER", result.stdout)


    def test_plain_launch_offers_the_reported_prerequisites_and_takes_no_for_an_answer(self):
        result = self.launch(answer="n\n4\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("module prerequisites:", result.stdout)
        self.assertIn("skipped", result.stdout)
        self.assertNotIn("PACKAGE_MANAGER", result.stdout)
        # Declining is not fatal: the menu still opens (select prints to stderr).
        self.assertIn("Apply all safe patches", result.stderr)

    def test_plain_launch_installs_the_reported_prerequisites_after_confirmation(self):
        result = self.launch(answer="y\n4\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        line = next(line for line in result.stdout.splitlines() if "PACKAGE_MANAGER" in line)
        # Package names, not command names, and the headers package the tool
        # scan cannot see because it carries no command of its own.
        for package in ("base-devel", "kmod", "dkms", "pahole", "libpulse", "linux-headers"):
            self.assertIn(package, line)
        for command in ("gcc ", "modinfo", "pactl"):
            self.assertNotIn(command, line)
        # A stub package manager delivers none of them, so the recheck says so
        # and the refreshed status is printed before the menu.
        self.assertIn("still missing after the install", result.stdout)
        self.assertEqual(result.stdout.count("ids:"), 2)

    def test_fedora_prerequisites_use_fedora_package_names(self):
        result = self.launch(answer="y\n4\n", fedora=True, desktop="KDE")
        self.assertEqual(result.returncode, 0, result.stderr)
        line = next(line for line in result.stdout.splitlines() if "PACKAGE_MANAGER" in line)
        for package in ("dwarves", "pulseaudio-utils", "pipewire-utils", "kscreen",
                        "rpm-build", "kernel-devel-7.2.2-startup-test"):
            self.assertIn(package, line)
        self.assertNotIn("base-devel", line)

    def test_status_reports_prerequisites_without_installing_them(self):
        result = self.launch("--status", answer="y\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("missing dependencies:", result.stdout)
        self.assertNotIn("module prerequisites:", result.stdout)
        self.assertNotIn("PACKAGE_MANAGER", result.stdout)

if __name__ == "__main__":
    unittest.main()
