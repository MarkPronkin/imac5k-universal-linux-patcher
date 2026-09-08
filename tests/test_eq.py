"""Offline tests for the speaker tuning module: no audio server, no network."""
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
PATCHER = ROOT / "scripts/imac-patcher"

# Two cards as pactl prints them: the HDMI one first, so picking the card by
# "offers a 4.0 profile" is doing real work rather than taking the first.
FOUR_CHANNEL = "output:analog-surround-40+input:analog-stereo"
STEREO = "output:analog-stereo+input:analog-stereo"
PACTL_CARDS = """Card #51
\tName: alsa_card.pci-0000_01_00.1
\tDriver: alsa
\tProfiles:
\t\toutput:hdmi-stereo: Digital Stereo (HDMI) Output (sinks: 1, sources: 0, priority: 5900, available: no)
\t\toutput:hdmi-surround71: Digital Surround 7.1 (HDMI) Output (sinks: 1, sources: 0, priority: 800, available: no)
\tActive Profile: off

Card #52
\tName: alsa_card.pci-0000_00_1f.3
\tDriver: alsa
\tProfiles:
\t\toutput:analog-stereo+input:analog-stereo: Analog Stereo Duplex (sinks: 1, sources: 1, priority: 6565, available: yes)
{profiles}\tActive Profile: {active}
"""
FOUR_CHANNEL_PROFILE_LINE = (
    "\t\toutput:analog-surround-40+input:analog-stereo: Analog Surround 4.0 Output"
    " + Analog Stereo Input (sinks: 1, sources: 1, priority: 1265, available: yes)\n")
TUNED_SINK = "39\taudio_effect.iMac-convolver\tPipeWire\tfloat32le 2ch 48000Hz\tRUNNING\n"


def module():
    """The eq module's own definitions, lifted out of the real script."""
    source = PATCHER.read_text()
    start = source.index("# ═══════════════════════ module: eq ")
    return source[start:source.index("# ═══════════════════════ module: color ", start)]


class EqTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        # The module picks its installer from what is on PATH, so the runner's
        # own distribution must not decide which branch a test takes: a CI
        # machine with neither pacman nor dnf reaches the "install them
        # yourself" message and never prompts at all.
        self.stub("sudo", 'exec "$@"')
        self.stub("pacman", 'echo "PACMAN: $*"; exit 0')
        self.stub_audio()

    def stub_audio(self, hardware="0.40", visible="1.00", fail_node=""):
        # Use different node IDs from the real machine, plus another 4.0
        # device: the fix must target this card, not the first matching sink.
        self.stub("pw-cli", '''cat <<'EOF'
    id 12, type PipeWire:Interface:Node/3
        node.name = "alsa_output.usb-other.analog-surround-40"
    id 73, type PipeWire:Interface:Node/3
        node.name = "audio_effect.iMac-convolver"
    id 91, type PipeWire:Interface:Node/3
        node.name = "alsa_output.pci-0000_00_1f.3.analog-surround-40"
        media.class = "Audio/Sink/Internal"
EOF''')
        for node, value in (("91", hardware), ("73", visible)):
            (self.root / f"volume-{node}").write_text(value)
        self.stub("wpctl", f'''
state="{self.root}/volume-$2"
case "$1" in
    get-volume) printf 'Volume: %s\\n' "$(cat "$state")" ;;
    set-volume)
        echo "SET-VOLUME $2 $3"
        [[ $2 != "{fail_node}" ]] || exit 1
        case "$3" in
            45%) echo 0.45 > "$state" ;;
            100%) echo 1.00 > "$state" ;;
            *) printf '%s' "$3" > "$state" ;;
        esac ;;
    *) exit 1 ;;
esac''')

    def stub(self, name, body):
        path = self.bin / name
        path.write_text(f"#!/usr/bin/env bash\n{body}\n")
        path.chmod(0o755)

    def stub_pactl(self, four_channel_profile=True, active=STEREO, sinks=""):
        """A pactl that remembers the profile it was told to select, so the
        order of "restart, then select" can be checked the way the audio
        server enforces it."""
        profiles = FOUR_CHANNEL_PROFILE_LINE if four_channel_profile else ""
        (self.root / "card-profile").write_text(active)   # what the card is on now
        cards = PACTL_CARDS.format(profiles=profiles, active="$active")   # expanded by the heredoc
        path = self.bin / "pactl"
        path.write_text(f'''#!/usr/bin/env bash
state="{self.root}/card-profile"
case "$*" in
    "list cards")
        active=$(cat "$state")
        cat <<EOF
{cards}
EOF
        ;;
    "list sinks short")   printf '%s' '{sinks}' ;;
    "set-card-profile "*) echo "SET-PROFILE $3"; printf '%s' "$3" > "$state" ;;
    "set-default-sink "*) echo "SET-DEFAULT $2" ;;
esac
''')
        path.chmod(0o755)

    def run_eq(self, command):
        harness = f'''
set -uo pipefail
export PATH="{self.bin}:$PATH"
source "{ROOT}/scripts/lib/platform.sh"
product=iMac18,3
HOME="{self.root}/home"; XDG_DATA_HOME="{self.root}/home/.local/share"
CACHE="{self.root}/cache"; LOGDIR="{self.root}/state"
mkdir -p "$HOME" "$CACHE" "$LOGDIR"
say()  {{ printf '%s\\n' "$*"; }}
warn() {{ printf '%s\\n' "$*"; }}
confirm() {{ printf 'PROMPTED: %s\\n' "$1"; return 1; }}   # declines, installs nothing
'''
        return subprocess.run(["bash", "-c", harness + module() + command],
                              text=True, capture_output=True, timeout=10)

    def test_the_speaker_card_is_the_one_offering_a_4_0_profile(self):
        self.stub_pactl()
        result = self.run_eq("eq_card")
        self.assertEqual(result.stdout.strip(), f"alsa_card.pci-0000_00_1f.3 {STEREO}")

    def test_no_card_without_a_4_0_profile(self):
        # A stock driver: the card is there, the four-channel profile is not.
        self.stub_pactl(four_channel_profile=False)
        self.assertEqual(self.run_eq("eq_card").stdout.strip(), "")

    def test_applying_without_that_profile_changes_nothing(self):
        self.stub_pactl(four_channel_profile=False)
        result = self.run_eq("mod_eq_apply")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Apply the audio module first", result.stdout)
        self.assertFalse((self.root / "home/.config").exists())

    def test_detect_weighs_the_files_the_live_sink_and_the_card_profile(self):
        self.stub_pactl()
        self.assertEqual(self.run_eq("mod_eq_detect").stdout.strip(), "not-applied")

        # config and impulse responses in place, but the sink is not loaded
        setup = '''
mkdir -p "$(dirname "$EQ_CONF")" "$EQ_IRS_DIR"
touch "$EQ_CONF"
for f in "${EQ_IRS[@]}"; do touch "${EQ_IRS_DIR}/${f}"; done
mod_eq_detect'''
        self.assertEqual(self.run_eq(setup).stdout.strip(), "partial")

        # Everything installed and the sink loaded, but the card is still on
        # stereo: the two woofer channels go nowhere, which is what "quiet and
        # thin" sounds like. Not an "applied".
        self.stub_pactl(sinks=TUNED_SINK)
        self.assertEqual(self.run_eq(setup).stdout.strip(), "partial")

        self.stub_pactl(sinks=TUNED_SINK, active=FOUR_CHANNEL)
        self.assertEqual(self.run_eq(setup).stdout.strip(), "applied")

    def test_the_plugin_search_survives_an_unset_lv2_path(self):
        # `set -u` makes expanding an unset LV2_PATH fatal to the whole
        # process, not just the function: the patcher would die here before
        # printing a thing. Most machines have no LV2_PATH at all.
        self.stub_pactl()
        result = self.run_eq('unset LV2_PATH\neq_have_lv2 absent.lv2; echo "survived rc=$?"')
        self.assertIn("survived rc=1", result.stdout)
        self.assertNotIn("unbound variable", result.stderr)

        bundle = self.root / "lv2/present.lv2"
        bundle.mkdir(parents=True)
        result = self.run_eq(f'export LV2_PATH="{self.root}/lv2:/nowhere"\n'
                             'eq_have_lv2 present.lv2; echo "found rc=$?"')
        self.assertIn("found rc=0", result.stdout)

    def test_apply_stops_when_a_plugin_is_missing(self):
        # A filter node whose plugin is absent takes the whole graph with it,
        # so a declined install has to stop the apply, not proceed silently.
        self.stub_pactl()
        result = self.run_eq('eq_have_lv2() { return 1; }\nmod_eq_apply')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("missing LV2 plugins", result.stdout)
        self.assertIn("PROMPTED:", result.stdout)
        self.assertFalse((self.root / "home/.config").exists())

    def test_the_impulse_response_paths_are_rewritten_into_the_home_directory(self):
        # With the tuned sink loaded, so apply reaches its end instead of
        # waiting out the "did the graph come up?" retries.
        self.stub_pactl(sinks=TUNED_SINK)
        # eq_fetch's download step stands in for the network; the rest of apply
        # is what is under test here.
        fake_fetch = r'''
eq_fetch() {
    mkdir -p "$CACHE/imac-audio"
    printf '%s\n' '"filename": [ "/usr/share/imac-audio/Filters L Aug 14-MP.wav" ]' \
                  '"filename": [ "/usr/share/imac-audio/Filters LFE Aug 16-MP.wav" ]' \
        > "$CACHE/imac-audio/iMacAudio.conf"
    local f; for f in "${EQ_IRS[@]}"; do printf 'irs' > "$CACHE/imac-audio/$f"; done
}
eq_plugins() { :; }
eq_restart_pipewire() { echo RESTARTED; }
mod_eq_apply
echo "--- installed config ---"
cat "$EQ_CONF"'''
        result = self.run_eq(fake_fetch)
        home = self.root / "home"
        self.assertIn(f'"{home}/.local/share/imac-audio/Filters L Aug 14-MP.wav"', result.stdout)
        self.assertNotIn("/usr/share/imac-audio", result.stdout)
        for name in ("Filters L Aug 14-MP.wav", "Filters LFE Aug 16-MP.wav"):
            self.assertTrue((home / ".local/share/imac-audio" / name).is_file())

    def test_the_raw_device_is_hidden_while_the_tuning_is_installed(self):
        # Selected directly, the 4.0 device plays the tweeter half of the
        # crossover, so it is marked internal: still linkable by the chain,
        # no longer offered by pickers.
        self.stub_pactl(sinks=TUNED_SINK)
        self.run_eq('''
eq_fetch() {
    mkdir -p "$CACHE/imac-audio"; printf '%s' "$EQ_UPSTREAM_IRS_DIR/x" > "$CACHE/imac-audio/iMacAudio.conf"
    local f; for f in "${EQ_IRS[@]}"; do : > "$CACHE/imac-audio/$f"; done
}
eq_plugins() { :; }
eq_restart_pipewire() { :; }
mod_eq_apply''')
        rule = self.root / "home/.config/wireplumber/wireplumber.conf.d/51-imac-hide-raw-speakers.conf"
        self.assertTrue(rule.is_file())
        self.assertIn('media.class = "Audio/Sink/Internal"', rule.read_text())
        self.assertIn("analog-surround-40", rule.read_text())

    def test_the_card_profile_is_selected_after_the_restart(self):
        # WirePlumber re-applies its own stored profile as it comes back, so a
        # profile selected before the restart is undone by it: the graph then
        # feeds a stereo sink and the woofer channels link to nothing.
        self.stub_pactl(sinks=TUNED_SINK)
        result = self.run_eq('''
eq_fetch() {
    mkdir -p "$CACHE/imac-audio"; : > "$CACHE/imac-audio/iMacAudio.conf"
    printf '%s' "$EQ_UPSTREAM_IRS_DIR/x" >> "$CACHE/imac-audio/iMacAudio.conf"
    local f; for f in "${EQ_IRS[@]}"; do : > "$CACHE/imac-audio/$f"; done
}
eq_plugins() { :; }
eq_restart_pipewire() { echo RESTARTED; }
mod_eq_apply''')
        self.assertEqual(result.returncode, 0, result.stdout)
        order = [line for line in result.stdout.splitlines()
                 if line.startswith(("RESTARTED", "SET-PROFILE"))]
        self.assertEqual(order[:2], ["RESTARTED", f"SET-PROFILE {FOUR_CHANNEL}"])
        self.assertLess(result.stdout.index("SET-PROFILE"), result.stdout.index("SET-VOLUME"))
        self.assertIn("SET-VOLUME 73 45%\n", result.stdout)
        self.assertIn("SET-VOLUME 91 100%\n", result.stdout)
        self.assertLess(result.stdout.index("SET-VOLUME 73"), result.stdout.index("SET-VOLUME 91"))

    def test_reapply_preserves_the_original_hardware_level_and_user_slider(self):
        result = self.run_eq('''
eq_set_hardware_volume alsa_card.pci-0000_00_1f.3
wpctl set-volume 73 0.80
eq_set_hardware_volume alsa_card.pci-0000_00_1f.3
cat "$EQ_VOLUME_STATE"
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.count("SET-VOLUME 73 45%"), 1)
        self.assertEqual((self.root / "volume-73").read_text(), "0.80")
        self.assertEqual((self.root / "state/eq-hardware-volume").read_text(), "0.40\n")

    def test_apply_repairs_an_already_installed_eq_instead_of_skipping_it(self):
        self.stub_pactl(active=FOUR_CHANNEL)
        source = PATCHER.read_text()
        start = source.index("run_module() {")
        driver = source[start:source.index('\ncase "$ACTION" in', start)]
        result = self.run_eq(driver + '''
mod_eq_detect() { echo applied; }
mod_eq_apply() { echo UNEXPECTED-REINSTALL; return 1; }
run_module apply eq
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SET-VOLUME 91 100%", result.stdout)
        self.assertNotIn("UNEXPECTED-REINSTALL", result.stdout)

    def test_unreadable_hardware_volume_changes_nothing(self):
        self.stub("wpctl", "exit 1")
        result = self.run_eq("eq_set_hardware_volume alsa_card.pci-0000_00_1f.3")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("could not read the hardware volume", result.stdout)
        self.assertFalse((self.root / "state/eq-hardware-volume").exists())

    def test_quieter_visible_volume_is_preserved(self):
        self.stub_audio(visible="0.20")
        result = self.run_eq("eq_set_hardware_volume alsa_card.pci-0000_00_1f.3")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("SET-VOLUME 73", result.stdout)
        self.assertIn("SET-VOLUME 91 100%", result.stdout)

    def test_failed_visible_volume_change_does_not_raise_hardware(self):
        self.stub_audio(fail_node="73")
        result = self.run_eq("eq_set_hardware_volume alsa_card.pci-0000_00_1f.3")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("SET-VOLUME 91", result.stdout)
        self.assertEqual((self.root / "volume-91").read_text(), "0.40")

    def test_failed_hardware_volume_change_is_reported(self):
        self.stub_audio(fail_node="91")
        result = self.run_eq("eq_set_hardware_volume alsa_card.pci-0000_00_1f.3")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("could not set the hidden speaker output", result.stdout)

    def test_missing_hardware_node_does_not_change_another_device(self):
        self.stub("sleep", ":")
        result = self.run_eq("eq_set_hardware_volume alsa_card.not-present")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("SET-VOLUME", result.stdout)

    def test_remove_restores_hardware_volume_before_the_restart(self):
        self.stub_pactl(active=FOUR_CHANNEL)
        result = self.run_eq('''
eq_set_hardware_volume alsa_card.pci-0000_00_1f.3
eq_restart_pipewire() { echo RESTARTED; }
mod_eq_remove
''')
        self.assertLess(result.stdout.index("SET-VOLUME 91 0.40"), result.stdout.index("RESTARTED"))
        self.assertEqual((self.root / "volume-91").read_text(), "0.40")
        self.assertFalse((self.root / "state/eq-hardware-volume").exists())

    def test_failed_restore_preserves_the_saved_volume_and_installed_eq(self):
        self.stub_pactl(active=FOUR_CHANNEL)
        self.stub_audio(fail_node="91")
        result = self.run_eq('''
mkdir -p "$(dirname "$EQ_CONF")"
touch "$EQ_CONF"
echo 0.40 > "$EQ_VOLUME_STATE"
eq_restart_pipewire() { echo RESTARTED; }
mod_eq_remove
''')
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("RESTARTED", result.stdout)
        self.assertTrue((self.root / "state/eq-hardware-volume").exists())
        self.assertTrue((self.root / "home/.config/pipewire/pipewire.conf.d/imac-audio.conf").exists())

    def test_removing_puts_the_saved_card_profile_back(self):
        self.stub_pactl()
        script = '''
mkdir -p "$(dirname "$EQ_CONF")" "$EQ_IRS_DIR" "$(dirname "$EQ_HIDE_RULE")"
touch "$EQ_CONF" "${EQ_IRS_DIR}/one.wav" "$EQ_HIDE_RULE"
printf 'output:analog-stereo+input:analog-stereo\\n' > "$EQ_PROFILE_STATE"
eq_restart_pipewire() { :; }
mod_eq_remove
[[ -e $EQ_CONF ]] && echo "CONFIG LEFT BEHIND"
[[ -d $EQ_IRS_DIR ]] && echo "FILTERS LEFT BEHIND"
[[ -e $EQ_PROFILE_STATE ]] && echo "STATE LEFT BEHIND"
[[ -e $EQ_HIDE_RULE ]] && echo "HIDE RULE LEFT BEHIND"
exit 0'''
        result = self.run_eq(script)
        self.assertIn("card profile restored to output:analog-stereo+input:analog-stereo", result.stdout)
        self.assertNotIn("LEFT BEHIND", result.stdout)


if __name__ == "__main__":
    unittest.main()
