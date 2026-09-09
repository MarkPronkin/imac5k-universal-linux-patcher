"""Offline tests for the speaker tuning module: no audio server, no network."""
from pathlib import Path
import hashlib
import re
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
PATCHER = ROOT / "scripts/imac-patcher"

# Two cards as pactl prints them: the HDMI one first, so picking the card by
# "offers a 4.0 profile" is doing real work rather than taking the first.
FOUR_CHANNEL = "output:analog-surround-40+input:analog-stereo"
CARD = "alsa_card.pci-0000_00_1f.3"
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
# What the card exposes instead once a headphone plug moves it off the 4.0
# profile: the untuned jack output.
AUX_SINK = ("61\talsa_output.pci-0000_00_1f.3.analog-stereo\tPipeWire"
            "\ts32le 2ch 44100Hz\tSUSPENDED\n")

# A stand-in for the vendored tuning, so these tests do not depend on the real
# graph's contents. It carries what apply rewrites: the upstream impulse-response
# paths, the names of both of the chain's nodes, and the playback properties the
# speaker-device pin is inserted into.
ASSET_CONF = '''"node.name": "audio_effect.iMac-convolver",
"node.name": "effect_output.iMac-convolver",
"filename": [ "/usr/share/imac-audio/Filters L Aug 14-MP.wav" ]
"filename": [ "/usr/share/imac-audio/Filters LFE Aug 16-MP.wav" ]
            "playback.props": {
'''
# What apply pins the chain's output to, so a change of the default device --
# plugging in a USB DAC, say -- cannot move the measured tuning onto it.
SPEAKER_TARGET = "alsa_output.pci-0000_00_1f.3.analog-surround-40"
PINNED_CONF = f'"target.object": "{SPEAKER_TARGET}"\n'
IRS = ("Filters L Aug 14-MP.wav", "Filters R Aug 14-MP.wav",
       "Filters C2 Aug 16-MP.wav", "Filters LFE Aug 16-MP.wav")



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
        # One ordered log of what apply did, in the order it did it.
        self.trace = self.root / "trace.log"
        self.assets = self.root / "assets"
        # The module picks its installer from what is on PATH, so the runner's
        # own distribution must not decide which branch a test takes: a CI
        # machine with neither pacman nor dnf reaches the "install them
        # yourself" message and never prompts at all.
        self.stub("sudo", 'exec "$@"')
        self.stub("pacman", 'echo "PACMAN: $*"; exit 0')
        self.stub_systemctl()
        self.stub_audio()
        self.stub_pactl()

    def stub_systemctl(self):
        """A systemctl that remembers which units are enabled, so detection and
        removal can be checked against unit state rather than against a log."""
        units = self.root / "units"
        units.mkdir(exist_ok=True)
        trace = self.trace
        self.stub("systemctl", f'''
state="{units}"
[[ ${{1:-}} == --user ]] && shift
command=${{1:-}}; shift || true
echo "SYSTEMCTL $command $*" >> "{trace}"   # the module silences systemctl itself
for arg in "$@"; do
    case "$arg" in -*) continue ;; esac
    case "$command" in
        is-enabled) [[ -f "$state/$arg" ]] || exit 1 ;;
        enable)     : > "$state/$arg" ;;
        disable)    rm -f "$state/$arg" ;;
    esac
done
exit 0''')

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

    def stage_assets(self, conf=ASSET_CONF, missing=()):
        """Write a stand-in for the vendored tuning and point the module at it.
        Returns the bash preamble that overrides EQ_ASSETS."""
        self.assets.mkdir(parents=True, exist_ok=True)
        files = {"iMacAudio.conf": conf, **{name: "irs" for name in IRS}}
        for name, body in files.items():
            if name in missing:
                continue
            (self.assets / name).write_text(body)
        return f'''
EQ_ASSETS="{self.assets}"
eq_plugins() {{ :; }}
'''

    def stub_pactl(self, four_channel_profile=True, active=STEREO, sinks="",
                   default="alsa_output.pci-0000_00_1f.3.analog-stereo"):
        """A pactl that remembers the profile it was told to select, so the
        order of "restart, then select" can be checked the way the audio
        server enforces it. It also remembers the default sink, so claiming it
        can be checked against what the user had chosen."""
        profiles = FOUR_CHANNEL_PROFILE_LINE if four_channel_profile else ""
        (self.root / "card-profile").write_text(active)   # what the card is on now
        (self.root / "default-sink").write_text(default)  # what the user listens to
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
    "list short sinks")   printf '%s' '{sinks}' ;;
    "set-card-profile "*) echo "SET-PROFILE $3"; echo "SET-PROFILE $3" >> "{self.trace}"
                          printf '%s' "$3" > "$state" ;;
    "get-default-sink")   cat "{self.root}/default-sink" ;;
    "set-default-sink "*) echo "SET-DEFAULT $2"; printf '%s' "$2" > "{self.root}/default-sink" ;;
