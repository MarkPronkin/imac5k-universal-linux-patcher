"""T2 speaker selection, live verification, ownership and failure recovery.

PipeWire/WirePlumber/systemctl are simulated. Nothing touches host audio.
"""
import copy
import importlib.util
import itertools
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("t2_speakers", ROOT / "scripts/t2-speakers.py")
t2 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(t2)
NODE = "alsa_output.pci-0000_02_00.3.pro-output-0"
LEGACY = """# Written by imac-patcher; removed by @TICK@imac-patcher --remove t2speakers@TICK@.
#
# iMacPro1,1: only 2 of the 4 T2 speaker drivers play without an explicit
# channel map. Position all four and upmix stereo onto the second pair.
# Matched by suffix: the T2's PCI address differs between machines.
monitor.alsa.rules = [
  {
    matches = [ { node.name = "~alsa_output.*pro-output-0" } ]
    actions = {
      update-props = {
        audio.position = [ FL FR RL RR ]
        channelmix.upmix = true
        channelmix.upmix-method = simple
        node.description = "iMac Pro Speakers"
      }
    }
  }
]
""".replace("@TICK@", chr(96))


def graph(applied=False, node_id=51, name=NODE):
    channels = t2.POSITIONS if applied else ["AUX0", "AUX1", "AUX2", "AUX3"]
    inputs = t2.INPUT_POSITIONS if applied else channels
    props = {
        "node.name": name, "media.class": "Audio/Sink",
        "alsa.card_name": "Apple T2 Audio", "alsa.driver_name": "apple_bce",
        "api.alsa.pcm.stream": "playback",
        "audio.channels": 4, "audio.position": "[ " + " ".join(channels) + " ]",
    }
    if applied:
        props.update({"imac-patcher.t2-speakers": "2", "item.features.no-format": True,
                      "channelmix.disable": False, "channelmix.upmix": True,
                      "channelmix.upmix-method": "simple"})
    params = {
        "EnumFormat": [{"mediaType": "audio", "mediaSubtype": "raw",
                        "channels": 4, "position": channels}],
        "Format": [],
        "PortConfig": [{"direction": "Input", "mode": "dsp", "format": {
            "channels": len(inputs), "position": inputs}}],
        "Props": [{"params": ["channelmix.disable", False, "channelmix.upmix", True,
                              "channelmix.upmix-method", "simple" if applied else "none"]}],
    }
    result = [{"id": node_id, "type": "PipeWire:Interface:Node", "info": {"props": props, "params": params}}]
    for i, channel in enumerate(inputs):
        result.append({"id": node_id + i + 1, "type": "PipeWire:Interface:Port",
                       "info": {"direction": "input", "props": {
                           "node.id": node_id, "port.id": i, "audio.channel": channel}}})
    return result


