"""Ubuntu 26.04 ABI, source packaging, signing and shared APT transactions."""
import unittest
from test_debian import AptBackendMixin


class UbuntuBackendTests(AptBackendMixin, unittest.TestCase):
    distro = "ubuntu"
    krel = "7.0.0-38-generic"
    series = "7.0"
    version = "7.0.0-38.38"
    port = "imac5k-ubuntu-7.0.patch"
    dkms_cert = "/var/lib/shim-signed/mok/MOK.der"

    def test_source_binary_uses_ubuntu_full_base_version(self):
        result = self.run_backend("imac_apt_source_binary")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "linux-source-7.0.0\n")

    def test_hwe_source_version_is_taken_from_headers(self):
        result = self.run_backend("source_version", HEADER_METADATA="installed linux-hwe-7.0 7.0.0-38.38~26.04.1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "7.0.0-38.38~26.04.1\n")

    def test_oem_cloud_and_third_party_headers_are_rejected(self):
        for release, source in (("7.0.0-38-lowlatency", "linux-lowlatency"),
                                ("7.0.0-38-oem", "linux-oem-7.0"),
                                ("7.0.0-38-aws", "linux-aws"),
                                (self.krel, "linux-signed"),
                                (self.krel, "linux-custom"),
                                ("7.0.0-070000-generic", "linux-upstream")):
            with self.subTest(release=release, source=source):
                result = self.run_backend(f"KREL={release}; source_version", HEADER_METADATA=f"installed {source} {self.version}")
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((self.root / "state").exists())

    def test_stock_older_lts_kernel_is_refused(self):
        result = self.run_backend("KREL=6.8.0-100-generic; KSERIES=6.8; check")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("needs a patch port", result.stderr)

    def test_custom_dkms_certificate_is_used(self):
        result = self.module("xhci_fix_signing_ok", SECURE_BOOT="1", IMAC5K_DKMS_CERT="/tmp/custom.der")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("/tmp/custom.der", result.stderr)
        self.assertNotIn(self.dkms_cert, result.stderr)

    def test_stock_ubuntu_audio_uses_dkms_and_refreshes_initramfs(self):
        result = self.module(r'''
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
        self.assertIn("linux-headers-" + self.krel, result.stdout)
        self.assertIn("zstd", result.stdout)
        self.assertIn("DKMS_INSTALLED\nINITRAMFS -u -k all", result.stdout)
        self.assertIn("Audio installed for " + self.krel, result.stdout)

    def test_audio_installs_exact_source_and_rechecks_it(self):
        code = r'''
apt_deps() { :; }
present=0
dpkg-query() {
    if [[ ${*: -1} == linux-source-* ]]; then
        ((present)) && printf 'installed linux 7.0.0-38.38'
    else printf 'installed linux 7.0.0-38.38'; fi
}
confirm() { return 0; }
apt-get() { printf 'APT %s\n' "$*"; present=1; }
ubuntu_audio_source_deps
'''
        result = self.module(code)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("APT install -y linux-source-7.0.0=7.0.0-38.38", result.stdout)
        result = self.module(code.replace("present=1;", ":;"))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("sources do not match", result.stderr)

    def test_dkms_prebuild_rejects_sources_from_another_abi(self):
        upstream = self.root / "install.cirrus.driver.sh"
        upstream.write_text('#!/bin/sh\nprintf "PREBUILD %s\\n" "$*"\n')
        upstream.chmod(0o755)
        command = 'cd "$TEST_ROOT"; "$REPO/scripts/lib/ubuntu-audio-pre-build.sh" "$KREL"'
        result = self.run_backend(command)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "PREBUILD -k " + self.krel + " --dkms\n")
        result = self.run_backend(command, SOURCE_METADATA="installed linux 7.0.0-39.39")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("PREBUILD", result.stdout)
        self.assertIn("linux-source-7.0.0=7.0.0-38.38", result.stderr)

    def test_prepared_dkms_tree_keeps_the_ubuntu_source_guard(self):
        (self.root / "dkms.conf").write_text('PRE_BUILD="install.cirrus.driver.sh -k $kernelver --dkms"\n')
        result = self.module('audio_platform_prepare_source "$TEST_ROOT"')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('PRE_BUILD="imac5k-ubuntu-pre-build $kernelver"', (self.root / "dkms.conf").read_text())
        self.assertTrue((self.root / "imac5k-ubuntu-pre-build").stat().st_mode & 0o111)
        result = self.module('printf "%s\\n" "$AUDIO_DKMS_VERSION"')
        self.assertEqual(result.stdout, "0.2.imac5k1.ubuntu1\n")


if __name__ == "__main__":
    unittest.main()
