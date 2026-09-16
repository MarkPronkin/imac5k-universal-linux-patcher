"""Build a release and install it from a local server, touching nothing real.

`curl | bash` is unforgiving -- there is no half-installed state a user can be
talked through -- so the whole path is exercised here: tarball, checksum,
launcher symlink, rollback pruning and uninstall, all inside a temp HOME.
"""
from functools import partialmethod
import fcntl
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import os
import subprocess
import tarfile
import tempfile
import threading
import unittest


REPO = Path(__file__).resolve().parents[1]
INSTALL = REPO / "install.sh"
MAKE_RELEASE = REPO / "scripts/make-release.sh"
VERSION = "9.9.9-test"

# Creating a tag or a stash writes a git object, which needs an identity the
# machine may not have -- a CI runner has none. Supply one rather than depend
# on the ambient config.
GIT_ENV = {**os.environ, "GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "test@invalid",
           "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "test@invalid"}


# Snapshot runtime files with a temporary index, including new files, without
# staging anything in the user's index or moving their working-tree changes.
def worktree_ref():
    with tempfile.TemporaryDirectory() as tmp:
        env = {**GIT_ENV, "GIT_INDEX_FILE": str(Path(tmp) / "index")}
        def git(*args):
            return subprocess.run(["git", *args], cwd=REPO, check=True,
                                  text=True, capture_output=True, env=env).stdout.strip()
        git("read-tree", "HEAD")
        git("add", "-A", "--", "install.sh", "scripts", "modules", "patches", "configs",
            "assets", "docs", "README.md", "DEPENDENCIES.md", "LICENSE")
        return git("commit-tree", git("write-tree"), "-p", "HEAD", "-m", "Offline release fixture")


REF = None


def build_release(dist, ref=None, version=VERSION):
    global REF
    if REF is None:
        REF = worktree_ref()
    subprocess.run([MAKE_RELEASE, version, ref or REF],
                   cwd=REPO, check=True, capture_output=True)
    built = REPO / "dist"
    dist.mkdir(parents=True, exist_ok=True)
    (dist / f"imac5k-patcher-{version}.tar.gz").write_bytes(
        (built / f"imac5k-patcher-{version}.tar.gz").read_bytes())
    # One SHA256SUMS covers every release the fake server offers.
    (dist / "SHA256SUMS").write_bytes((built / "SHA256SUMS").read_bytes())


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(subprocess.run, ["rm", "-rf", str(self.tmp)])
        self.dist = self.tmp / "dist"
        build_release(self.dist)

        handler = type("Quiet", (SimpleHTTPRequestHandler,), {
            "log_message": lambda *a, **k: None,
            "__init__": partialmethod(SimpleHTTPRequestHandler.__init__,
                                      directory=str(self.dist)),
        })
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

        self.home = self.tmp / "home"
        self.share = self.home / ".local/share"
        self.bin = self.home / ".local/bin"

    def env(self):
        url = "http://127.0.0.1:%d" % self.server.server_address[1]
        return {
            "PATH": f"{self.bin}:/usr/bin:/bin", "HOME": str(self.home),
            "XDG_DATA_HOME": str(self.share),
            "IMAC5K_BASE_URL": url, "IMAC5K_API_URL": f"{url}/releases",
        }

    def install(self, *args):
        return subprocess.run(["bash", str(INSTALL), "--version", VERSION, *args],
                              env=self.env(), text=True, capture_output=True, timeout=120)

    def publish(self, version):
        """Offer `version` from the fake server, as the newest release."""
        build_release(self.dist, version=version)
        (self.dist / "releases").write_text('[{"tag_name": "v%s"}]' % version)

    def upgrade(self):
        return subprocess.run([str(self.bin / "imac-patcher"), "upgrade"],
                              env=self.env(), text=True, capture_output=True, timeout=120)

    def test_tarball_holds_the_runtime_tree_and_no_dev_state(self):
        with tarfile.open(self.dist / f"imac5k-patcher-{VERSION}.tar.gz") as tar:
            names = {n.split("/", 1)[1] for n in tar.getnames() if "/" in n}
        for needed in ("VERSION", "COMMIT", "install.sh", "LICENSE", "README.md", "DEPENDENCIES.md",
                       "scripts/hypr-color.py", "scripts/t2-speakers.py", "scripts/lib/limine-config.py",
                       "scripts/imac-patcher", "scripts/lib/platform.sh",
                       "scripts/lib/grub.sh", "scripts/lib/arch-grub.sh", "docs/arch-grub.md",
                       "patches/cs8409-headset-capture.patch", "docs/headphones.md",
                       "scripts/imac-audio-jack-switch",
                       # The suspend module installs its sleep hooks and s2idle
                       # drop-in from here.
                       "scripts/imac-tb-sleep-hook", "scripts/imac-wifi-sleep-hook",
                       "configs/imac5k-s2idle.conf",
                       # ...and on the iMac18,3 builds the USB controller fix
                       # through DKMS and loads it at boot.
                       "modules/imac5k-xhci-d0/imac5k_xhci_d0.c",
                       "modules/imac5k-xhci-d0/Makefile", "modules/imac5k-xhci-d0/dkms.conf",
                       "configs/imac5k-xhci-d0.conf",
                       "patches/imacpro-slave-dp-panel-mode.patch",
                       "patches/dce120-enable-crtc-reset.patch",
                       "patches/dce12-multisync-master-first.patch",
                       "patches/dce110-genlock-master-from-pipe0.patch",
                       "patches/5k-resync-postpone-on-modeset.patch",
                       # The speaker tuning is vendored, not downloaded: an
                       # archive without it installs a graph that cannot load.
                       "assets/imac-audio/iMacAudio.conf",
                       "assets/imac-audio/Filters L Aug 14-MP.wav",
                       # MIT requires its notice to travel with the copies.
                       "assets/imac-audio/LICENSE",
                       "configs/monitors.lua", "patches/imac5k-lean-core-7.2.x.patch"):
            self.assertIn(needed, names)
        for excluded in ("TODO.md", "notes", "tests"):
            self.assertNotIn(excluded, {n.split("/")[0] for n in names})

    def test_rebuilding_the_same_commit_is_byte_identical(self):
        first = (self.dist / f"imac5k-patcher-{VERSION}.tar.gz").read_bytes()
        second = self.tmp / "again"
        build_release(second)
        self.assertEqual(first, (second / f"imac5k-patcher-{VERSION}.tar.gz").read_bytes())

    def test_building_from_an_annotated_tag_matches_building_from_its_commit(self):
        # An annotated tag is its own git object, so a bare rev-parse hands back
        # the tag rather than the commit it points at -- and the tarball then
        # gets a mangled timestamp and a checksum nobody else can reproduce.
        tag = "_test-make-release"
        # Tag the same worktree ref the other release tests build from, not
        # HEAD: a runtime file added but not yet committed is in the worktree
        # ref and absent from HEAD, and archiving a path that does not exist
        # in the commit is a hard git error.
        base = subprocess.run(["git", "rev-parse", REF], cwd=REPO, check=True,
                              text=True, capture_output=True).stdout.strip()
        subprocess.run(["git", "tag", "-a", tag, "-m", "temp", base], cwd=REPO,
                       check=True, env=GIT_ENV)
        self.addCleanup(subprocess.run, ["git", "tag", "-d", tag],
                        cwd=REPO, capture_output=True)
        from_tag, from_commit = self.tmp / "tag", self.tmp / "commit"
        build_release(from_tag, tag)
        build_release(from_commit, base)
        name = f"imac5k-patcher-{VERSION}.tar.gz"
        self.assertEqual((from_tag / name).read_bytes(), (from_commit / name).read_bytes())

    def test_install_links_a_launcher_that_finds_its_own_files(self):
        result = self.install()
        self.assertEqual(result.returncode, 0, result.stderr)
        launcher = self.bin / "imac-patcher"
        self.assertTrue(launcher.is_symlink())
        # Reached through the symlink, the patcher must still resolve the libs,
        # patches and configs that sit beside its real path.
        version = subprocess.run([str(launcher), "--version"], text=True,
                                 capture_output=True, timeout=30)
        self.assertEqual(version.stdout.strip(), VERSION, version.stderr)

    def test_upgrade_installs_a_newer_release_over_the_running_one(self):
        self.install()
        newer = "9.9.10-test"
        self.publish(newer)
        result = self.upgrade()
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn(f"{VERSION} \u2192 {newer}", result.stdout)
        # The launcher must now reach the new version -- the installer replaced
        # the very tree the upgrading script was reading itself from.
        version = subprocess.run([str(self.bin / "imac-patcher"), "--version"],
                                 env=self.env(), text=True, capture_output=True, timeout=30)
        self.assertEqual(version.stdout.strip(), newer, version.stderr)

    def test_upgrade_on_the_newest_release_changes_nothing(self):
        self.install()
        self.publish(VERSION)
        before = (self.share / f"imac5k-patcher/versions/{VERSION}").stat().st_mtime
        result = self.upgrade()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("already on the newest release", result.stdout)
        self.assertEqual((self.share / f"imac5k-patcher/versions/{VERSION}").stat().st_mtime, before)

    def test_upgrade_refuses_to_touch_a_git_checkout(self):
        result = subprocess.run([str(REPO / "scripts/imac-patcher"), "upgrade"],
                                env=self.env(), text=True, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 1)
        self.assertIn("git checkout", result.stderr)
        self.assertIn("git -C", result.stdout)

    def test_a_tampered_tarball_is_refused(self):
        sums = self.dist / "SHA256SUMS"
        sums.write_text("\n".join(
            "0" * 64 + line[64:] if line.endswith(f"imac5k-patcher-{VERSION}.tar.gz") else line
            for line in sums.read_text().splitlines()) + "\n")
        result = self.install()
        self.assertEqual(result.returncode, 1)
        self.assertIn("checksum mismatch", result.stderr)
        self.assertFalse((self.bin / "imac-patcher").exists())

    def test_uninstall_removes_everything_it_installed(self):
        self.install()
        self.assertEqual(self.install("--uninstall").returncode, 0)
        self.assertFalse((self.bin / "imac-patcher").exists())
        self.assertFalse((self.share / "imac5k-patcher").exists())

    def test_invalid_versions_never_create_an_installation(self):
        for version in ("../escape", "1/../../escape", "-option", "1?asset", "1#fragment", "1\n2"):
            with self.subTest(version=version):
                result = self.install("--version", version)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("invalid release version", result.stderr)
                self.assertFalse((self.share / "imac5k-patcher/current").exists())

    def test_same_version_reinstall_keeps_the_existing_tree(self):
        self.assertEqual(self.install().returncode, 0)
        current = self.share / "imac5k-patcher/current"
        inode = current.resolve().stat().st_ino
        self.assertEqual(self.install().returncode, 0)
        self.assertEqual(current.resolve().stat().st_ino, inode)

    def test_concurrent_install_is_refused_before_replacement(self):
        self.assertEqual(self.install().returncode, 0)
        lock = self.share / "imac5k-patcher.install.lock"
        with lock.open("w") as held:
            fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = self.install()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("another installer", result.stderr)
        self.assertTrue((self.bin / "imac-patcher").exists())

    def test_different_same_version_payload_does_not_remove_current(self):
        self.assertEqual(self.install().returncode, 0)
        current = self.share / "imac5k-patcher/current"
        (current / "user-file").write_text("keep")
        result = self.install()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((current / "user-file").read_text(), "keep")
        self.assertTrue((current / "scripts/imac-patcher").exists())

    def test_custom_launcher_is_removed_using_recorded_path(self):
        custom = self.home / "custom bin"
        self.assertEqual(self.install("--bin-dir", str(custom)).returncode, 0)
        self.assertTrue((custom / "imac-patcher").is_symlink())
        self.assertEqual(self.install("--uninstall").returncode, 0)
        self.assertFalse((custom / "imac-patcher").is_symlink())

    def test_uninstall_preserves_a_replacement_launcher(self):
        self.assertEqual(self.install().returncode, 0)
        launcher = self.bin / "imac-patcher"
        launcher.unlink()
        launcher.write_text("user replacement")
        self.assertEqual(self.install("--uninstall").returncode, 0)
        self.assertEqual(launcher.read_text(), "user replacement")

    def test_pruning_never_enters_version_symlinks(self):
        self.assertEqual(self.install().returncode, 0)
        outside = self.tmp / "outside"
        outside.mkdir()
        (outside / "keep").write_text("keep")
        (self.share / "imac5k-patcher/versions/0.0.1").symlink_to(outside, target_is_directory=True)
        self.assertEqual(self.install().returncode, 0)
        self.assertEqual((outside / "keep").read_text(), "keep")

    def test_missing_and_inexact_checksum_entries_are_refused(self):
        sums = self.dist / "SHA256SUMS"
        for content in ("", "0" * 64 + f"  imac5k-patcher-{VERSION}.tar.gz.extra\n"):
            sums.write_text(content)
            result = self.install()
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("exactly one entry", result.stderr)
            self.assertFalse((self.bin / "imac-patcher").exists())

    def test_explicit_no_verify_warns(self):
        (self.dist / "SHA256SUMS").unlink()
        result = self.install("--no-verify")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("verification disabled", result.stderr)

    def test_latest_lookup_without_version(self):
        self.publish(VERSION)
        result = subprocess.run(["bash", str(INSTALL)], env=self.env(), text=True,
                                capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_manifest_preserves_old_releases_after_new_build(self):
        self.publish("9.9.10-test")
        result = self.install()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_old_versions_are_pruned_but_the_current_one_survives(self):
        self.install()
        versions = self.share / "imac5k-patcher/versions"
        for old in ("0.0.1", "0.0.2", "0.0.3", "0.0.4"):
            (versions / old).mkdir()
            subprocess.run(["touch", "-d", "2020-01-01", str(versions / old)], check=True)
        self.install()
        kept = {d.name for d in versions.iterdir()}
        self.assertIn(VERSION, kept)
        self.assertEqual(len(kept), 3)
        self.assertTrue((self.share / "imac5k-patcher/current/scripts/imac-patcher").exists())


if __name__ == "__main__":
    unittest.main()
