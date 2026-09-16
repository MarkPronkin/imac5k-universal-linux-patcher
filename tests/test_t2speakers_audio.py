"""Optional real PipeWire test: private sockets, null sink, no hardware monitors.

Set IMAC5K_REQUIRE_T2_AUDIO_TESTS=1 to fail instead of skipping when the local
PipeWire tools or Unix sockets are unavailable. No host audio service is used.
"""
import array
import json
import math
import os
from pathlib import Path
import re
import shutil
import socket
import struct
import subprocess
import tempfile
import time
import unittest

from test_t2speakers import NODE, t2


TOOLS = ("pipewire", "wireplumber", "pw-cat", "pw-dump", "pw-config")


class NativeAudioTests(unittest.TestCase):
    def setUp(self):
        required = os.environ.get("IMAC5K_REQUIRE_T2_AUDIO_TESTS") == "1"
        missing = [tool for tool in TOOLS if not shutil.which(tool)]
        if missing:
            message = "T2 virtual audio test needs: " + " ".join(missing)
            if required:
                self.fail(message)
            self.skipTest(message)
        version = subprocess.run(["wireplumber", "--version"], capture_output=True,
                                 text=True, timeout=5, check=True).stdout
        match = re.search(r"(?:lib)?wireplumber\s+(\d+)\.(\d+)", version, re.I)
        if not match or tuple(map(int, match.groups())) < (0, 5):
            message = "T2 virtual audio test needs WirePlumber 0.5 or newer"
            if required:
                self.fail(message)
            self.skipTest(message)
        tmp = tempfile.TemporaryDirectory(prefix="imac-t2-audio-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        try:
            with socket.socket(socket.AF_UNIX) as sock:
                sock.bind(str(self.root / "socket-probe"))
        except OSError as error:
            if required:
                self.fail(f"T2 virtual audio test cannot create a private socket: {error}")
            self.skipTest(f"Private Unix sockets unavailable: {error}")
        self.runtime = self.root / "runtime"
        self.runtime.mkdir(mode=0o700)
        config = self.root / "config"
        wp_dir = config / "wireplumber/wireplumber.conf.d"
        wp_dir.mkdir(parents=True)
        # Policy only: never load the ALSA, Bluetooth or camera monitors.
        (wp_dir / "99-audit.conf").write_text('''
wireplumber.profiles = {
  t2-test = { inherits = [ policy mixin.systemwide-session mixin.stateless ] }
}
''')
        self.env = {
            "PATH": os.environ.get("PATH", os.defpath), "LC_ALL": "C",
            "HOME": str(self.root), "XDG_CONFIG_HOME": str(config),
            "XDG_CONFIG_DIRS": str(self.root / "empty-config"),
            "XDG_STATE_HOME": str(self.root / "state"),
            "XDG_RUNTIME_DIR": str(self.runtime),
            "PIPEWIRE_RUNTIME_DIR": str(self.runtime), "PIPEWIRE_REMOTE": "t2-test",
            "DBUS_SESSION_BUS_ADDRESS": "unix:path=" + str(self.root / "no-session-bus"),
            "DBUS_SYSTEM_BUS_ADDRESS": "unix:path=" + str(self.root / "no-system-bus"),
        }
        self.processes = []
        self.streams = []
        self.addCleanup(self.stop)

    def stop(self):
        for process in reversed(self.processes):
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)
        for stream in self.streams:
            stream.close()

    def launch(self, args, log):
        stream = (self.root / log).open("wb")
        self.streams.append(stream)
        process = subprocess.Popen(args, env=self.env, stdout=stream, stderr=stream)
        self.processes.append(process)
        return process

    def start_audio(self, fixed):
        rule = self.root / "rule.conf"
        rule.write_text(t2.RULE)
        result = subprocess.run(
            ["pw-config", "-n", str(rule), "-N", "-r", "merge", "monitor.alsa.rules"],
            env=self.env, capture_output=True, text=True, timeout=5, check=True)
        rules = json.loads(result.stdout)
        props = {
            "factory.name": "support.null-audio-sink", "node.name": NODE,
            "media.class": "Audio/Sink", "audio.channels": 4,
            "alsa.card_name": "Apple T2 Audio", "api.alsa.pcm.stream": "playback",
            "debug.wav-path": str(self.root / "converted.wav"),
            **rules[0]["actions"]["update-props"],
        }
        if not fixed:
            # Reproduce the original bug: four ports and upmix on the sink,
            # but no device-side conversion of the ordinary stereo stream.
            props.pop("item.features.no-format")
            props.pop("node.param.PortConfig")
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
                {"factory": "adapter", "args": props},
            ],
        }
        config = self.root / "pipewire.conf"
        config.write_text(json.dumps(configuration, indent=2))
        self.launch(["pipewire", "-c", str(config)], "pipewire.log")
        self.wait_for(lambda: (self.runtime / "t2-test").exists())
        self.launch(["wireplumber", "-p", "t2-test"], "wireplumber.log")
        def configured():
            data = self.snapshot()
            node = t2.speaker_node(data)
            return t2.mapped(data, node) if fixed else node["info"]["n-input-ports"] == 4
        self.wait_for(configured)

    def wait_for(self, predicate):
        deadline = time.monotonic() + 8
        last = "not ready"
        while time.monotonic() < deadline:
            if any(process.poll() is not None for process in self.processes):
                break
            try:
                if predicate():
                    return
            except (t2.Error, subprocess.SubprocessError, ValueError) as error:
                last = str(error)
            time.sleep(.1)
        logs = "\n".join(path.read_text(errors="replace") for path in self.root.glob("*.log"))
        self.fail(f"Private audio graph failed to become ready: {last}\n{logs}")

    def snapshot(self):
        result = subprocess.run(["pw-dump"], env=self.env, capture_output=True,
                                text=True, timeout=2, check=True)
        return json.loads(result.stdout)

    def start_pulse(self):
        missing = [tool for tool in ("pipewire-pulse", "pacat") if not shutil.which(tool)]
        if missing:
            message = "PulseAudio path test needs: " + " ".join(missing)
            if os.environ.get("IMAC5K_REQUIRE_T2_AUDIO_TESTS") == "1":
                self.fail(message)
            self.skipTest(message)
        address = "unix:" + str(self.runtime / "pulse.sock")
        self.env["PULSE_SERVER"] = address
        self.env["PULSE_RUNTIME_PATH"] = str(self.runtime)
        configuration = {
            "context.spa-libs": {"audio.convert.*": "audioconvert/libspa-audioconvert",
                                 "support.*": "support/libspa-support"},
            "context.modules": [{"name": "libpipewire-module-" + name} for name in (
                "protocol-native", "client-node", "adapter", "metadata", "protocol-pulse")],
            "pulse.properties": {"server.address": [address]},
            "stream.properties": {"channelmix.upmix": False, "channelmix.upmix-method": "none"},
        }
        config = self.root / "pipewire-pulse.conf"
        config.write_text(json.dumps(configuration, indent=2))
        self.launch(["pipewire-pulse", "-c", str(config)], "pulse.log")
        self.wait_for(lambda: (self.runtime / "pulse.sock").exists())

    def render(self, channels=2, pulse=False):
        samples = array.array("f")
        for i in range(48000):
            left = .04 * math.sin(2 * math.pi * 440 * i / 48000)
            right = .08 * math.sin(2 * math.pi * 880 * i / 48000)
            samples.extend((left, right) if channels == 2 else (left,))
        input_file = self.root / "input.raw"
        input_file.write_bytes(samples.tobytes())
        if pulse:
            args = ["pacat", "--playback", "--raw", "--rate=48000", "--channels=2",
                    "--channel-map=front-left,front-right", "--format=float32le",
                    "--latency-msec=20", "--device=" + NODE, str(input_file)]
        else:
            args = ["pw-cat", "-p", "--raw", "--rate=48000", f"--channels={channels}",
                    "--channel-map=" + ("FL,FR" if channels == 2 else "MONO"),
                    "--format=f32", "--latency=20ms", "--target=" + NODE,
                    "-P", "{ channelmix.upmix=false channelmix.upmix-method=none }", str(input_file)]
        process = self.launch(args, "playback.log")
        self.assertEqual(process.wait(timeout=8), 0, (self.root / "playback.log").read_text())
        time.sleep(.1)
        self.stop()  # close the debug WAV and flush its RIFF length
        raw = (self.root / "converted.wav").read_bytes()
        offset = 12
        output = None
        while offset + 8 <= len(raw):
            key, size = struct.unpack_from("<4sI", raw, offset)
            chunk = raw[offset + 8:offset + 8 + size]
            if key == b"fmt ":
                encoding, count, rate, _, _, bits = struct.unpack_from("<HHIIHH", chunk)
                self.assertEqual((encoding, count, rate, bits), (3, 4, 48000, 32))
            if key == b"data":
                output = array.array("f")
                output.frombytes(chunk)
            offset += 8 + size + (size % 2)
        self.assertIsNotNone(output)
        self.assertGreater(len(output), 48000 * 4 // 2)
        return [output[channel::4] for channel in range(4)]

    def test_old_four_port_setup_leaves_second_pair_silent(self):
        self.start_audio(fixed=False)
        data = self.snapshot()
        self.assertFalse(t2.mapped(data, t2.speaker_node(data)))
        left, right, rear_left, rear_right = self.render()
        self.assertGreater(max(map(abs, left)), .03)
        self.assertGreater(max(map(abs, right)), .06)
        self.assertEqual(max(map(abs, rear_left)), 0)
        self.assertEqual(max(map(abs, rear_right)), 0)

    def test_stereo_reaches_all_four_channels_even_with_client_upmix_disabled(self):
        self.start_audio(fixed=True)
        self.assert_stereo_copies(self.render())

    def test_pulseaudio_stereo_reaches_all_four_channels(self):
        self.start_audio(fixed=True)
        self.start_pulse()
        self.assert_stereo_copies(self.render(pulse=True))

    def assert_stereo_copies(self, output):
        left, right, rear_left, rear_right = output
        self.assertGreater(max(map(abs, left)), .03)
        self.assertGreater(max(map(abs, right)), .06)
        # PipeWire simple upmix copies fronts to rears at its standard -3 dB.
        for front, rear in ((left, rear_left), (right, rear_right)):
            self.assertGreater(max(map(abs, rear)), .02)
            error = max(abs(a / math.sqrt(2) - b) for a, b in zip(front, rear))
            self.assertLess(error, 1e-6)

    def test_mono_is_mixed_to_both_pairs(self):
        self.start_audio(fixed=True)
        left, right, rear_left, rear_right = self.render(channels=1)
        for samples in (left, right, rear_left, rear_right):
            self.assertGreater(max(map(abs, samples)), .02)
        self.assertEqual(left, right)
        self.assertEqual(rear_left, rear_right)


if __name__ == "__main__":
    unittest.main()
