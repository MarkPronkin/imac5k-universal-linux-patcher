#!/usr/bin/env python3
"""Configure the internal panel through KScreen, without editing KWin's live files."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys


def doctor(*args):
    return subprocess.check_output(
        ["kscreen-doctor", *args], text=True, stderr=subprocess.PIPE,
        env={**os.environ, "LC_ALL": "C"}, timeout=15,
    )


def panel(config):
    panels = [o for o in config["outputs"] if o["name"].startswith("eDP-")
              and o.get("connected") and o.get("enabled", True)]
    if len(panels) != 1:
        raise ValueError("Expected one active internal eDP panel; check KDE Display Configuration.")
    return panels[0]


def block(text, output_id):
    text = re.sub(r"\x1b\[[0-9;]*m", "", text)
    for part in re.split(r"(?m)(?=^Output:)", text):
        if re.match(rf"Output:\s*{output_id}\s", part):
            return part
    return ""


def profile(text, output_id):
    # KScreen JSON omits colorProfileSource; the text output exposes it.
    match = re.search(r"(?m)^\s*Color profile source:\s*(sRGB|ICC|EDID)\s*$",
                      block(text, output_id))
    if match:
        return match[1]
    raise ValueError("KScreen does not expose colour profile selection. Use Plasma Wayland.")


# KWin keys every per-output setting to the panel's identity -- an EDID hash --
# and not to the connector name. The 5K stitch rewrites the panel's EDID, so
# eDP-1 comes back after that reboot as a *different* output carrying KDE's
# defaults, and a profile applied before the stitch stays behind on the old
# identity. Recording the identity keeps --remove from restoring one panel's
# saved setting onto another. Older state files have no identity; they are
# taken at face value rather than discarded.
def identity(text, output_id):
    # The header line alone: \s would otherwise run past it into the block.
    header = block(text, output_id).split("\n", 1)[0]
    match = re.match(r"Output:\s*\S+\s+\S+\s+(\S+)", header)
    return match[1] if match else ""


def is_5k(output):
    return any(str(m["id"]) == str(output["currentModeId"])
               and m["size"] == {"width": 5120, "height": 2880}
               for m in output["modes"])


# A state file that cannot be parsed must not wedge --apply: it is replaced.
def read_state(path):
    try:
        saved = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return saved if isinstance(saved, dict) and "output" in saved and "profile" in saved else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    for action in ("status", "apply", "remove", "5k-active"):
        group.add_argument("--" + action, action="store_true")
    args = parser.parse_args()
    state = Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state"))) / "imac-patcher/kde-color.json"
    try:
        if os.environ.get("XDG_SESSION_TYPE") != "wayland" or not os.environ.get("WAYLAND_DISPLAY"):
            raise ValueError("Run this from a terminal in your Plasma Wayland session.")
        output = panel(json.loads(doctor("--json")))
        if getattr(args, "5k_active"):
            return 0 if is_5k(output) else 1
        outputs = doctor("--outputs")
        current = profile(outputs, output["id"])
        panel_id = identity(outputs, output["id"])
        if args.status:
            print("applied" if current == "EDID" else "not-applied")
            return 0
        saved = read_state(state)
        if args.apply:
            if current == "EDID":
                return 0
            # Re-save when the panel is not the one the stored setting came
            # from, so --remove restores this panel's own previous profile.
            if saved is None or saved.get("uuid", panel_id) != panel_id:
                state.parent.mkdir(parents=True, exist_ok=True)
                state.write_text(json.dumps(
                    {"output": output["name"], "uuid": panel_id, "profile": current}) + "\n")
            target = "EDID"
        else:
            if saved is None:
                print("No saved colour setting; nothing to restore.")
                return 0
            if saved["output"] != output["name"]:
                raise ValueError("Saved colour setting belongs to a different connector.")
            if saved.get("uuid", panel_id) != panel_id:
                # The stitch reboot replaced the panel this setting was taken
                # from. KDE gave the panel now present its own defaults, so
                # there is nothing of ours left on it to undo.
                state.unlink()
                print(f"{output['name']}: the saved colour setting belongs to the pre-5K panel; "
                      "discarded it and left this panel at its own setting.")
                return 0
            target = saved["profile"]
            if target not in ("sRGB", "ICC", "EDID"):
                raise ValueError("Invalid saved colour profile selection.")
        doctor(f"output.{output['id']}.colorProfileSource.{target}")
        if profile(doctor("--outputs"), output["id"]) != target:
            raise ValueError("KScreen did not apply the colour profile; check Display Configuration.")
        if args.remove:
            state.unlink()
        print(f"{output['name']}: colour profile source set to {target}.")
        return 0
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        if args.status:
            print("n/a")
            return 0
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
