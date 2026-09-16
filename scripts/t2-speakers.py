#!/usr/bin/env python3
"""Manage the iMac Pro T2 speaker rule and verify its live PipeWire node."""
import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time


RULE_NAME = "51-imacpro-t2-speakers.conf"
ANY_CONTENT = object()
POSITIONS = ["FL", "FR", "RL", "RR"]
INPUT_POSITIONS = ["FL", "FR"]
NODE_NAME = re.compile(r"alsa_output\.[A-Za-z0-9_.-]+\.pro-output-0")
RULE = """# Managed by imac-patcher: iMac Pro T2 speakers, revision 2.
# Restrict this rule to the four-channel Apple T2 speaker PCM.
monitor.alsa.rules = [
  {
    matches = [
      {
        alsa.card_name = "Apple T2 Audio"
        api.alsa.pcm.stream = "playback"
        node.name = "~^alsa_output[.].+[.]pro-output-0$"
        audio.channels = 4
      }
    ]
    actions = {
      update-props = {
        audio.position = [ FL FR RL RR ]
        # Expose stereo inputs so the device adapter does the 2 -> 4 mix.
        # Otherwise clients send four channels with the second pair silent.
        item.features.no-format = true
        node.param.PortConfig = {
          direction = Input
          mode = dsp
          monitor = true
          format = {
            mediaType = audio
            mediaSubtype = raw
            format = F32P
            channels = 2
            position = [ FL FR ]
          }
        }
        channelmix.disable = false
        channelmix.upmix = true
        channelmix.upmix-method = simple
        node.description = "iMac Pro Speakers"
        imac-patcher.t2-speakers = "2"
      }
    }
  }
]
"""
# Only the exact former generated file is eligible for automatic migration.
LEGACY_SHA256 = "8a189e3e9123dd352e2fa62efe97b7ef8559e4b25bd82bc77b7c4f658e2ea441"


class Error(Exception):
    pass


def command(*args, timeout=15):
    try:
        result = subprocess.run(args, text=True, capture_output=True, timeout=timeout,
                                env={**os.environ, "LC_ALL": "C"})
    except (OSError, subprocess.TimeoutExpired) as error:
        raise Error(f"Could not run {args[0]}: {error}") from error
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
        raise Error(f"{' '.join(args)}: {detail}")
    return result.stdout


def read_file(path):
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(metadata.st_mode):
        raise Error(f"Refusing a symlink or non-regular file: {path}")
    try:
        return path.read_bytes().decode("utf-8")
    except UnicodeError as error:
        raise Error(f"Not a UTF-8 configuration file; preserving {path}.") from error


