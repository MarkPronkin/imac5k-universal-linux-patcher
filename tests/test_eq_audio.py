"""Optional DSP smoke test with real LV2 plugins, private sockets and no hardware.

Set IMAC5K_REQUIRE_EQ_AUDIO_TESTS=1 to require local PipeWire tools and plugins.
The acoustic response still needs a measurement microphone and real speakers.
"""
import array
import json
import math
import os
from pathlib import Path
import struct
import subprocess
import unittest

import test_eq as eq
import test_t2speakers_audio as audio


class SpeakerEqAudioTests(unittest.TestCase):
    def test_current_and_legacy_graphs_render_four_finite_channels(self):
        required = os.environ.get("IMAC5K_REQUIRE_EQ_AUDIO_TESTS") == "1"
        lv2_dirs = [Path.home() / ".lv2", Path("/usr/lib/lv2"),
                    Path("/usr/lib64/lv2"), Path("/usr/local/lib/lv2")]
        lv2_dirs.extend(Path(p) for p in os.environ.get("LV2_PATH", "").split(":") if p)
        lv2_dirs = list(dict.fromkeys(p.resolve() for p in lv2_dirs if p.is_dir()))
        for plugin in ("bankstown.lv2", "lsp-plugins.lv2"):
            if not any((p / plugin).is_dir() for p in lv2_dirs):
                if required:
                    self.fail(f"EQ audio test needs {plugin}")
                self.skipTest(f"EQ audio test needs {plugin}")
        for tuning in ("current", "legacy"):
            with self.subTest(tuning=tuning):
                self.render(tuning, lv2_dirs, required)

    def render(self, tuning, lv2_dirs, required):
        # Reuse the private server lifecycle, not its T2 speaker configuration.
        private = audio.NativeAudioTests()
        self.addCleanup(private.doCleanups)
        try:
            private.setUp()
        except unittest.SkipTest as error:
            if required:
                self.fail(str(error))
            raise
        installer = eq.EqTests()
        self.addCleanup(installer.doCleanups)
        installer.setUp()
        installer.stub_pactl(sinks=eq.TUNED_SINK)
        result = installer.run_eq('''
eq_plugins() { :; }
eq_restart_pipewire() { :; }
mod_eq_apply''', tuning=tuning)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        private.env["LV2_PATH"] = ":".join(map(str, lv2_dirs))
        output = private.root / "speakers.wav"
        configuration = {
            "context.properties": {"core.daemon": True, "core.name": "t2-test",
                                   "default.clock.rate": 48000},
            "context.spa-libs": {"audio.convert.*": "audioconvert/libspa-audioconvert",
                                 "support.*": "support/libspa-support"},
            "context.modules": [{"name": "libpipewire-module-" + name} for name in (
                "protocol-native", "metadata", "spa-node-factory", "client-node",
                "client-device", "access", "adapter", "link-factory", "session-manager")],
            "context.objects": [
                {"factory": "spa-node-factory", "args": {
                    "factory.name": "support.node.driver", "node.name": "Dummy-Driver",
                    "node.group": "pipewire.dummy", "priority.driver": 20000}},
                {"factory": "adapter", "args": {
                    "factory.name": "support.null-audio-sink",
                    "node.name": eq.SPEAKER_TARGET, "media.class": "Audio/Sink",
                    "audio.channels": 4, "audio.position": ["FL", "FR", "RL", "RR"],
                    "adapter.auto-port-config": {"mode": "dsp", "position": "preserve"},
                    "debug.wav-path": str(output)}},
            ],
        }
        config = private.root / "pipewire.conf"
        config.write_text(json.dumps(configuration, indent=2))
        private.launch(["pipewire", "-c", str(config)], "pipewire.log")
        private.wait_for(lambda: (private.runtime / "t2-test").exists())
        private.launch(["wireplumber", "-p", "t2-test"], "wireplumber.log")
        installed = installer.root / "home/.config/pipewire/imac-speaker-eq.conf"
        private.launch(["pipewire", "-c", str(installed)], "eq.log")
        sink = eq.TUNED_SINK.split()[1]
        private.wait_for(lambda: any(item.get("info", {}).get("props", {}).get("node.name") == sink
                                    for item in private.snapshot()))
        # Broadband-enough input to exercise both halves of the crossover.
        samples = array.array("f")
        for i in range(48000):
            sample = .02 * sum(math.sin(2 * math.pi * hz * i / 48000)
                               for hz in (200, 1000, 6000))
            samples.extend((sample, sample * .5))
        source = private.root / "input.raw"
        source.write_bytes(samples.tobytes())
        process = private.launch([
            "pw-cat", "-p", "--raw", "--rate=48000", "--channels=2",
            "--channel-map=FL,FR", "--format=f32", "--latency=20ms",
            "--target=" + sink, str(source)], "playback.log")
        try:
            self.assertEqual(process.wait(timeout=10), 0)
        except subprocess.TimeoutExpired:
            self.fail("DSP playback timed out: " + (private.root / "eq.log").read_text())
        # Every DSP output must link to the intended four-channel device.
        graph = private.snapshot()
        nodes = {item.get("info", {}).get("props", {}).get("node.name"): item["id"]
                 for item in graph if item.get("type", "").endswith(":Node")}
        links = [item["info"] for item in graph if item.get("type", "").endswith(":Link")
                 and item["info"]["output-node-id"] == nodes["omarchy_speaker_tuning_imac5k_output"]]
        self.assertEqual(len(links), 4)
        self.assertTrue(all(link["input-node-id"] == nodes[eq.SPEAKER_TARGET] for link in links))
        private.stop()  # Flush the WAV header before reading the virtual output.
        raw = output.read_bytes()
        offset, data = 12, None
        while offset + 8 <= len(raw):
            tag, size = struct.unpack_from("<4sI", raw, offset)
            chunk = raw[offset + 8:offset + 8 + size]
            if tag == b"fmt ":
                encoding, channels, rate, _, _, bits = struct.unpack_from("<HHIIHH", chunk)
                self.assertEqual((encoding, channels, rate, bits), (3, 4, 48000, 32))
            if tag == b"data":
                data = array.array("f")
                data.frombytes(chunk)
            offset += 8 + size + size % 2
        self.assertIsNotNone(data)
        self.assertGreater(len(data), 48000 * 4 // 2)
        for channel in range(4):
            values = data[channel::4]
            self.assertTrue(all(math.isfinite(value) for value in values))
            self.assertGreater(max(map(abs, values)), .00001, f"silent channel {channel}")


if __name__ == "__main__":
    unittest.main()
