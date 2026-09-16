"""Regression cases from the audit, using temporary files and fake boot tools."""
import hashlib
import importlib.util
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from test_patcher_menu import shell_function

ROOT = Path(__file__).resolve().parents[1]


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


hypr = load("hypr_color", "scripts/hypr-color.py")
limine = load("limine_config", "scripts/lib/limine-config.py")


class ColourRegressionTests(unittest.TestCase):
    def test_round_trip_preserves_external_rules_comments_and_other_edits(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "monitors.lua"
            state = Path(tmp) / "color.json"
            original = ('-- cm = "dp3"\n'
                        'hl.monitor({ output = "DP-2", cm = "icc", scale = 1 })\n'
                        'hl.monitor({ output = "eDP-1", cm = "edid", scale = 2 })\n')
            config.write_text(original)
            self.assertEqual(hypr.configure(config, state, '--status'), 'not-applied')
            hypr.configure(config, state, '--apply')
            self.assertEqual(hypr.configure(config, state, '--status'), 'applied')
            config.write_text(config.read_text().replace('scale = 2', 'scale = 1.5'))
            hypr.configure(config, state, '--remove')
            self.assertEqual(config.read_text(), original.replace('scale = 2', 'scale = 1.5'))
            self.assertFalse(state.exists())

    def test_fallback_rule_stays_intact_while_internal_override_is_added(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "monitors.lua"
            state = Path(tmp) / "color.json"
            original = 'hl.monitor({ output = "", cm = "auto", scale = 2 })\n'
            config.write_text(original)
            hypr.configure(config, state, '--apply')
            self.assertTrue(config.read_text().startswith(original))
            self.assertIn('output = "eDP-1", cm = "dp3"', config.read_text())
            hypr.configure(config, state, '--apply')
            self.assertEqual(config.read_text().count('output = "eDP-1"'), 1)
            hypr.configure(config, state, '--remove')
            self.assertEqual(config.read_text(), original)

    def test_remove_restores_absent_cm_property(self):
        with tempfile.TemporaryDirectory() as tmp:
            config, state = Path(tmp) / "monitors.lua", Path(tmp) / "color.json"
            config.write_text('hl.monitor({ output = "eDP-1", scale = 2 })\n')
            hypr.configure(config, state, '--apply')
            hypr.configure(config, state, '--remove')
            self.assertNotIn('cm =', config.read_text())


class AudioCardRegressionTests(unittest.TestCase):
    def test_external_and_ambiguous_cards_are_never_chosen_by_order(self):
        profile = 'output:analog-surround-40+input:analog-stereo'
        def card(name):
            return (f'Card #1\n\tName: {name}\n\tProfiles:\n'
                    f'\t\t{profile}: available: yes\n\tActive Profile: {profile}\n')
        internal = 'alsa_card.pci-0000_00_1f.3'
        for script, function in (('imac-patcher', 'eq_card'),
                                 ('imac-audio-jack-switch', 'speaker_card')):
            code = shell_function((ROOT / 'scripts' / script).read_text(), function)
            for cards, expected in (
                (card('alsa_card.usb-external') + card(internal), internal),
                (card('alsa_card.usb-external'), ''),
                (card(internal) + card('alsa_card.pci-0000_02_00.0'), ''),
            ):
                with self.subTest(function=function, expected=expected, cards=cards):
                    result = subprocess.run(['bash', '-c', f'''
set -uo pipefail
EQ_PROFILE_40={shlex.quote(profile)}
PROFILE_40=$EQ_PROFILE_40
pactl() {{ cat; }}
pa() {{ cat; }}
{code}
{function}
'''], input=cards, text=True, capture_output=True)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stdout.strip().split(' ', 1)[0], expected)


class LimineRegressionTests(unittest.TestCase):
    def test_remove_matches_whole_entry_and_keeps_neighbour_without_cmdline(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "limine.conf"
            original = ('timeout: 5\n/Test - a (remove after confirming)\nprotocol: efi\n'
                        '/Test - ab (remove after confirming)\nprotocol: efi\ncmdline: keep\n')
            config.write_text(original)
            limine.update(config, '/Test - a')
            self.assertIn('/Test - ab', config.read_text())
            self.assertIn('cmdline: keep', config.read_text())
            self.assertEqual(next(Path(tmp).glob('limine.conf.backup-*')).read_text(), original)

    def test_failed_atomic_replace_keeps_original_and_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            real, link = Path(tmp) / "real", Path(tmp) / "limine.conf"
            real.write_text('/Test - a\ncmdline: old\n')
            real.chmod(0o640)
            link.symlink_to(real)
            with patch.object(limine.os, 'replace', side_effect=OSError('disk failure')):
                with self.assertRaises(OSError):
                    limine.update(link, '/Test - a')
            self.assertEqual(real.read_text(), '/Test - a\ncmdline: old\n')
            self.assertTrue(link.is_symlink())
            limine.update(link, '/Test - a', '/Test - a\ncmdline: new')
            self.assertTrue(link.is_symlink())
            self.assertEqual(real.stat().st_mode & 0o777, 0o640)

    def test_promotion_rejects_changed_image_and_wrong_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            config, image = Path(tmp) / 'limine.conf', Path(tmp) / 'test.efi'
            image.write_bytes(b'known image')
            digest = hashlib.blake2b(image.read_bytes()).hexdigest()
            config.write_text(f'/Test - trial\npath: boot():/EFI/Linux/test.efi#{digest}\ncmdline: quiet\n')
            limine.main([str(config), 'verify', '/Test - trial', str(image)])
            image.write_bytes(b'replaced image')
            with self.assertRaisesRegex(ValueError, 'path/hash'):
                limine.main([str(config), 'verify', '/Test - trial', str(image)])

    def test_saved_entries_keep_their_own_cmdline_and_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            images = root / 'EFI/Linux'
            images.mkdir(parents=True)
            image = images / 'trial.efi'
            image.write_bytes(b'trial')
            digest = hashlib.blake2b(image.read_bytes()).hexdigest()
            saved, config = root / 'saved.conf', root / 'limine.conf'
            saved.write_text(f'/Test - other\npath: boot():/EFI/Linux/trial.efi#{digest}\ncmdline: root=saved custom=1\n')
            config.write_text('/Default\ncmdline: root=current\n')
            limine.main([str(config), 'restore-tests', str(saved), tmp, '/Test - promoted'])
            self.assertIn('cmdline: root=saved custom=1', config.read_text())
            image.write_bytes(b'unknown replacement')
            with self.assertRaises(ValueError):
                limine.main([str(config), 'restore-tests', str(saved), tmp, '/Test - promoted'])

    def test_two_failed_decompressors_cannot_match(self):
        result = subprocess.run(['bash', '-c', f'''
set -uo pipefail
source {shlex.quote(str(ROOT / 'scripts/lib/grub.sh'))}
zstd() {{ return 1; }}
module_matches bad-a bad-b
'''], text=True, capture_output=True)
        self.assertNotEqual(result.returncode, 0)

    def test_stale_successful_rebuild_is_rejected(self):
        source = (ROOT / 'scripts/imac-test-entry').read_text()
        function = shell_function(source, 'rebuild_default_uki')
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(['bash', '-c', f'''
set -uo pipefail
source {shlex.quote(str(ROOT / 'scripts/lib/grub.sh'))}
{function}
ESP={shlex.quote(tmp)}
UKI="$ESP/image"
MODULE="$ESP/module"
printf old > "$UKI"
printf new > "$MODULE"
say() {{ :; }}
warn() {{ echo "$*" >&2; }}
limine-mkinitcpio() {{ return 0; }}
extract_module() {{ cp "$1" "$2"; }}
zstd() {{ cat "$2"; }}
sync_conf() {{ echo UNEXPECTED_SYNC; }}
rebuild_default_uki
'''], text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('does not contain', result.stderr)
            self.assertNotIn('UNEXPECTED_SYNC', result.stdout)


class UpgradeRegressionTests(unittest.TestCase):
    def test_failed_installer_copy_never_runs_and_cleans_temp_file(self):
        source = (ROOT / 'scripts/imac-patcher').read_text()
        start = source.index('# ── version and upgrade')
        version_code = source[start:source.index('\ncase "$ACTION" in', start)]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'VERSION').write_text('1.0\n')
            (root / 'install.sh').write_text('echo SHOULD_NOT_RUN\n')
            scratch = root / 'tmp'
            scratch.mkdir()
            result = subprocess.run(['bash', '-c', f'''
set -uo pipefail
REPO_DIR={shlex.quote(tmp)}
say() {{ :; }}
warn() {{ echo "$*" >&2; }}
{version_code}
imac_latest_release() {{ echo v2.0; }}
cat() {{ [[ $1 != "$REPO_DIR/install.sh" ]] || return 1; command cat "$@"; }}
imac_upgrade
'''], text=True, capture_output=True, env={**os.environ, 'TMPDIR': str(scratch)})
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn('SHOULD_NOT_RUN', result.stdout)
            self.assertIn('could not copy', result.stderr)
            self.assertEqual(list(scratch.iterdir()), [])