esac
''')
        path.chmod(0o755)

    def run_eq(self, command):
        harness = f'''
set -uo pipefail
export PATH="{self.bin}:$PATH"
source "{ROOT}/scripts/lib/platform.sh"
product=iMac18,3
SCRIPT_DIR="{ROOT}/scripts"
HOME="{self.root}/home"; XDG_DATA_HOME="{self.root}/home/.local/share"
CACHE="{self.root}/cache"; LOGDIR="{self.root}/state"
mkdir -p "$HOME" "$CACHE" "$LOGDIR"
say()  {{ printf '%s\\n' "$*"; }}
warn() {{ printf '%s\\n' "$*"; }}
confirm() {{ printf 'PROMPTED: %s\\n' "$1"; return 1; }}   # declines, installs nothing
'''
        return subprocess.run(["bash", "-c", harness + module() + command],
                              text=True, capture_output=True, timeout=10)

    def install_eq(self, pin=True, wait=True):
        """The shell preamble for an installed tuning, for detect/remove tests.
        With pin=False the config is left as an install from before the chain's
        output was pinned to the speaker device; with wait=False the unit is
        left as one from before its start was gated on that device existing."""
        write = f"printf '%s' '{PINNED_CONF}' >" if pin else "touch"
        legacy = "" if wait else 'sed -i "/ExecStartPre=/d" "${EQ_UNIT_DIR}/${EQ_UNIT}"'
        return f'''
mkdir -p "$EQ_CONF_DIR" "$EQ_IRS_DIR"
touch "$EQ_BASE_CONF"
{write} "$EQ_CONF"
for f in "${{EQ_IRS[@]}}"; do touch "${{EQ_IRS_DIR}}/${{f}}"; done
eq_write_units {CARD}
{legacy}
eq_install_jack_helper
systemctl --user enable "$EQ_UNIT" "$EQ_JACK_UNIT"
'''

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
        setup = self.install_eq() + "mod_eq_detect"
        self.assertEqual(self.run_eq(setup).stdout.strip(), "partial")

        # Everything installed and the sink loaded, but the card is still on
        # stereo: the two woofer channels go nowhere, which is what "quiet and
        # thin" sounds like. Not an "applied".
        self.stub_pactl(sinks=TUNED_SINK)
        self.assertEqual(self.run_eq(setup).stdout.strip(), "partial")

        self.stub_pactl(sinks=TUNED_SINK, active=FOUR_CHANNEL)
        self.assertEqual(self.run_eq(setup).stdout.strip(), "applied")

    def test_the_tuning_waits_for_the_device_it_targets_before_starting(self):
        """Started with the card not yet enumerated, the chain registers no
        sink and does not exit, so nothing restarts it and the hidden 4.0
        device leaves the session with no output at all."""
        self.stub_pactl()
        self.run_eq("eq_write_units alsa_card.pci-0000_00_1f.3")
        unit = (self.root / "home/.config/systemd/user/imac-speaker-eq.service").read_text()
        pre = next(l for l in unit.splitlines() if l.startswith("ExecStartPre="))
        # The device it waits for is the one the chain is pinned to.
        self.assertIn("alsa_output.pci-0000_00_1f.3.analog-surround-40", pre)
        # pactl cannot see it: this module hides it from the PulseAudio layer.
        self.assertIn("pw-cli", pre)
        self.assertNotIn("pactl", pre)
        # Bounded, and it must run before the chain, not alongside it.
        self.assertIn("timeout", pre)
        self.assertLess(unit.index("ExecStartPre="), unit.index("ExecStart=/"))
        # A wait that never succeeds has to fail the unit, not start it anyway.
        self.assertIn("Restart=on-failure", unit)

    def test_an_ungated_start_needs_reapplying(self):
        # An install from before the start was gated on the target device is
        # indistinguishable from a working one until the next boot, when the
        # chain comes up too early and the session is left with no output.
        self.stub_pactl(sinks=TUNED_SINK, active=FOUR_CHANNEL)
        self.assertEqual(self.run_eq(self.install_eq() + "mod_eq_detect").stdout.strip(),
                         "applied")
        self.assertEqual(self.run_eq(self.install_eq(wait=False) + "mod_eq_detect").stdout.strip(),
                         "partial")

    def test_an_unpinned_output_needs_reapplying(self):
        # An install from before the chain's output was pinned to the speaker
        # device has every file in place and the sink loaded, but WirePlumber
        # re-links that output with the default device -- onto a USB DAC, say.
        # It needs re-applying, so it is a "partial", not an "applied".
        self.stub_pactl(sinks=TUNED_SINK, active=FOUR_CHANNEL)
        self.assertEqual(self.run_eq(self.install_eq(pin=False) + "mod_eq_detect").stdout.strip(), "partial")

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
        result = self.run_eq(self.stage_assets() + '''
