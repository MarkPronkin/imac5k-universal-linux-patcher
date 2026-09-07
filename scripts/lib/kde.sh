#!/usr/bin/env bash
mod_color_desc() { echo "Uses Plasma Wayland's built-in EDID colour profile for the iMac panel. Saves and restores the previous profile selection."; }
mod_color_detect() { python3 "$SCRIPT_DIR/kde-display.py" --status; }
mod_color_apply() { python3 "$SCRIPT_DIR/kde-display.py" --apply; }
mod_color_remove() { python3 "$SCRIPT_DIR/kde-display.py" --remove; }
