#!/usr/bin/env bash
# Arch-family GRUB backend: sourced after the base (Omarchy/Limine) module
# definitions when the system is Arch-like and boots GRUB. The 5K/suspend
# modules keep their base logic; only the pieces that touch the boot
# configuration are re-pointed at /etc/default/grub + grub-mkconfig.
source "${SCRIPT_DIR}/lib/grub.sh"
GRUB_SUDO=sudo

# Boot repair is Limine-specific (shadow limine.conf copies, UKI fallback) —
# same n/a policy as the Fedora backend.
mod_boot_detect() { echo n/a; }
mod_boot_apply() { warn "Boot repair is specific to the Omarchy/Limine layout; nothing to do on GRUB."; return 1; }
mod_boot_remove() { mod_boot_apply; }

boot_config_has() { grub_cmdline_has "$1"; }

# The cmdline edits (grub_cmdline_add/remove) regenerate grub.cfg themselves;
# what remains here is the initramfs, which carries the patched amdgpu module.
sync_boot_files() {
    say "rebuilding initramfs"
    sudo mkinitcpio -P || return 1
    grub_regen
}

# $1 must be present, $2 must be absent. Check the running kernel's normal
# entry, which need not be the first installed kernel in the GRUB menu.
verify_cmdline() {
    local entry line
    entry=$(grub_kernel_entry) || { warn "verify: no normal entry for the running kernel in $GRUB_CFG"; return 1; }
    line=$(awk '$1 == "linux" || $1 == "linuxefi" { $1=""; $2=""; print; exit }' <<< "$entry")
    [[ -n ${1:-} ]] && ! grub_has_token "$line" "$1" && { warn "verify: GRUB cmdline missing '$1'"; return 1; }
    [[ -n ${2:-} ]] &&   grub_has_token "$line" "$2" && { warn "verify: GRUB cmdline still has '$2'"; return 1; }
    say "GRUB cmdline verified"
}

suspend_drop_no_cstates() {
    grub_cmdline_has "$NO_CSTATES_PARAM" || return 0
    grub_cmdline_remove "$NO_CSTATES_PARAM" || return 1
    verify_cmdline '' "$NO_CSTATES_PARAM" || return 1
    say "removed stale ${NO_CSTATES_PARAM} from ${GRUB_DEFAULT_FILE} — reboot to restore idle C-states"
}

# The 4K fallback pins eDP-1 to a single-tile mode the stitched driver rejects.
remove_4k_fallback() { grub_cmdline_remove "$VIDEO_4K"; }
add_4k_fallback()    { grub_cmdline_add "$VIDEO_4K"; }
remove_stitch_boot_config() { grub_cmdline_remove 'amdgpu.tiled_stitch=1'; }

audio_refresh_initramfs() { sudo mkinitcpio -P; }

mod_5k_desc() { echo "Wakes the panel's second tile, stitches both into one 5120x2880 output and genlocks them. Rebuilds the amdgpu module for the running kernel (stock module backed up), enables amdgpu.tiled_stitch=1 in the GRUB cmdline."; }