eq_restart_pipewire() { echo RESTARTED; }
mod_eq_apply
echo "--- installed config ---"
cat "$EQ_CONF"''')
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
        self.run_eq(self.stage_assets() + '''
eq_restart_pipewire() { :; }
mod_eq_apply''')
        rule = self.root / "home/.config/wireplumber/wireplumber.conf.d/51-imac-hide-raw-speakers.conf"
        self.assertTrue(rule.is_file())
        self.assertIn('media.class = "Audio/Sink/Internal"', rule.read_text())
        self.assertIn("analog-surround-40", rule.read_text())
        # The jack output is named by exact node name: a USB DAC presents an
        # "analog-stereo" sink too, and renaming that one would be wrong.
        self.assertIn('node.name = "alsa_output.pci-0000_00_1f.3.analog-stereo"',
                      rule.read_text())
        for key in ("node.description", "node.nick"):
            self.assertIn(f'{key} = "Aux Audio Output"', rule.read_text())

    def test_the_card_profile_is_selected_after_the_restart(self):
        # WirePlumber re-applies its own stored profile as it comes back, so a
        # profile selected before the restart is undone by it: the graph then
        # feeds a stereo sink and the woofer channels link to nothing.
        self.stub_pactl(sinks=TUNED_SINK)
        result = self.run_eq(self.stage_assets() + '''
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

    def test_headphones_block_eq_install_and_hardware_volume_increases(self):
        self.stub_pactl(active=FOUR_CHANNEL)
        pactl = self.bin / "pactl"
        pactl.write_text(pactl.read_text().replace(
            "\tActive Profile: $active",
            "\tPorts:\n\t\tanalog-output-headphones: Headphones (type: Headphones, priority: 9900, available)\n"
            "\tActive Profile: $active"))
        for command in ("mod_eq_apply", "eq_set_hardware_volume alsa_card.pci-0000_00_1f.3"):
            with self.subTest(command=command):
                result = self.run_eq(command)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Unplug headphones", result.stdout)
                self.assertNotIn("SET-VOLUME", result.stdout)
                self.assertEqual((self.root / "volume-91").read_text(), "0.40")
                self.assertFalse((self.root / "home/.config/pipewire/imac-speaker-eq.conf.d/imac-audio.conf").exists())

    def test_headphones_on_another_card_do_not_block_speaker_adjustment(self):
        self.stub_pactl(active=FOUR_CHANNEL)
        pactl = self.bin / "pactl"
        pactl.write_text(pactl.read_text().replace(
            "\tActive Profile: off",
            "\tPorts:\n\t\tanalog-output-headphones: Headphones (type: Headphones, priority: 9900, available)\n"
            "\tActive Profile: off"))
        result = self.run_eq("eq_set_hardware_volume alsa_card.pci-0000_00_1f.3")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("SET-VOLUME 91 100%", result.stdout)

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
mkdir -p "$EQ_CONF_DIR"
touch "$EQ_CONF"
echo 0.40 > "$EQ_VOLUME_STATE"
eq_restart_pipewire() { echo RESTARTED; }
mod_eq_remove
''')
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("RESTARTED", result.stdout)
        self.assertTrue((self.root / "state/eq-hardware-volume").exists())
        self.assertTrue((self.root / "home/.config/pipewire/imac-speaker-eq.conf.d/imac-audio.conf").exists())

    def test_removing_puts_the_saved_card_profile_back(self):
        self.stub_pactl()
        script = '''