def atomic_write(path, text, mode=0o600, expected=ANY_CONTENT):
    # A failure before replace leaves the destination intact.
    read_file(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            os.fchmod(stream.fileno(), mode)
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        if expected is not ANY_CONTENT and read_file(path) != expected:
            raise Error(f"Configuration changed during the operation; preserving {path}.")
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def owned_rule(text):
    return text is None or text == RULE or hashlib.sha256(text.encode()).hexdigest() == LEGACY_SHA256


def positions(value):
    if isinstance(value, list):
        return value
    if isinstance(value, str) and re.fullmatch(r'[\[\]\s,"A-Z0-9]+', value):
        return re.findall(r"[A-Z][A-Z0-9]*", value)
    return []


def speaker_node(graph):
    if not isinstance(graph, list):
        raise Error("pw-dump did not return a list of PipeWire objects.")
    candidates = []
    for obj in graph:
        if not isinstance(obj, dict):
            raise Error("Malformed PipeWire object.")
        if obj.get("type") != "PipeWire:Interface:Node":
            continue
        info = obj.get("info") or {}
        props = info.get("props") if isinstance(info, dict) else None
        if not isinstance(props, dict):
            raise Error("Missing PipeWire node properties.")
        name = props.get("node.name")
        if (props.get("media.class") == "Audio/Sink"
                and props.get("alsa.card_name") == "Apple T2 Audio"
                and props.get("api.alsa.pcm.stream") == "playback"
                and isinstance(name, str) and NODE_NAME.fullmatch(name)):
            candidates.append(obj)
    if len(candidates) != 1:
        raise Error("Expected one Apple T2 Audio Pro Audio speaker output (pro-output-0); "
                    "check the T2 driver and select the Pro Audio profile in Sound settings.")
    node = candidates[0]
    if str(node["info"]["props"].get("audio.channels")) != "4":
        raise Error("The T2 speaker output does not expose exactly four channels; leaving it unchanged.")
    if not isinstance(node.get("id"), int) or isinstance(node["id"], bool):
        raise Error("Missing PipeWire node ID.")
    return node


def mapped(graph, node):
    if node["info"].get("state") == "error":
        return False
    props = node["info"]["props"]
    if not (positions(props.get("audio.position")) == POSITIONS
            and str(props.get("imac-patcher.t2-speakers")) == "2"
            and str(props.get("item.features.no-format")).lower() == "true"
            and str(props.get("channelmix.disable")).lower() == "false"
            and str(props.get("channelmix.upmix")).lower() == "true"
            and props.get("channelmix.upmix-method") == "simple"):
        return False
    # Node properties are startup requests. Verify the actual adapter setup
    # and mixer parameters too, including changes made by another client.
    params = node["info"].get("params")
    if not isinstance(params, dict):
        return False
    formats = params.get("EnumFormat")
    if not isinstance(formats, list) or not any(
            isinstance(fmt, dict) and fmt.get("mediaType") == "audio"
            and fmt.get("mediaSubtype") == "raw" and fmt.get("channels") == 4
            and fmt.get("position") == POSITIONS for fmt in formats):
        return False
    # ALSA can close its active format while idle. When open, it must retain
    # the four hardware channels even though applications see stereo ports.
    active_formats = params.get("Format", [])
    if not isinstance(active_formats, list) or any(
            not isinstance(fmt, dict) or fmt.get("channels") != 4
            or fmt.get("position") != POSITIONS for fmt in active_formats):
        return False
    configs = params.get("PortConfig")
    if not isinstance(configs, list) or len(configs) != 1:
        return False
    config = configs[0]
    if not isinstance(config, dict):
        return False
    fmt = config.get("format")
    if (config.get("direction") != "Input" or config.get("mode") != "dsp"
            or not isinstance(fmt, dict) or fmt.get("channels") != 2
            or fmt.get("position") != INPUT_POSITIONS):
        return False
    mixer_props = params.get("Props")
    if not isinstance(mixer_props, list):
        return False
    mixer = {}
    for item in mixer_props:
        if not isinstance(item, dict):
            return False
        pairs = item.get("params", [])
        if not isinstance(pairs, list) or len(pairs) % 2:
            return False
        for key, value in zip(pairs[::2], pairs[1::2]):
            if not isinstance(key, str):
                return False
            mixer[key] = value
    if (mixer.get("channelmix.disable") is not False
            or mixer.get("channelmix.upmix") is not True
            or mixer.get("channelmix.upmix-method") != "simple"):
        return False
    # Check the actual input ports, not just requested properties.
    channels = {}
    for obj in graph:
        if obj.get("type") != "PipeWire:Interface:Port":
            continue
        info = obj.get("info") or {}
        if not isinstance(info, dict):
            raise Error("Malformed PipeWire port information.")
        port = info.get("props") or {}
        if not isinstance(port, dict):
            raise Error("Malformed PipeWire port properties.")
        if str(port.get("node.id")) != str(node["id"]) or info.get("direction") != "input":
            continue
        index = str(port.get("port.id"))
        if index in channels:
            return False
        channels[index] = port.get("audio.channel")
    return channels == {str(i): channel for i, channel in enumerate(INPUT_POSITIONS)}


def graph_snapshot():
    try:
        graph = json.loads(command("pw-dump", timeout=3))
    except ValueError as error:
        raise Error("Invalid JSON from pw-dump.") from error
    return graph, speaker_node(graph)


def xdg_path(variable, default):
    path = Path(os.environ.get(variable) or default)
    if not path.is_absolute():
        raise Error(f"{variable} must be an absolute path.")
    return path


class SpeakerFix:
    def __init__(self, config_home=None, state_home=None):
        config_home = config_home or xdg_path("XDG_CONFIG_HOME", str(Path.home() / ".config"))
        state_home = state_home or xdg_path("XDG_STATE_HOME", str(Path.home() / ".local/state"))
        self.rule = config_home / "wireplumber/wireplumber.conf.d" / RULE_NAME
        self.state = state_home / "imac-patcher/t2-speakers-pending.json"
        self.lock = state_home / "imac-patcher/t2-speakers.lock"

    def pending(self):
        text = read_file(self.state)
        if text is None:
            return None
        try:
            data = json.loads(text)
        except ValueError as error:
            raise Error(f"Invalid recovery record; preserve it for manual recovery: {self.state}") from error
        if (not isinstance(data, dict) or data.get("version") != 1
                or data.get("config") != str(self.rule.absolute())
                or data.get("operation") not in ("apply", "remove")):
            raise Error(f"Recovery record does not match this configuration: {self.state}")
        return data

    def record(self, operation, **extra):
        data = {"version": 1, "config": str(self.rule.absolute()), "operation": operation, **extra}
        atomic_write(self.state, json.dumps(data) + "\n")

    @contextmanager
    def locked(self):
        self.lock.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.lock, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise Error("Another T2 speaker operation is running.") from error
            yield
        finally:
            os.close(fd)

    def status(self):
        try:
            text = read_file(self.rule)
            pending = self.pending()
            if text is None and pending is None:
                return "not-applied"
            if text != RULE or pending is not None:
                return "partial"
            graph, node = graph_snapshot()
            return "applied" if mapped(graph, node) else "partial"
        except (Error, OSError, ValueError) as error:
            # Keep removal accessible when audio is down or recovery is pending.
            print(f"t2speakers: {error}", file=sys.stderr)
            return "partial"

    def check_rule(self):
        text = read_file(self.rule)
        if not owned_rule(text):
            raise Error(f"Existing rule was created or edited by the user; preserving {self.rule}. "
                        "Move it aside before applying or removing this fix.")
        return text

    def preflight(self):
        for tool in ("pw-dump", "wireplumber", "systemctl"):
            if not shutil.which(tool):
                raise Error(f"{tool} is required for the T2 speaker fix.")
        if os.environ.get("WIREPLUMBER_CONFIG_DIR"):
            raise Error("WIREPLUMBER_CONFIG_DIR overrides normal config lookup; use the standard "
                        "WirePlumber configuration directories for this module.")
        version = command("wireplumber", "--version")
        match = re.search(r"(?:lib)?wireplumber\s+(\d+)\.(\d+)(?:\.\d+)?", version, re.I)
        if not match or tuple(map(int, match.groups())) < (0, 5):
            raise Error("WirePlumber 0.5 or newer is required for this configuration format.")
        command("systemctl", "--user", "is-active", "--quiet", "wireplumber.service")

    def restart(self):
        # Rules belong to WirePlumber; restarting PipeWire/PulseAudio as well
        # needlessly disconnects clients and can hide session-manager failure.
        command("systemctl", "--user", "restart", "wireplumber.service")

    def wait_mapped(self):
        last = "The live T2 channel map or upmix properties did not take effect."
        deadline = time.monotonic() + 10
        while True:
            try:
                graph, node = graph_snapshot()
                if mapped(graph, node):
                    return node["info"]["props"]["node.name"]
            except Error as error:
                last = str(error)
            if time.monotonic() >= deadline:
                raise Error(last)
            time.sleep(0.25)

    def apply(self):
        with self.locked():
            previous = self.check_rule()
            if self.pending() is not None:
                raise Error("An earlier T2 operation is incomplete; run --remove t2speakers "
                            "to finish recovery before applying again.")
            self.preflight()
            graph, node = graph_snapshot()  # no rule changes or restart without matching hardware
            if previous == RULE and mapped(graph, node):
                return "iMac Pro speaker map is already applied."
            previous_mode = self.rule.stat().st_mode & 0o777 if previous is not None else 0o644
            print("Turn the volume down first: enabling four speaker channels can increase loudness.",
                  file=sys.stderr)
            self.record("apply", previous=previous, previous_mode=previous_mode)
            try:
                atomic_write(self.rule, RULE, previous_mode, expected=previous)
                self.restart()
                name = self.wait_mapped()
                if self.check_rule() != RULE:
                    raise Error("The speaker rule changed while it was being applied.")
                self.state.unlink()
            except (Error, OSError, KeyboardInterrupt) as original:
                try:
                    current = self.check_rule()  # preserve concurrent user edits
                    if current != RULE and current != previous:
                        raise Error("The speaker rule changed during apply; preserving that change.")
                    if current == RULE:
                        if previous is None:
                            self.rule.unlink()
                        else:
                            atomic_write(self.rule, previous, previous_mode, expected=RULE)
                    self.restart()
                    self.state.unlink()
                except (Error, OSError, KeyboardInterrupt) as recovery:
                    raise Error(f"Apply failed: {original}. Recovery is incomplete: {recovery}. "
                                "Run --remove t2speakers to retry; the recovery record is retained.") from original
                raise Error(f"Apply failed and the previous rule was restored: {original}") from original
            return f"Mapped stereo to {name}'s FL FR RL RR speaker channels with simple upmix."

    def remove(self):
        with self.locked():
            previous = self.check_rule()
            pending = self.pending()
            if previous is None and pending is None:
                return "No T2 speaker rule to remove."
            self.record("remove")
            if self.check_rule() != previous:
                raise Error("The speaker rule changed during removal; preserving that change.")
            if previous is not None:
                self.rule.unlink()
            # An inactive service will read the removal at its next start.
            # A failed service may have rejected the rule; restart it to recover.
            try:
                active = command("systemctl", "--user", "show", "--property=ActiveState",
                                 "--value", "wireplumber.service").strip()
                if active not in ("active", "inactive", "failed", "activating", "deactivating", "reloading"):
                    raise Error("Could not determine WirePlumber's state.")
                if active != "inactive":
                    self.restart()
                if read_file(self.rule) is not None:
                    raise Error("A new rule appeared during removal; preserving it.")
                self.state.unlink()
            except (Error, OSError, KeyboardInterrupt) as error:
                raise Error(f"The rule is removed, but reloading is incomplete: {error}. "
                            "Run --remove t2speakers again; the recovery record is retained.") from error
            return "iMac Pro speaker map removed."


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("status", "apply", "remove"))
    parser.add_argument("--model", required=True)
    args = parser.parse_args()
    if args.model != "iMacPro1,1":
        if args.action == "status":
            print("n/a")
            return 0
        print("The T2 speaker fix supports only iMacPro1,1.", file=sys.stderr)
        return 1
    try:
        if args.action != "status" and os.geteuid() == 0:
            raise Error("Run the T2 speaker fix as your desktop user, without sudo.")
        fix = SpeakerFix()
        print(getattr(fix, args.action)())
        return 0
    except (Error, OSError, ValueError, KeyboardInterrupt) as error:
        print(f"t2speakers: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