class SelectionTests(unittest.TestCase):
    def test_different_pci_addresses_and_string_properties(self):
        data = graph(True, name="alsa_output.pci-0000_03_00.3.pro-output-0")
        data[0]["info"]["props"]["audio.channels"] = "4"
        data[0]["info"]["props"]["channelmix.upmix"] = "true"
        self.assertTrue(t2.mapped(data, t2.speaker_node(data)))

    def test_external_pro_audio_sink_is_never_selected(self):
        for card in ("USB Audio", "HDA Intel PCH", "", None):
            with self.subTest(card=card):
                external = graph(True, node_id=100, name="alsa_output.usb-device.pro-output-0")
                external[0]["info"]["props"]["alsa.card_name"] = card
                self.assertEqual(t2.speaker_node(external + graph(True))["id"], 51)
                with self.assertRaises(t2.Error):
                    t2.speaker_node(external)

    def test_card_identity_does_not_depend_on_kernel_module_or_alsa_id(self):
        data = graph(True)
        data[0]["info"]["props"].pop("alsa.driver_name")
        data[0]["info"]["props"]["alsa.id"] = "custom-card-id"
        self.assertTrue(t2.mapped(data, t2.speaker_node(data)))

    def test_ambiguous_t2_sinks_are_rejected(self):
        with self.assertRaises(t2.Error):
            t2.speaker_node(graph() + graph(node_id=100))

    def test_headphones_loopback_capture_and_name_prefixes_are_rejected(self):
        for change in ({"node.name": NODE + ".other"},
                       {"node.name": NODE.replace("output-0", "output-4")},
                       {"node.name": NODE.replace("output-0", "output-100")},
                       {"node.name": NODE.replace("pro-output-0", "HiFi__Speaker__sink")},
                       {"media.class": "Audio/Source"}, {"api.alsa.pcm.stream": "capture"}):
            with self.subTest(change=change):
                data = graph()
                data[0]["info"]["props"].update(change)
                with self.assertRaises(t2.Error):
                    t2.speaker_node(data)

    def test_wrong_or_missing_channel_counts_are_rejected(self):
        for count in (None, 0, 2, 6, 8, "garbage", True, 4.0):
            with self.subTest(count=count):
                data = graph()
                data[0]["info"]["props"]["audio.channels"] = count
                with self.assertRaises(t2.Error):
                    t2.speaker_node(data)

    def test_missing_channelmap_upmix_or_revision_is_not_applied(self):
        for key, value in (("audio.position", "[ AUX0 AUX1 AUX2 AUX3 ]"),
                           ("audio.position", None), ("channelmix.upmix", False),
                           ("channelmix.upmix-method", "psd"),
                           ("imac-patcher.t2-speakers", None)):
            with self.subTest(key=key):
                data = graph(True)
                data[0]["info"]["props"][key] = value
                self.assertFalse(t2.mapped(data, t2.speaker_node(data)))

    def test_requested_properties_without_actual_ports_are_not_applied(self):
        data = graph(True)[:1]
        self.assertFalse(t2.mapped(data, t2.speaker_node(data)))

    def test_four_channel_input_config_without_device_conversion_is_not_applied(self):
        data = graph(True)
        data[0]["info"]["params"]["PortConfig"][0]["format"] = {
            "channels": 4, "position": t2.POSITIONS}
        self.assertFalse(t2.mapped(data, t2.speaker_node(data)))

    def test_runtime_mixer_override_is_not_hidden_by_startup_properties(self):
        for key, value in (("channelmix.disable", True), ("channelmix.upmix", False),
                           ("channelmix.upmix-method", "none")):
            with self.subTest(key=key):
                data = graph(True)
                params = data[0]["info"]["params"]["Props"][0]["params"]
                params[params.index(key) + 1] = value
                self.assertFalse(t2.mapped(data, t2.speaker_node(data)))

    def test_active_hardware_format_must_retain_all_four_channels(self):
        for count, positions in ((2, ["FL", "FR"]), (4, ["AUX0", "AUX1", "AUX2", "AUX3"]),
                                 (4, t2.POSITIONS)):
            with self.subTest(count=count, positions=positions):
                data = graph(True)
                data[0]["info"]["params"]["Format"] = [{"channels": count, "position": positions}]
                self.assertEqual(t2.mapped(data, t2.speaker_node(data)), positions == t2.POSITIONS)

    def test_failed_device_or_wrong_advertised_hardware_format_is_not_applied(self):
        data = graph(True)
        data[0]["info"]["state"] = "error"
        self.assertFalse(t2.mapped(data, t2.speaker_node(data)))
        data[0]["info"]["state"] = "suspended"
        self.assertTrue(t2.mapped(data, t2.speaker_node(data)))
        data[0]["info"]["params"]["EnumFormat"][0]["channels"] = 2
        self.assertFalse(t2.mapped(data, t2.speaker_node(data)))

    def test_missing_or_malformed_runtime_parameters_are_not_applied(self):
        for params in (None, [], {}, {"PortConfig": [42]},
                       {"PortConfig": [{"format": None}]},
                       {"PortConfig": graph(True)[0]["info"]["params"]["PortConfig"],
                        "Props": [{"params": ["unpaired"]}]}):
            with self.subTest(params=params):
                data = graph(True)
                data[0]["info"]["params"] = params
                self.assertFalse(t2.mapped(data, t2.speaker_node(data)))

    def test_missing_duplicate_or_reordered_ports_are_not_applied(self):
        for variant in ("missing", "duplicate", "wrong_map", "foreign_node", "monitor"):
            with self.subTest(variant=variant):
                data = graph(True)
                if variant == "missing":
                    data.pop()
                elif variant == "duplicate":
                    data.append(copy.deepcopy(data[-1]))
                elif variant == "wrong_map":
                    data[-1]["info"]["props"]["audio.channel"] = "RL"
                elif variant == "foreign_node":
                    data[-1]["info"]["props"]["node.id"] = 999
                else:
                    data[-1]["info"]["direction"] = "output"
                self.assertFalse(t2.mapped(data, t2.speaker_node(data)))

    def test_monitor_ports_do_not_invalidate_the_input_map(self):
        data = graph(True)
        extra = copy.deepcopy(data[-1])
        extra["info"]["direction"] = "output"
        data.append(extra)
        self.assertTrue(t2.mapped(data, t2.speaker_node(data)))

    def test_malformed_graph_and_node_properties_are_rejected(self):
        for data in ({}, None, [42], [{"type": "PipeWire:Interface:Node", "info": []}]):
            with self.subTest(data=data), self.assertRaises(t2.Error):
                t2.speaker_node(data)

    def test_malformed_port_properties_are_rejected(self):
        data = graph(True)
        data[-1]["info"]["props"] = ["wrong"]
        with self.assertRaises(t2.Error):
            t2.mapped(data, t2.speaker_node(data))


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.fix = t2.SpeakerFix(self.root / "custom-config", self.root / "custom-state")
        self.data = graph()
        self.calls = []
        self.version = "wireplumber\nCompiled with libwireplumber 0.5.17\nLinked with libwireplumber 0.5.17\n"
        self.active = "active"
        self.missing = set()
        self.fail_restart = []
        self.restart_effective = True
        self.query_failure = None
        self.on_restart = None
        self.addCleanup(patch.stopall)
        patch.object(t2, "command", side_effect=self.command).start()
        patch.object(t2.shutil, "which", side_effect=lambda tool: None if tool in self.missing else "/fake/" + tool).start()
        patch.object(t2.time, "sleep").start()
        patch.object(t2.time, "monotonic", side_effect=itertools.count()).start()
        patch.dict(os.environ, {"WIREPLUMBER_CONFIG_DIR": ""}).start()

    def command(self, *args, timeout=15):
        self.calls.append(args)
        if args[0] in self.missing:
            raise t2.Error("missing " + args[0])
        if args == ("wireplumber", "--version"):
            return self.version
        if args[0] == "pw-dump":
            if self.query_failure:
                raise t2.Error(self.query_failure)
            return json.dumps(self.data)
        if args[0] == "systemctl":
            if args[2] == "is-active":
                if self.active != "active":
                    raise t2.Error("session manager is not active")
                return ""
            if args[2] == "show":
                return self.active + "\n"
            if args[2] == "restart":
                if self.fail_restart and self.fail_restart.pop(0):
                    raise t2.Error("restart failed")
                if self.on_restart:
                    self.on_restart()
                if self.restart_effective:
                    self.data = graph(t2.read_file(self.fix.rule) == t2.RULE, node_id=100,
                                      name=NODE.replace("02_00", "03_00"))
                return ""
        self.fail(f"Unexpected command: {args}")

    def install(self, text=t2.RULE):
        self.fix.rule.parent.mkdir(parents=True, exist_ok=True)
        self.fix.rule.write_text(text)

    def restarts(self):
        return [call for call in self.calls if "restart" in call]

    def test_fresh_status_is_read_only_and_needs_no_audio_tools(self):
        self.missing.update(("pw-dump", "wireplumber", "systemctl"))
        self.assertEqual(self.fix.status(), "not-applied")
        self.assertEqual(self.calls, [])
        self.assertFalse(self.fix.state.parent.exists())

    def test_apply_checks_identity_maps_live_ports_and_restarts_only_wireplumber(self):
        self.assertIn("FL FR RL RR", self.fix.apply())
        self.assertEqual(self.fix.rule.read_text(), t2.RULE)
        self.assertEqual(self.fix.status(), "applied")
        self.assertEqual(self.restarts(), [("systemctl", "--user", "restart", "wireplumber.service")])
        self.assertFalse(self.fix.state.exists())
        self.assertNotIn("set-volume", str(self.calls))
        self.assertNotIn("set-default", str(self.calls))

    def test_reapply_is_idempotent_without_restart_or_rewrite(self):
        self.fix.apply()
        before = self.fix.rule.stat().st_mtime_ns
        self.calls.clear()
        self.assertIn("already", self.fix.apply())
        self.assertEqual(self.restarts(), [])
        self.assertEqual(self.fix.rule.stat().st_mtime_ns, before)

    def test_applied_rule_with_stale_live_map_is_repaired(self):
        self.install()
        self.assertEqual(self.fix.status(), "partial")
        self.fix.apply()
        self.assertEqual(self.fix.status(), "applied")

    def test_legacy_rule_is_migrated_and_can_be_removed(self):
        self.assertTrue(t2.owned_rule(LEGACY))
        self.install(LEGACY)
        self.assertEqual(self.fix.status(), "partial")
        self.fix.apply()
        self.assertEqual(self.fix.rule.read_text(), t2.RULE)
        self.fix.remove()
        self.assertEqual(self.fix.status(), "not-applied")

    def test_no_target_is_refused_before_config_write_or_restart(self):
        self.data = []
        with self.assertRaisesRegex(t2.Error, "Expected one"):
            self.fix.apply()
        self.assertFalse(self.fix.rule.exists())
        self.assertFalse(self.fix.state.exists())
        self.assertEqual(self.restarts(), [])

    def test_missing_dependencies_leave_configuration_untouched(self):
        for tool in ("pw-dump", "wireplumber", "systemctl"):
            with self.subTest(tool=tool):
                self.missing = {tool}
                with self.assertRaisesRegex(t2.Error, tool):
                    self.fix.apply()
                self.assertFalse(self.fix.rule.exists())
                self.assertFalse(self.fix.state.exists())

    def test_old_or_unparseable_wireplumber_refused_before_write(self):
        for version in ("wireplumber 0.4.17", "not a version", ""):
            with self.subTest(version=version):
                self.version = version
                with self.assertRaisesRegex(t2.Error, "0.5"):
                    self.fix.apply()
                self.assertFalse(self.fix.rule.exists())

    def test_inactive_session_is_not_started_by_apply(self):
        self.active = "inactive"
        with self.assertRaises(t2.Error):
            self.fix.apply()
        self.assertFalse(self.fix.rule.exists())
        self.assertEqual(self.restarts(), [])

    def test_overridden_config_lookup_refused_before_write(self):
        with patch.dict(os.environ, {"WIREPLUMBER_CONFIG_DIR": "/somewhere"}):
            with self.assertRaisesRegex(t2.Error, "CONFIG_DIR"):
                self.fix.apply()
        self.assertFalse(self.fix.rule.exists())

    def test_existing_user_rule_and_modified_managed_rule_are_preserved(self):
        for text in ("# audio.position pro-output-0\n", t2.RULE + "# user edit\n", LEGACY + "\n"):
            with self.subTest(text=text):
                self.install(text)
                for operation in (self.fix.apply, self.fix.remove):
                    with self.assertRaisesRegex(t2.Error, "preserving"):
                        operation()
                    self.assertEqual(self.fix.rule.read_text(), text)
                self.assertEqual(self.fix.status(), "partial")
        self.assertEqual(self.restarts(), [])

    def test_symlink_and_directory_at_rule_path_are_preserved(self):
        self.fix.rule.parent.mkdir(parents=True)
        other = self.root / "other"
        other.write_text("user data")
        self.fix.rule.symlink_to(other)
        with self.assertRaisesRegex(t2.Error, "symlink"):
            self.fix.apply()
        with self.assertRaises(t2.Error):
            self.fix.remove()
        self.assertEqual(other.read_text(), "user data")
        self.assertTrue(self.fix.rule.is_symlink())
        self.fix.rule.unlink()
        self.fix.rule.mkdir()
        with self.assertRaises(t2.Error):
            self.fix.remove()

    def test_failed_reload_rolls_back_new_rule(self):
        self.fail_restart = [True, False]
        with self.assertRaisesRegex(t2.Error, "previous rule was restored"):
            self.fix.apply()
        self.assertFalse(self.fix.rule.exists())
        self.assertFalse(self.fix.state.exists())
        self.assertEqual(len(self.restarts()), 2)

    def test_successful_restart_with_wrong_live_map_is_failure_and_rollback(self):
        self.restart_effective = False
        with self.assertRaisesRegex(t2.Error, "did not take effect"):
            self.fix.apply()
        self.assertFalse(self.fix.rule.exists())
        self.assertFalse(self.fix.state.exists())

    def test_legacy_contents_and_mode_restored_when_apply_fails(self):
        self.install(LEGACY)
        self.fix.rule.chmod(0o640)
        self.restart_effective = False
        with self.assertRaises(t2.Error):
            self.fix.apply()
        self.assertEqual(self.fix.rule.read_text(), LEGACY)
        self.assertEqual(self.fix.rule.stat().st_mode & 0o777, 0o640)

    def test_failed_rollback_keeps_recovery_record_and_remove_can_retry(self):
        self.fail_restart = [True, True]
        with self.assertRaisesRegex(t2.Error, "Recovery is incomplete"):
            self.fix.apply()
        self.assertTrue(self.fix.state.exists())
        self.assertEqual(self.fix.status(), "partial")
        with self.assertRaisesRegex(t2.Error, "incomplete"):
            self.fix.apply()
        self.fix.remove()
        self.assertFalse(self.fix.state.exists())
        self.assertEqual(self.fix.status(), "not-applied")

    def test_concurrent_user_edit_is_preserved_during_failed_apply(self):
        self.restart_effective = False
        self.on_restart = lambda: self.fix.rule.write_text("user edit")
        with self.assertRaisesRegex(t2.Error, "Recovery is incomplete"):
            self.fix.apply()
        self.assertEqual(self.fix.rule.read_text(), "user edit")
        self.assertTrue(self.fix.state.exists())

    def test_concurrent_user_edit_is_not_reported_as_success_after_good_reload(self):
        def edit():
            self.fix.rule.write_text("user edit")
            self.data = graph(True)
        self.restart_effective = False
        self.on_restart = edit
        with self.assertRaisesRegex(t2.Error, "Recovery is incomplete"):
            self.fix.apply()
        self.assertEqual(self.fix.rule.read_text(), "user edit")
        self.assertTrue(self.fix.state.exists())

    def test_user_edit_during_preflight_is_not_overwritten(self):
        def change_during_preflight():
            self.install("user edit while checking audio")
        with patch.object(self.fix, "preflight", side_effect=change_during_preflight):
            with self.assertRaisesRegex(t2.Error, "Recovery is incomplete"):
                self.fix.apply()
        self.assertEqual(self.fix.rule.read_text(), "user edit while checking audio")
        self.assertEqual(self.restarts(), [])

    def test_user_deletion_during_failed_migration_is_not_undone(self):
        self.install(LEGACY)
        self.restart_effective = False
        self.on_restart = lambda: self.fix.rule.unlink()
        with self.assertRaisesRegex(t2.Error, "preserving that change"):
            self.fix.apply()
        self.assertFalse(self.fix.rule.exists())
        self.assertTrue(self.fix.state.exists())

    def test_stopped_audio_keeps_installed_module_removable(self):
        self.install()
        self.query_failure = "audio unavailable"
        self.assertEqual(self.fix.status(), "partial")
        self.active = "inactive"
        self.fix.remove()
        self.assertFalse(self.fix.rule.exists())
        self.assertEqual(self.restarts(), [])

    def test_remove_preserves_siblings_and_does_not_need_pulse_or_target_sink(self):
        self.install()
        sibling = self.fix.rule.parent / "50-user.conf"
        sibling.write_text("keep")
        self.data = []
        self.missing.update(("pw-dump", "wireplumber", "pactl"))
        self.fix.remove()
        self.assertEqual(sibling.read_text(), "keep")
        self.assertFalse(self.fix.rule.exists())
        self.assertFalse(self.fix.state.exists())
        self.assertEqual(len(self.restarts()), 1)

    def test_failed_removal_reload_is_retryable_after_rule_is_gone(self):
        self.install()
        self.fail_restart = [True]
        with self.assertRaises(t2.Error):
            self.fix.remove()
        self.assertFalse(self.fix.rule.exists())
        self.assertEqual(self.fix.status(), "partial")
        self.fix.remove()
        self.assertEqual(self.fix.status(), "not-applied")
        self.assertFalse(self.fix.state.exists())

    def test_remove_missing_rule_is_noop(self):
        self.fix.remove()
        self.assertEqual(self.calls, [])

    def test_user_edit_while_preparing_removal_is_preserved(self):
        self.install()
        record = self.fix.record
        def record_and_edit(*args, **kwargs):
            record(*args, **kwargs)
            self.fix.rule.write_text("new user rule")
        with patch.object(self.fix, "record", side_effect=record_and_edit):
            with self.assertRaisesRegex(t2.Error, "preserving"):
                self.fix.remove()
        self.assertEqual(self.fix.rule.read_text(), "new user rule")
        self.assertTrue(self.fix.state.exists())
        self.assertEqual(self.restarts(), [])

    def test_user_rule_created_during_removal_reload_is_preserved(self):
        self.install()
        self.on_restart = lambda: self.fix.rule.write_text("new user rule")
        with self.assertRaisesRegex(t2.Error, "preserving"):
            self.fix.remove()
        self.assertEqual(self.fix.rule.read_text(), "new user rule")
        self.assertTrue(self.fix.state.exists())

    def test_remove_unlink_failure_is_not_reported_as_success(self):
        self.install()
        unlink = Path.unlink
        def fail_rule(path, *args, **kwargs):
            if path == self.fix.rule:
                raise PermissionError("denied")
            return unlink(path, *args, **kwargs)
        with patch.object(Path, "unlink", fail_rule), self.assertRaises(PermissionError):
            self.fix.remove()
        self.assertEqual(self.fix.rule.read_text(), t2.RULE)
        self.assertTrue(self.fix.state.exists())
        self.assertEqual(self.restarts(), [])

    def test_unknown_service_state_keeps_removal_pending(self):
        self.install()
        self.active = ""
        with self.assertRaises(t2.Error):
            self.fix.remove()
        self.assertTrue(self.fix.state.exists())

    def test_corrupt_or_foreign_recovery_record_is_preserved(self):
        self.install()
        for content in ("{bad", "[]", '{"version": 1, "config": "/other", "operation": "remove"}'):
            with self.subTest(content=content):
                t2.atomic_write(self.fix.state, content)
                with self.assertRaises(t2.Error):
                    self.fix.remove()
                self.assertEqual(self.fix.state.read_text(), content)
                self.assertEqual(self.fix.rule.read_text(), t2.RULE)

    def test_parallel_operation_is_refused(self):
        with self.fix.locked(), self.assertRaisesRegex(t2.Error, "Another"):
            self.fix.apply()
        self.assertEqual(self.calls, [])
        self.assertFalse(self.fix.rule.exists())

    def test_xdg_paths_are_used(self):
        with patch.dict(os.environ, {"XDG_CONFIG_HOME": str(self.root / "cfg"),
                                     "XDG_STATE_HOME": str(self.root / "state")}):
            fix = t2.SpeakerFix()
        self.assertEqual(fix.rule, self.root / "cfg/wireplumber/wireplumber.conf.d" / t2.RULE_NAME)
        self.assertEqual(fix.state, self.root / "state/imac-patcher/t2-speakers-pending.json")

    def test_relative_xdg_path_is_refused(self):
        with patch.dict(os.environ, {"XDG_CONFIG_HOME": "relative"}), self.assertRaises(t2.Error):
            t2.SpeakerFix()