mkdir -p "$EQ_CONF_DIR" "$EQ_IRS_DIR" "$(dirname "$EQ_HIDE_RULE")"
touch "$EQ_CONF" "$EQ_BASE_CONF" "${EQ_IRS_DIR}/one.wav" "$EQ_HIDE_RULE"
eq_write_units alsa_card.pci-0000_00_1f.3
eq_install_jack_helper
systemctl --user enable "$EQ_UNIT" "$EQ_JACK_UNIT"
printf 'output:analog-stereo+input:analog-stereo\\n' > "$EQ_PROFILE_STATE"
eq_restart_pipewire() { :; }
mod_eq_remove
[[ -e $EQ_CONF ]] && echo "CONFIG LEFT BEHIND"
[[ -e $EQ_BASE_CONF ]] && echo "BASE CONFIG LEFT BEHIND"
[[ -d $EQ_CONF_DIR ]] && echo "CONFIG DIR LEFT BEHIND"
[[ -d $EQ_IRS_DIR ]] && echo "FILTERS LEFT BEHIND"
[[ -e $EQ_PROFILE_STATE ]] && echo "STATE LEFT BEHIND"
[[ -e $EQ_HIDE_RULE ]] && echo "HIDE RULE LEFT BEHIND"
[[ -e $EQ_JACK_BIN ]] && echo "HELPER LEFT BEHIND"
[[ -e "${EQ_UNIT_DIR}/${EQ_UNIT}" ]] && echo "UNIT LEFT BEHIND"
[[ -e "${EQ_UNIT_DIR}/${EQ_JACK_UNIT}" ]] && echo "JACK UNIT LEFT BEHIND"
eq_units_installed && echo "UNITS STILL ENABLED"
exit 0'''
        result = self.run_eq(script)
        self.assertIn("card profile restored to output:analog-stereo+input:analog-stereo", result.stdout)
        self.assertNotIn("LEFT BEHIND", result.stdout)
        self.assertNotIn("UNITS STILL ENABLED", result.stdout)

    def with_headphones(self, **kwargs):
        """A card reporting a headphone plug, as pactl prints it."""
        self.stub_pactl(**kwargs)
        pactl = self.bin / "pactl"
        pactl.write_text(pactl.read_text().replace(
            "\tActive Profile: $active",
            "\tPorts:\n\t\tanalog-output-headphones: Headphones (type: Headphones,"
            " priority: 9900, available)\n\tActive Profile: $active"))

    def test_detect_accepts_the_jack_output_while_headphones_are_in(self):
        # With the jack in use the tuning is *meant* to be stopped and the card
        # *meant* to be on stereo. Looking for the tuned sink and the 4.0
        # profile then would report a working install as broken.
        installed = self.install_eq() + "mod_eq_detect"
        self.with_headphones(sinks=AUX_SINK)
        self.assertEqual(self.run_eq(installed).stdout.strip(), "applied")

        # The same install with the jack output missing is not a working one.
        self.with_headphones(sinks="")
        self.assertEqual(self.run_eq(installed).stdout.strip(), "partial")

        # And with the headphones out, the tuned sink is required again.
        self.stub_pactl(sinks=AUX_SINK, active=FOUR_CHANNEL)
        self.assertEqual(self.run_eq(installed).stdout.strip(), "partial")

    def test_apply_removes_a_pre_service_config_from_the_daemon(self):
        # An install from before headphone switching loaded the same graph in
        # the session daemon. Left there it is a second copy of the chain that
        # no service can stop, so the tuned sink would never go away.
        self.stub_pactl(sinks=TUNED_SINK)
        result = self.run_eq(self.stage_assets() + '''
