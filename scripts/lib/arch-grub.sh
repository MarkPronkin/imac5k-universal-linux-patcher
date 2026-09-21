#!/usr/bin/env bash
# Arch-family GRUB backend: sourced after the base (Omarchy/Limine) module
# definitions when the system is Arch-like and boots GRUB. The 5K, macOS and
# both sleep modules (suspend, t2suspend) keep their base logic; only the
# pieces that touch the boot configuration are re-pointed at
# /etc/default/grub + grub-mkconfig.
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

# macOS mode. GRUB loads the kernel image itself, so the set_os edit lands in
# the /boot copy the mkinitcpio preset installs before every build, and it
# has to be taken back out explicitly: rebuilding the initramfs never re-copies
# the kernel. The parameters go in GRUB_CMDLINE_LINUX, which recovery entries
# read too, because every entry boots the same edited image.
mod_macos_desc() { echo "Makes the kernel tell Apple's firmware that macOS is starting, as it already does for some MacBook Pros. That exposes the Intel HD 630 the firmware otherwise hides, which then encodes and decodes video for every app that takes the first GPU (H.264 about 3.7x faster than the Radeon, plus VP9 and HEVC 10-bit), and it makes the brightness slider actually dim the panel — over the full range where the ACPI table can be rebuilt, which needs iasl. The Radeon keeps the display and all 3D. A mkinitcpio hook makes the edit in the kernel image GRUB loads and repeats it after every kernel update; the parameters go in GRUB_CMDLINE_LINUX. Needs GRUB 2.12 or newer installed for UEFI, which starts the kernel through its EFI stub. Verified on an iMac18,3 under Omarchy/Limine; the GRUB path is untested on hardware."; }
macos_boot_image() {
    local pkgbase
    pkgbase=$(imac_kernel_pkgbase "$KREL") || return 1
    printf '%s/vmlinuz-%s\n' "$GRUB_BOOT_DIR" "$pkgbase"
}
# Every kernel the hook edited, not just the running one's.
macos_restore_images() {
    sudo bash -c 'shopt -s nullglob; exec python3 "$1" --restore "$2"/vmlinuz-*' \
        bash "${SCRIPT_DIR}/imac-setos" "$GRUB_BOOT_DIR"
}
# Read without sudo, as detection must never ask for a password;
# /etc/default/grub is world-readable. Each parameter is its own token.
macos_cmdline_present() {
    local opts=() p
    read -ra opts <<< "$MACOS_OPTS"
    GRUB_SUDO='' grub_read_cmdlines 2>/dev/null || return 1
    for p in "${opts[@]}"; do
        grub_has_token "$GRUB_LINUX $GRUB_LINUX_DEFAULT" "$p" || return 1
    done
}
# Confirmed in the regenerated entry before the hook goes in: a drop-in in
# /etc/default/grub.d that reassigns GRUB_CMDLINE_LINUX would otherwise leave
# an edited kernel booting without them.
macos_add_cmdline() {
    local opts=()
    read -ra opts <<< "$MACOS_OPTS"
    grub_cmdline_add_linux "${opts[@]}" && macos_verify_cmdline present
}
macos_remove_cmdline() {
    local opts=()
    read -ra opts <<< "$MACOS_OPTS"
    grub_cmdline_remove "${opts[@]}"
}
# All four, token by token: the mark the Limine drop-in is found by is only a
# prefix of one of them, and a GRUB entry is compared by whole tokens.
macos_verify_cmdline() {   # present|absent
    local opts=() p
    read -ra opts <<< "$MACOS_OPTS"
    for p in "${opts[@]}"; do
        if [[ $1 == present ]]; then verify_cmdline "$p" >/dev/null || return 1
        else verify_cmdline "" "$p" >/dev/null || return 1; fi
    done
    say "GRUB cmdline verified"
}
macos_image_note()  { printf 'the kernel image GRUB loads,\n    %s, each time mkinitcpio runs' "$(macos_boot_image)"; }
macos_params_note() { echo "to GRUB_CMDLINE_LINUX in ${GRUB_DEFAULT_FILE}"; }
macos_menu_note()   { echo "GRUB"; }
