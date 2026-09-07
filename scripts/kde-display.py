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


def profile(text, output_id):
    # KScreen JSON omits colorProfileSource; the text output exposes it.
    text = re.sub(r"\x1b\[[0-9;]*m", "", text)
    for block in re.split(r"(?m)(?=^Output:)", text):
        if re.match(rf"Output:\s*{output_id}\s", block):
            match = re.search(r"(?m)^\s*Color profile source:\s*(sRGB|ICC|EDID)\s*$", block)
            if match:
                return match[1]
    raise ValueError("KScreen does not expose colour profile selection. Use Plasma Wayland.")


def is_5k(output):
    return any(str(m["id"]) == str(output["currentModeId"])
               and m["size"] == {"width": 5120, "height": 2880}
               for m in output["modes"])


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
        current = profile(doctor("--outputs"), output["id"])
        if args.status:
            print("applied" if current == "EDID" else "not-applied")
            return 0
        if args.apply:
            if current == "EDID":
                return 0
            if not state.exists():
                state.parent.mkdir(parents=True, exist_ok=True)
                state.write_text(json.dumps({"output": output["name"], "profile": current}) + "\n")
            target = "EDID"
        else:
            if not state.exists():
                print("No saved colour setting; nothing to restore.")
                return 0
            saved = json.loads(state.read_text())
            if saved["output"] != output["name"]:
                raise ValueError("Saved colour setting belongs to a different connector.")
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