mkdir -p "$(dirname "$EQ_LEGACY_CONF")"
echo "old in-daemon graph" > "$EQ_LEGACY_CONF"
mod_eq_apply
[[ -e $EQ_LEGACY_CONF ]] && echo "LEGACY CONFIG LEFT BEHIND"
[[ -f $EQ_CONF && -f $EQ_BASE_CONF ]] || echo "NEW CONFIG MISSING"
exit 0''')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("LEGACY CONFIG LEFT BEHIND", result.stdout)
        self.assertNotIn("NEW CONFIG MISSING", result.stdout)

    def test_the_units_are_stopped_before_the_restart_and_started_after_it(self):
        # A re-apply must not let the chain come up against whichever profile
        # WirePlumber restores: it would feed a stereo sink, the woofer
        # channels would link to nothing, and the tuning would be the tweeter
        # half of a crossover. Stop, restart, choose the profile, then start.
        self.stub_pactl(sinks=TUNED_SINK)
        result = self.run_eq(self.stage_assets() + f'''
eq_restart_pipewire() {{ echo RESTARTED >> "{self.trace}"; }}
mod_eq_apply''')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        steps = self.trace.read_text().splitlines()
        first = lambda prefix: next(i for i, line in enumerate(steps)
                                    if line.startswith(prefix))
        self.assertLess(first("SYSTEMCTL stop"), first("RESTARTED"))
        self.assertLess(first("RESTARTED"), first("SET-PROFILE"))
        self.assertLess(first("SET-PROFILE"), first("SYSTEMCTL enable"))

    def test_the_tunings_own_output_is_renamed_out_of_the_application_list(self):
        # The chain's output is a playback stream, so desktops list it beside
        # real applications. Omarchy's panel already skips a tuning's output,
        # but recognises it by name.
        self.stub_pactl(sinks=TUNED_SINK)
        result = self.run_eq(self.stage_assets() + '''
eq_restart_pipewire() { :; }
mod_eq_apply
echo "--- installed config ---"
cat "$EQ_CONF"''')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        config = result.stdout.split("--- installed config ---")[1]
        self.assertIn('"node.name": "omarchy_speaker_tuning_imac5k_output"', config)
        self.assertNotIn("effect_output.iMac-convolver", config)
        # The sink the user actually picks keeps its name; everything else
        # refers to it by that name.
        self.assertIn('"node.name": "audio_effect.iMac-convolver"', config)

    def test_a_renamed_upstream_output_is_reported_but_does_not_fail_apply(self):
        # Cosmetic, unlike the impulse-response paths: worth saying out loud,
        # not worth refusing a working tuning over.
        self.stub_pactl(sinks=TUNED_SINK)
        renamed = ASSET_CONF.replace('"effect_output.iMac-convolver"', '"something_else"')
        result = self.run_eq(self.stage_assets(conf=renamed) + '''
eq_restart_pipewire() { :; }
mod_eq_apply''')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("will be listed as an application", result.stdout)

    def test_the_chains_output_is_pinned_to_the_speaker_device(self):
        # Without a target, WirePlumber links the chain's output to the default
        # device and re-links it every time the default changes: plug in a USB
        # DAC and the measured crossover and EQ play on the DAC.
        self.stub_pactl(sinks=TUNED_SINK)
        result = self.run_eq(self.stage_assets() + '''
eq_restart_pipewire() { :; }
mod_eq_apply
echo "--- installed config ---"
cat "$EQ_CONF"''')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        config = result.stdout.split("--- installed config ---")[1]
        self.assertIn(f'"target.object": "{SPEAKER_TARGET}"', config)
        self.assertIn('"node.dont-move": "true"', config)

    def test_apply_fails_when_the_output_cannot_be_pinned(self):
        # Pinning is functional, not cosmetic: a config with no playback
        # properties to anchor to installs a chain that follows the default
        # device onto whatever the user plugs in.
        self.stub_pactl(sinks=TUNED_SINK)
        result = self.run_eq(self.stage_assets(
            conf=ASSET_CONF.replace('"playback.props": {', 'no anchor')) + '''
