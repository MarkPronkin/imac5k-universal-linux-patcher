"""Offline tests for headphone jack switching: no audio server, no systemd."""
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SWITCH = ROOT / "scripts/imac-audio-jack-switch"

CARD = "alsa_card.pci-0000_00_1f.3"
AUX = "alsa_output.pci-0000_00_1f.3.analog-stereo"
TUNED = "audio_effect.iMac-convolver"
FOUR_CHANNEL = "output:analog-surround-40+input:analog-stereo"
STEREO = "output:analog-stereo+input:analog-stereo"

# Two cards, the HDMI one first, so "the card offering a 4.0 profile" is doing
# real work rather than taking whichever comes first.
CARDS = """Card #51
\tName: alsa_card.pci-0000_01_00.1
\tDriver: alsa
\tProfiles:
\t\toutput:hdmi-stereo: Digital Stereo (HDMI) Output (sinks: 1, sources: 0, priority: 5900, available: no)
\tPorts:
\t\thdmi-output-0: HDMI (type: HDMI, priority: 5900, not available)
\tActive Profile: off

Card #52
\tName: {card}
\tDriver: alsa
\tProfiles:
\t\toutput:analog-stereo+input:analog-stereo: Analog Stereo Duplex (sinks: 1, sources: 1, priority: 6565, available: yes)
\t\t{four}: Analog Surround 4.0 Output + Analog Stereo Input (sinks: 1, sources: 1, priority: 1265, available: yes)
\tPorts:
\t\tanalog-output-speaker: Speakers (type: Speaker, priority: 10000, {speaker})
\t\tanalog-output-headphones: Headphones (type: Headphones, priority: 9900, {headphones})
\tActive Profile: $active
"""


def switcher():
    """The script's definitions, without its main loop."""
    source = SWITCH.read_text()
    return source[:source.index('\nmain "$@"')]


class JackSwitchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.trace = self.root / "trace.log"
        self.stub("sleep", ":")            # the waits are what make this slow
        self.stub_systemctl()
        self.stub_pactl()

    def stub(self, name, body):
        path = self.bin / name
        path.write_text(f"#!/usr/bin/env bash\n{body}\n")
        path.chmod(0o755)

    def stub_systemctl(self, installed=True):
        self.stub("systemctl", f'''
[[ ${{1:-}} == --user ]] && shift
echo "SYSTEMCTL $*" >> "{self.trace}"
case "${{1:-}}" in
    cat) [[ "{str(installed).lower()}" == true ]] || exit 1 ;;
esac
exit 0''')

    def stub_pactl(self, headphones=False, active=FOUR_CHANNEL, sinks=(),
                   inputs=(), default=TUNED, four_channel=True):
        """`sinks` is (id, name) pairs; `inputs` is (stream id, sink id) pairs."""
        cards = CARDS.format(
            card=CARD, four=FOUR_CHANNEL if four_channel else "output:unused",
            speaker="not available" if headphones else "availability unknown",
            headphones="available" if headphones else "not available")
        sink_lines = "".join(
            f"{i}\t{n}\tPipeWire\ts32le 2ch 44100Hz\tSUSPENDED\n" for i, n in sinks)
        input_lines = "".join(
            f"Sink Input #{s}\n\tDriver: PipeWire\n\tSink: {k}\n" for s, k in inputs)
        (self.root / "default-sink").write_text(default)
        self.stub("pactl", f'''
state="{self.root}/default-sink"
export LC_ALL=C
case "$*" in
    "list cards")
        active="{active}"
        cat <<EOF
{cards}
EOF
        ;;
    "list short sinks")  printf '%s' '{sink_lines}' ;;
    "list sink-inputs")  printf '%s' '{input_lines}' ;;
    "get-default-sink")  cat "$state" ;;
    "set-default-sink "*) echo "SET-DEFAULT $2" >> "{self.trace}"; printf '%s' "$2" > "$state" ;;
    "move-sink-input "*) echo "MOVE $2 -> $3" >> "{self.trace}" ;;
esac
exit 0''')

    def run_switch(self, command):
        harness = f'''
set -uo pipefail
export PATH="{self.bin}:$PATH"
'''
        return subprocess.run(["bash", "-c", harness + switcher() + "\n" + command],
                              text=True, capture_output=True, timeout=30)

    def steps(self):
        return self.trace.read_text().splitlines() if self.trace.exists() else []

    # ── identifying the hardware ──────────────────────────────────────────
    def test_the_speaker_card_is_the_one_offering_a_4_0_profile(self):
        self.assertEqual(self.run_switch("speaker_card").stdout.strip(), CARD)

    def test_no_card_without_a_4_0_profile(self):
        self.stub_pactl(four_channel=False)
        self.assertEqual(self.run_switch("speaker_card").stdout.strip(), "")

    def test_the_jack_output_is_derived_from_the_card_not_matched_by_pattern(self):
        # A USB DAC presents an "analog-stereo" sink too; only this card's is
        # the headphone jack.
        self.assertEqual(self.run_switch(f"eq=$(aux_sink {CARD}); echo $eq").stdout.strip(), AUX)

    def test_only_a_positively_available_headphone_port_counts(self):
        # "availability unknown" is what a jack that cannot report insertion
        # says, and it must not read as one in use.
        self.stub_pactl(headphones=True)
        self.assertEqual(self.run_switch(f"headphones_present {CARD}; echo rc=$?")
                         .stdout.strip(), "rc=0")
        self.stub_pactl(headphones=False)
        self.assertEqual(self.run_switch(f"headphones_present {CARD}; echo rc=$?")
                         .stdout.strip(), "rc=1")

    # ── choosing what to carry across ─────────────────────────────────────
    def test_only_streams_on_the_departing_sink_are_carried(self):
        # Streams the user sent to Bluetooth or HDMI are their choice.
        self.stub_pactl(sinks=((40, TUNED), (41, AUX), (42, "bluez_output.x")),
                        inputs=((70, 40), (71, 42), (72, 41)))
        result = self.run_switch(f"inputs_on {TUNED} auto_null")
        self.assertEqual(result.stdout.split(), ["70"])

    def test_streams_stranded_on_the_dummy_sink_are_carried_too(self):
        self.stub_pactl(sinks=((40, TUNED), (43, "auto_null")),
                        inputs=((70, 43), (71, 40)))
        self.assertEqual(sorted(self.run_switch(f"inputs_on {TUNED} auto_null").stdout.split()),
                         ["70", "71"])

    # ── taking over the default ───────────────────────────────────────────
    def test_the_default_is_claimed_only_from_a_sink_we_own(self):
        self.stub_pactl(default=TUNED)
        self.run_switch(f"claim_default {AUX} {TUNED} auto_null")
        self.assertIn(f"SET-DEFAULT {AUX}", self.steps())

    def test_a_users_own_output_choice_outranks_the_jack(self):
        self.stub_pactl(default="bluez_output.headset")
        result = self.run_switch(f"claim_default {AUX} {TUNED} auto_null")
        self.assertEqual(self.steps(), [])
        self.assertIn("left on bluez_output.headset", result.stdout)

    # ── the two transitions ───────────────────────────────────────────────
    def test_plugging_in_stops_the_tuning_and_moves_streams_to_the_jack(self):
        self.stub_pactl(headphones=True, active=STEREO, default=TUNED,
                        sinks=((40, TUNED), (41, AUX)), inputs=((70, 40),))
        result = self.run_switch(f"to_headphones {CARD}")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        steps = self.steps()
        self.assertIn("SYSTEMCTL stop imac-speaker-eq.service", steps)
        self.assertIn(f"SET-DEFAULT {AUX}", steps)
        self.assertIn(f"MOVE 70 -> {AUX}", steps)

    def test_the_tuning_is_left_alone_if_the_jack_output_never_appears(self):
        # Stopping it with nowhere else to go would stranded the streams on a
        # dummy sink rather than move them to headphones.
        self.stub_pactl(headphones=True, active=STEREO, default=TUNED, sinks=((40, TUNED),))
        result = self.run_switch(f"to_headphones {CARD}")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.steps(), [])
        self.assertIn("never appeared", result.stdout)

    def test_unplugging_waits_for_the_4_0_profile_before_starting_the_tuning(self):
        # Started against a stereo card the chain has nothing to link its two
        # woofer channels to, and plays the tweeter half of a crossover.
        self.stub_pactl(headphones=False, active=FOUR_CHANNEL, default=AUX,
                        sinks=((40, TUNED), (41, AUX)), inputs=((70, 41),))
        result = self.run_switch(f"to_speakers {CARD}")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        steps = self.steps()
        self.assertIn("SYSTEMCTL start imac-speaker-eq.service", steps)
        self.assertIn(f"SET-DEFAULT {TUNED}", steps)
        self.assertIn(f"MOVE 70 -> {TUNED}", steps)

    def test_startup_does_nothing_when_the_tuning_is_not_installed(self):
        # Without the eq module there is no tuned sink to hide, and the stock
        # behaviour is already right.
        self.stub_systemctl(installed=False)
        result = self.run_switch('main')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("nothing to switch", result.stdout)


if __name__ == "__main__":
    unittest.main()
