#!/usr/bin/env bash
mod_color_desc() { echo "Uses Plasma Wayland's built-in EDID colour profile for the iMac panel. Saves and restores the previous profile selection."; }
mod_color_detect() {
    command -v python3 >/dev/null && command -v kscreen-doctor >/dev/null || { echo n/a; return; }
    python3 "$SCRIPT_DIR/kde-display.py" --status
}
# KWin stores per-output settings against the panel's EDID, so the 5K stitch --
# which rewrites that EDID -- brings eDP-1 back as a new output at KDE's own
# defaults and leaves the colour profile behind on the old one. Nothing can
# carry a setting across that boot: the new identity does not exist yet. So
# refuse rather than apply something the next boot silently drops.
color_stitch_pending() {
    boot_config_has 'amdgpu.tiled_stitch=1' && ! imac_panel_has_stitched_mode
}
mod_color_apply() {
    if color_stitch_pending; then
        warn "the 5K stitch is configured but not active yet."
        warn "It changes the panel's identity at the next boot, and KDE would drop this"
        warn "colour profile with the old one. Reboot first, then: $0 --apply color"
        return 1
    fi
    python3 "$SCRIPT_DIR/kde-display.py" --apply
}
mod_color_remove() { python3 "$SCRIPT_DIR/kde-display.py" --remove; }

# Same reason in the other direction: applying 5K invalidates a colour profile
# that is already in place, and the module cannot re-apply it until the panel
# it belongs to exists. Say so at the point the reboot is asked for.
color_note_after_5k() {
    [[ "$(mod_color_detect)" == applied ]] || return 0
    warn "the stitch changes the panel's identity, so KDE will come back with its own"
    warn "colour defaults. Re-apply the colour module after the reboot: $0 --apply color"
}