eq_restart_pipewire() { :; }
mod_eq_apply''')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("could not pin the tuning", result.stdout)

    def test_apply_claims_the_default_from_a_built_in_output(self):
        self.stub_pactl(sinks=TUNED_SINK)
        result = self.run_eq(self.stage_assets() + '''
eq_restart_pipewire() { :; }
mod_eq_apply''')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(f"SET-DEFAULT {TUNED_SINK.split()[1]}", result.stdout)

    def test_apply_leaves_a_chosen_external_default_alone(self):
        # Re-applying while the user listens through a USB DAC must not yank
        # their output back to the speakers.
        self.stub_pactl(sinks=TUNED_SINK,
                        default="alsa_output.usb-AudioQuest_DragonFly.analog-stereo")
        result = self.run_eq(self.stage_assets() + '''
eq_restart_pipewire() { :; }
mod_eq_apply''')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("SET-DEFAULT", result.stdout)
        self.assertIn("default output left on alsa_output.usb-AudioQuest_DragonFly.analog-stereo",
                      result.stdout)

    def test_apply_stops_when_the_vendored_tuning_is_missing(self):
        # A checkout without the assets would otherwise install a graph whose
        # convolvers point at files that are not there, and the sink would
        # simply never appear.
        self.stub_pactl(sinks=TUNED_SINK)
        result = self.run_eq(self.stage_assets(missing=("Filters C2 Aug 16-MP.wav",)) + '''
eq_restart_pipewire() { echo RESTARTED; }
mod_eq_apply''')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("missing from this checkout", result.stdout)
        self.assertNotIn("RESTARTED", result.stdout)
        self.assertFalse((self.root / "home/.config").exists())


    # ── bankstown, built rather than taken from the AUR ───────────────────
    def stub_bankstown_build(self):
        """git and cargo that record what they were asked to do and produce the
        files the upstream Makefile's install target copies."""
        upstream = self.root / "upstream"
        (upstream / "target/release").mkdir(parents=True, exist_ok=True)
        for name in ("bankstown.ttl", "manifest.ttl"):
            (upstream / name).write_text(name)
        self.stub("git", f'''
echo "GIT $*" >> "{self.trace}"
case "$*" in
    *cat-file*) exit 1 ;;                       # the pin is not cached yet
    *archive*)  tar -cf - -C "{upstream}" . ;;
esac
exit 0''')
        self.stub("cargo", f'''
echo "CARGO $*" >> "{self.trace}"
printf 'so' > target/release/libbankstown.so
exit 0''')

    def test_bankstown_is_built_from_source_rather_than_from_the_aur(self):
        # An AUR helper is an Arch-only answer and would leave Fedora with none
        # at all. The AUR package itself does nothing but run cargo.
        self.stub_bankstown_build()
        result = self.run_eq('''
eq_have_lv2() { [[ $1 == lsp-plugins.lv2 ]] || [[ -d "${EQ_LV2_USER_DIR}/$1" ]]; }
confirm() { printf 'PROMPTED: %s\\n' "$1"; return 0; }
eq_plugins''')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PROMPTED: Build bankstown from source", result.stdout)
        steps = self.trace.read_text()
        self.assertIn("CARGO build --release --locked", steps)
        # Pinned, and exported rather than built in the cached clone.
        self.assertIn("e9829c9bccf5ed73768135c0ddd506f5a6690f9e", steps)
        bundle = self.root / "home/.lv2/bankstown.lv2"
        for name in ("bankstown.so", "bankstown.ttl", "manifest.ttl"):
            with self.subTest(name=name):
                self.assertTrue((bundle / name).is_file(), name)
        self.assertTrue((self.root / "state/eq-bankstown").is_file())

    def test_declining_the_build_stops_the_apply(self):
        # A missing plugin takes the whole graph with it and the sink never
        # appears, so proceeding would install a tuning that cannot load.
        self.stub_bankstown_build()
        result = self.run_eq('''