class FileAndCommandTests(unittest.TestCase):
    def test_invalid_utf8_and_altered_line_endings_are_not_owned(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rule.conf"
            path.write_bytes(b"\xff")
            with self.assertRaisesRegex(t2.Error, "preserving"):
                t2.read_file(path)
            self.assertEqual(path.read_bytes(), b"\xff")
            path.write_bytes(t2.RULE.replace("\n", "\r\n").encode())
            self.assertFalse(t2.owned_rule(t2.read_file(path)))

    def test_atomic_replace_failure_keeps_original_and_cleans_temporary_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rule.conf"
            path.write_text("original")
            with patch.object(t2.os, "replace", side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    t2.atomic_write(path, t2.RULE)
            self.assertEqual(path.read_text(), "original")
            self.assertEqual(list(Path(tmp).iterdir()), [path])

    def test_commands_use_c_locale_and_timeout_and_propagate_failures(self):
        with patch.object(t2.subprocess, "run") as run:
            run.return_value = subprocess.CompletedProcess(["pw-dump"], 1, "", "cannot connect")
            with self.assertRaisesRegex(t2.Error, "cannot connect"):
                t2.command("pw-dump", timeout=3)
            self.assertEqual(run.call_args.kwargs["env"]["LC_ALL"], "C")
            self.assertEqual(run.call_args.kwargs["timeout"], 3)
            run.side_effect = subprocess.TimeoutExpired("pw-dump", 3)
            with self.assertRaisesRegex(t2.Error, "Could not run"):
                t2.command("pw-dump", timeout=3)

    def test_invalid_graph_json_is_not_a_successful_probe(self):
        with patch.object(t2, "command", return_value="{bad"), self.assertRaises(t2.Error):
            t2.graph_snapshot()

    def test_cli_rejects_other_models_before_creating_any_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            for action in ("status", "apply", "remove"):
                result = subprocess.run(
                    ["python3", str(ROOT / "scripts/t2-speakers.py"), action, "--model", "iMac18,3"],
                    env={**os.environ, "HOME": tmp, "XDG_CONFIG_HOME": tmp, "XDG_STATE_HOME": tmp},
                    capture_output=True, text=True, timeout=5)
                self.assertEqual(result.returncode, 0 if action == "status" else 1)
            self.assertEqual(list(Path(tmp).iterdir()), [])


class WrapperTests(unittest.TestCase):
    def test_missing_python_does_not_make_an_imac_pro_inapplicable(self):
        source = (ROOT / "scripts/imac-patcher").read_text()
        start = source.index("# ═══════════════════════ module: t2speakers ")
        end = source.index("# ═══════════════════════ module: color ", start)
        script = '''
set -uo pipefail
product=iMacPro1,1
imac_t2speakers_supported() { return 0; }
warn() { printf '%s\\n' "$*" >&2; }
''' + source[start:end] + "\nmod_t2speakers_detect\nmod_t2speakers_apply\n"
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "wireplumber/wireplumber.conf.d" / t2.RULE_NAME
            pending = Path(tmp) / "imac-patcher/t2-speakers-pending.json"
            for existing, expected in ((None, "not-applied"), (config, "partial"), (pending, "partial")):
                with self.subTest(existing=existing):
                    config.unlink(missing_ok=True)
                    if existing:
                        existing.parent.mkdir(parents=True, exist_ok=True)
                        existing.write_text("preserve")
                    result = subprocess.run(
                        ["/usr/bin/bash", "-c", script], capture_output=True, text=True, timeout=3,
                        env={"PATH": "/nonexistent", "HOME": tmp,
                             "XDG_CONFIG_HOME": tmp, "XDG_STATE_HOME": tmp})
                    self.assertEqual(result.stdout.strip(), expected)
                    self.assertEqual(result.returncode, 1)
                    self.assertIn("python3 is required", result.stderr)
                    if existing:
                        self.assertEqual(existing.read_text(), "preserve")


if __name__ == "__main__":
    unittest.main()
