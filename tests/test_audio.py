"""Pinned source, DKMS upgrades and failures, without building a host module."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "scripts/imac-patcher").read_text()
START = SOURCE.index("# ═══════════════════════ module: audio ")
AUDIO = SOURCE[START:SOURCE.index("# ═══════════════════════ module: eq ", START)]
KERNEL = "7.2.3-arch1-3"
VERSION = "0.2.imac5k1"


class AudioTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.cache = self.root / "cache"
        self.cache.mkdir()
        self.repo = self.cache / "imac18-3-cs8409-linux-audio"
        self.repo.mkdir()
        self.env = {**os.environ, "PATH": f"{self.bin}:/usr/bin:/bin",
                    "AUDIO_TEST_ROOT": str(self.root), "GIT_CONFIG_NOSYSTEM": "1",
                    "GIT_CONFIG_GLOBAL": "/dev/null"}
        (self.repo / "driver.c").write_text("before\n")
        (self.repo / "dkms.conf").write_text('PACKAGE_NAME="snd_hda_macbookpro"\nPACKAGE_VERSION="0.2"\n')
        self.git("init", "-q")
        self.git("add", "driver.c", "dkms.conf")
        self.git("-c", "user.name=test", "-c", "user.email=test@invalid", "commit", "-qm", "baseline")
        self.pin = self.git("rev-parse", "HEAD").stdout.strip()
        (self.repo / "driver.c").write_text("local edits\n")
        (self.repo / "notes").write_text("keep me\n")
        self.patch = self.root / "headset.patch"
        self.patch.write_text("--- a/driver.c\n+++ b/driver.c\n@@ -1 +1 @@\n-before\n+after\n")
        self.headers(KERNEL)
        self.stub("sudo", 'exec "$@"')
        self.stub("mkinitcpio", 'echo "INITRAMFS $*" >> "$AUDIO_TEST_ROOT/commands"')
        self.stub("limine-mkinitcpio", 'echo "INITRAMFS $*" >> "$AUDIO_TEST_ROOT/commands"')
        self.stub("dracut", 'echo "DRACUT $*" >> "$AUDIO_TEST_ROOT/commands"')
        self.stub("mokutil", '[[ $1 == --sb-state ]] && echo "SecureBoot disabled"; exit 0')
        self.stub("dkms", '''
printf 'DKMS %s\n' "$*" >> "$AUDIO_TEST_ROOT/commands"
verb=$1; shift
version= kernel=
args=("$@")
while (($#)); do
    case $1 in
        -v) version=$2; shift ;;
        -k) kernel=$2; shift ;;
    esac
    shift
done
[[ ${AUDIO_TEST_FAIL:-} != "$verb" ]] || exit 9
case $verb in
    status)
        if [[ -z $version ]]; then
            echo 'snd_hda_macbookpro/0.2, 7.2.3-arch1-3, x86_64: installed'
        elif [[ -f $AUDIO_TEST_ROOT/registered ]]; then
            if [[ -n $kernel && -f $AUDIO_TEST_ROOT/$kernel.installed ]]; then
                echo "snd_hda_macbookpro/$version, $kernel, x86_64: installed"
            else echo "snd_hda_macbookpro/$version: added"; fi
        fi ;;
    add)
        [[ $(cat "${args[0]}/driver.c") == after ]] || exit 2
        grep -q 'PACKAGE_VERSION="0.2.imac5k1"' "${args[0]}/dkms.conf" || exit 2
        touch "$AUDIO_TEST_ROOT/registered" ;;
    build) touch "$AUDIO_TEST_ROOT/$kernel.built" ;;
    install)
        [[ -f $AUDIO_TEST_ROOT/$kernel.built ]] || exit 3
        touch "$AUDIO_TEST_ROOT/$kernel.installed" ;;
    remove) : ;;
    *) exit 4 ;;
esac
''')
        self.stub("modinfo", '''
kernel= field= module=
while (($#)); do
    case $1 in
        -k) kernel=$2; shift ;;
        -F) field=$2; shift ;;
        -n) field=filename ;;
        *) module=$1 ;;
    esac
    shift
done
case $field in
    filename) echo "$AUDIO_TEST_ROOT/modules/$kernel/updates/dkms/snd-hda-codec-cs8409.ko" ;;
    parm)
        kernel=${module#"$AUDIO_TEST_ROOT/modules/"}; kernel=${kernel%%/*}
        [[ -f $AUDIO_TEST_ROOT/$kernel.installed && ${AUDIO_TEST_BAD_MODULE:-0} != 1 ]] &&
            echo 'headset_buttons:headset remote buttons: 1 = on (default), 0 = off (int)'
        exit 0 ;;
    *) exit 1 ;;
esac
''')

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.repo), *args], env=self.env,
                              text=True, capture_output=True, check=True)

    def headers(self, kernel):
        build = self.root / "modules" / kernel / "build"
        build.mkdir(parents=True)
        (build / "Module.symvers").touch()

    def stub(self, name, body):
        path = self.bin / name
        path.write_text("#!/usr/bin/env bash\nset -uo pipefail\n" + body + "\n")
        path.chmod(0o755)

    def run_audio(self, command, **env):
        harness = '''
set -uo pipefail
REPO_DIR=$1
CACHE=$AUDIO_TEST_ROOT/cache
KREL=7.2.3-arch1-3
say() { echo "$*"; }
warn() { echo "$*"; }
imac_audio_supported() { return 0; }
''' + AUDIO + '''
AUDIO_PIN=$2
AUDIO_PATCH=$AUDIO_TEST_ROOT/headset.patch
AUDIO_MODULES_DIR=$AUDIO_TEST_ROOT/modules
AUDIO_DKMS_TREE=$AUDIO_TEST_ROOT/dkms
audio_check_hardware() { return 0; }
audio_arch_deps() { return 0; }
audio_live_is_patched() { [[ -f $AUDIO_TEST_ROOT/live ]]; }
''' + command
        return subprocess.run(["bash", "-c", harness, "test", str(ROOT), self.pin],
                              env={**self.env, **env}, text=True, capture_output=True, timeout=15)

    def commands(self):
        path = self.root / "commands"
        return path.read_text() if path.exists() else ""

    def assert_ok(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_upgrade_builds_patched_source_before_replacing_the_old_driver(self):
        result = self.run_audio("mod_audio_apply")
        self.assert_ok(result)
        log = self.commands()
        self.assertLess(log.index("DKMS build"), log.index("DKMS install"))
        self.assertLess(log.index("DKMS install"), log.index("INITRAMFS"))
        self.assertIn(f"-v {VERSION} -k {KERNEL} --force", log)
        self.assertNotIn("DKMS remove", log)
        self.assertEqual((self.repo / "driver.c").read_text(), "local edits\n")
        self.assertEqual((self.repo / "notes").read_text(), "keep me\n")
        self.assertEqual(list(self.cache.glob("audio-build.*")), [])

    def test_an_old_installed_driver_is_partial_so_apply_will_upgrade_it(self):
        result = self.run_audio("mod_audio_detect")
        self.assert_ok(result)
        self.assertEqual(result.stdout.strip(), "partial")

    def test_a_new_module_on_disk_still_requires_a_reboot(self):
        self.assert_ok(self.run_audio("audio_install_driver"))
        self.assertEqual(self.run_audio("mod_audio_detect").stdout.strip(), "partial")
        (self.root / "live").touch()
        self.assertEqual(self.run_audio("mod_audio_detect").stdout.strip(), "applied")

    def test_a_stock_module_is_not_an_applied_patch(self):
        result = self.run_audio('''
dkms() { return 0; }
modinfo() { echo /usr/lib/modules/7.2.3/kernel/sound/cs8409.ko; }
mod_audio_detect
''')
        self.assertEqual(result.stdout.strip(), "not-applied")

    def test_pending_kernels_are_built_even_when_the_running_headers_are_gone(self):
        (self.root / "modules" / KERNEL / "build/Module.symvers").unlink()
        self.headers("7.2.4-arch1-1")
        self.headers("6.16.9-old")
        self.assert_ok(self.run_audio("audio_install_driver"))
        self.assertIn("-k 7.2.4-arch1-1", self.commands())
        self.assertNotIn(f"-k {KERNEL}", self.commands())
        self.assertNotIn("-k 6.16", self.commands())

    def test_a_missing_pending_build_is_partial(self):
        self.assert_ok(self.run_audio("audio_install_driver"))
        (self.root / "live").touch()
        self.headers("7.2.4-arch1-1")
        self.assertEqual(self.run_audio("mod_audio_detect").stdout.strip(), "partial")

    def test_an_already_installed_patched_build_is_not_recompiled_before_reboot(self):
        self.assert_ok(self.run_audio("audio_install_driver"))
        (self.root / "commands").write_text("")
        self.assert_ok(self.run_audio("audio_install_driver"))
        self.assertNotIn("DKMS build", self.commands())
        self.assertNotIn("DKMS install", self.commands())

    def test_failures_never_rebuild_initramfs_or_report_success(self):
        for verb in ("add", "build", "install"):
            with self.subTest(verb=verb):
                (self.root / "commands").write_text("")
                result = self.run_audio("mod_audio_apply", AUDIO_TEST_FAIL=verb)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn("INITRAMFS", self.commands())
                self.assertNotIn("installed — reboot", result.stdout)
                if verb == "build":
                    self.assertNotIn("DKMS install", self.commands())

    def test_dkms_success_with_the_wrong_resolved_module_is_a_failure(self):
        result = self.run_audio("mod_audio_apply", AUDIO_TEST_BAD_MODULE="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("was not installed", result.stdout)
        self.assertNotIn("INITRAMFS", self.commands())

    def test_a_patch_failure_leaves_the_installed_driver_alone(self):
        self.patch.write_text("--- a/driver.c\n+++ b/driver.c\n@@ -1 +1 @@\n-wrong baseline\n+after\n")
        result = self.run_audio("mod_audio_apply")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("DKMS add", self.commands())
        self.assertNotIn("DKMS remove", self.commands())
        self.assertNotIn("DKMS install", self.commands())
        self.assertEqual(list(self.cache.glob("audio-build.*")), [])

    def test_a_missing_pin_fails_without_using_the_checkout_head(self):
        result = self.run_audio('AUDIO_PIN=0123456789012345678901234567890123456789\naudio_install_driver')
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("DKMS add", self.commands())

    def test_no_matching_headers_changes_nothing(self):
        (self.root / "modules" / KERNEL / "build/Module.symvers").unlink()
        result = self.run_audio("audio_install_driver")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("matching headers", result.stdout)
        self.assertEqual(self.commands(), "")

    def test_conflicting_driver_is_reported_without_deleting_its_source(self):
        source = self.root / "dkms/rival/1.0/source/dkms.conf"
        source.parent.mkdir(parents=True)
        source.write_text('BUILT_MODULE_NAME[0]="snd-hda-codec-cs8409"\n')
        result = self.run_audio('''
dkms() { echo 'rival/1.0: added'; }
audio_install_driver
''')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Conflicting CS8409", result.stdout)
        self.assertTrue(source.exists())

    def test_remove_handles_legacy_and_added_versions_once_each(self):
        result = self.run_audio('''
dkms() {
    if [[ $1 == status ]]; then
        printf '%s\n' 'snd_hda_macbookpro/0.2, kernel1, x86_64: installed' \
            'snd_hda_macbookpro/0.2, kernel2, x86_64: installed' \
            'snd_hda_macbookpro/0.2.imac5k1: added'
    else command dkms "$@"; fi
}
mod_audio_remove
''')
        self.assert_ok(result)
        self.assertEqual(self.commands().count("DKMS remove snd_hda_macbookpro/0.2 --all"), 1)
        self.assertIn(f"DKMS remove snd_hda_macbookpro/{VERSION} --all", self.commands())
        self.assertIn("INITRAMFS", self.commands())

    def test_remove_failure_does_not_claim_stock_audio_is_restored(self):
        result = self.run_audio("mod_audio_remove", AUDIO_TEST_FAIL="remove")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("stock module restored", result.stdout)
        self.assertNotIn("INITRAMFS", self.commands())

    def test_fedora_uses_the_same_patched_source_and_refreshes_dracut(self):
        result = self.run_audio(f'''
source '{ROOT}/scripts/lib/fedora.sh'
fedora_mutable() {{ return 0; }}
fedora_deps() {{ return 0; }}
mod_audio_apply
''')
        self.assert_ok(result)
        self.assertIn(f"-v {VERSION} -k {KERNEL}", self.commands())
        self.assertIn(f"DRACUT --force /boot/initramfs-{KERNEL}.img {KERNEL}", self.commands())

    def test_fedora_stops_before_initramfs_when_the_signing_key_is_not_enrolled(self):
        self.stub("mokutil", '[[ $1 == --sb-state ]] && { echo "SecureBoot enabled"; exit 0; }; exit 1')
        result = self.run_audio(f'''
source '{ROOT}/scripts/lib/fedora.sh'
fedora_mutable() {{ return 0; }}
fedora_deps() {{ return 0; }}
mod_audio_apply
''')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Enroll the DKMS key", result.stdout)
        self.assertNotIn("DRACUT", self.commands())


if __name__ == "__main__":
    unittest.main()