eq_have_lv2() { [[ $1 == lsp-plugins.lv2 ]] || [[ -d "${EQ_LV2_USER_DIR}/$1" ]]; }
eq_plugins''')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("PROMPTED:", result.stdout)
        self.assertFalse((self.root / "home/.lv2").exists())

    def test_nothing_is_built_when_the_distribution_packages_it(self):
        self.stub_bankstown_build()
        result = self.run_eq("eq_have_lv2() { :; }\neq_plugins")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(self.trace.exists() and "CARGO" in self.trace.read_text())

    def test_removal_keeps_a_bankstown_the_user_installed_themselves(self):
        # Only a bundle this module built is ours to delete.
        self.stub_pactl(active=FOUR_CHANNEL)
        result = self.run_eq('''
mkdir -p "$EQ_BANKSTOWN_BUNDLE"
touch "${EQ_BANKSTOWN_BUNDLE}/bankstown.so"
eq_restart_pipewire() { :; }
mod_eq_remove
[[ -e "${EQ_BANKSTOWN_BUNDLE}/bankstown.so" ]] && echo "USER BUNDLE KEPT"
exit 0''')
        self.assertIn("USER BUNDLE KEPT", result.stdout)

    def test_removal_takes_away_a_bankstown_this_module_built(self):
        self.stub_pactl(active=FOUR_CHANNEL)
        result = self.run_eq('''
mkdir -p "$EQ_BANKSTOWN_BUNDLE"
touch "${EQ_BANKSTOWN_BUNDLE}/bankstown.so"
printf 'pin\\n' > "$EQ_BANKSTOWN_STATE"
eq_restart_pipewire() { :; }
mod_eq_remove
[[ -e $EQ_BANKSTOWN_BUNDLE ]] && echo "BUILT BUNDLE LEFT BEHIND"
[[ -e $EQ_BANKSTOWN_STATE ]] && echo "STATE LEFT BEHIND"
exit 0''')
        self.assertNotIn("LEFT BEHIND", result.stdout)


class VendoredTuningTests(unittest.TestCase):
    """The tuning ships in the repository, so its integrity is checkable here
    rather than at apply time on a user's machine."""

    ASSETS = ROOT / "assets/imac-audio"

    def test_every_file_the_module_installs_is_present(self):
        source = PATCHER.read_text()
        names = re.search(r"EQ_IRS=\((.*?)\)", source, re.S).group(1)
        expected = re.findall(r'"([^"]+)"', names)
        self.assertEqual(len(expected), 4, expected)
        for name in [*expected, "iMacAudio.conf"]:
            with self.subTest(name=name):
                self.assertTrue((self.ASSETS / name).is_file(), name)

    def test_the_files_match_the_checksums_recorded_beside_them(self):
        # They are byte-identical to the upstream commit the README names, so
        # anyone can check them against it. A silent edit here would be a
        # tuning change nobody could trace.
        readme = (self.ASSETS / "README.md").read_text()
        recorded = dict(
            (name, digest) for digest, name in
            re.findall(r"^([0-9a-f]{64})  (.+)$", readme, re.M))
        self.assertEqual(len(recorded), 5, recorded)
        for name, digest in recorded.items():
            with self.subTest(name=name):
                actual = hashlib.sha256((self.ASSETS / name).read_bytes()).hexdigest()
                self.assertEqual(actual, digest, f"{name} differs from its recorded checksum")

    def test_the_config_still_carries_what_apply_rewrites(self):
        # Apply rewrites the impulse-response paths and the output node name,
        # and pins the output to the speaker device inside the playback
        # properties. If a future update to the vendored file drops any of
        # these, a rewrite silently stops applying.
        config = (self.ASSETS / "iMacAudio.conf").read_text()
        self.assertIn("/usr/share/imac-audio/", config)
        self.assertIn('"effect_output.iMac-convolver"', config)
        self.assertIn('"audio_effect.iMac-convolver"', config)
        self.assertIn('"playback.props": {', config)


if __name__ == "__main__":
    unittest.main()
