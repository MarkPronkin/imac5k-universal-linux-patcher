#!/usr/bin/env bash
# Independent experimental Intel video opt-in. Only firmware/graphics files
# are shared with macos; the brightness table and NVRAM service are separate.
mod_igpu_title() { echo "Expose Intel iGPU"; }
mod_igpu_tier() { echo experimental; }
mod_igpu_desc() { echo "Experimental, independent opt-in for the iMac18,3's headless Intel HD 630 and Quick Sync. Enables the firmware mode, loads i915 with a no-outputs VBT, and keeps the desktop on the Radeon. Does not install the full-range brightness table or NVRAM brightness service; those belong to the separate macos patch. Works alone or alongside macos; removing it keeps an installed brightness patch and blocks Intel graphics again. Needs a reboot. Omarchy/Limine or Arch-family GRUB with mkinitcpio only; the separate module is not yet boot-tested."; }

igpu_cmdline_present() {
    boot_config_has 'i915.vbt_firmware=imac18-3/headless-vbt.bin' &&
        ! boot_config_has 'module_blacklist=.*i915'
}
igpu_add_cmdline() {
    sudo mkdir -p "$LIMINE_DROPIN_DIR" || return 1
    printf '%s\n%s\n' '# Written by imac-patcher (experimental Intel graphics).' \
        "KERNEL_CMDLINE[default]+=\" ${IGPU_OPTS}\"" \
        | sudo tee "$IGPU_DROPIN" >/dev/null || return 1
}
igpu_remove_cmdline() { sudo rm -f "$IGPU_DROPIN"; }
igpu_verify_cmdline() {
    local p opts=()
    read -ra opts <<< "$IGPU_OPTS"
    for p in "${opts[@]}"; do verify_cmdline "$p" >/dev/null || return 1; done
    verify_cmdline '' 'module_blacklist=i915,i2c_i801'
}
mod_igpu_detect() {
    if [[ ! -f $IGPU_MKI && ! -f $IGPU_DROPIN ]]; then
        if imac_macos_mode_supported && macos_backend_supported; then echo not-applied; else echo n/a; fi
        return
    fi
    local driver=''
    [[ -L $MACOS_IGPU/driver ]] && driver=$(readlink "$MACOS_IGPU/driver")
    if [[ -f $IGPU_MKI && -x $MACOS_HOOK && -f $MACOS_VBT &&
          -f "/etc/udev/rules.d/${MACOS_RULES[0]}" && -f "/etc/udev/rules.d/${MACOS_RULES[1]}" &&
          ${driver##*/} == i915 && -d $MACOS_IGPU/drm ]] && igpu_cmdline_present; then
        echo applied
    else
        echo partial
    fi
}
mod_igpu_preflight() {
    macos_boot_preflight || return 1
    local want=()
    if command -v pacman >/dev/null; then
        pacman -Qq intel-media-driver >/dev/null 2>&1 || want+=(intel-media-driver)
        pacman -Qq libva-utils >/dev/null 2>&1 || want+=(libva-utils)
    fi
    if ((${#want[@]})); then
        say "recommended for Intel video: ${want[*]}"
        macos_offer_packages "${want[@]}"
    fi
    return 0
}
mod_igpu_apply() {
    mod_igpu_preflight || { warn "preflight failed — nothing was changed."; return 1; }
    say "Experimental: expose the Intel HD 630 for video; keep the Radeon desktop."
    say "This edits $(macos_image_note) and the boot parameters $(macos_params_note)."
    say "Brightness table and NVRAM service are unchanged. Undo: $0 --remove igpu, then reboot."
    confirm "Enable the experimental Intel iGPU?" || return 1
    sudo install -Dm644 "${MACOS_CFG}/headless-vbt.bin" "$MACOS_VBT" || return 1
    local rule
    for rule in "${MACOS_RULES[@]}"; do
        sudo install -Dm644 "${MACOS_CFG}/${rule}" "/etc/udev/rules.d/${rule}" || return 1
    done
    sudo udevadm control --reload || return 1
    sudo udevadm trigger -s drm -s pci || return 1
    macos_install_hypr_pin || return 1
    sudo install -Dm644 "${MACOS_CFG}/zz-imac-igpu-experimental.conf" "$IGPU_MKI" || return 1
    if [[ -f $MACOS_MKI ]]; then macos_add_cmdline || return 1; fi
    igpu_add_cmdline || return 1
    sudo install -Dm755 "${SCRIPT_DIR}/imac-setos" "$MACOS_HOOK" || return 1
    sync_boot_files && macos_image_lists_model && igpu_verify_cmdline || return 1
    say "reboot to expose Intel graphics, then check: $0 --status"
}
mod_igpu_remove() {
    local rule
    if [[ ! -f $MACOS_MKI ]]; then
        # Restore GRUB kernels before removing anything they still need.
        macos_restore_images || return 1
        sudo rm -f "$MACOS_HOOK" "$MACOS_VBT" || return 1
        sudo rmdir "$MACOS_VBT_DIR" 2>/dev/null
        for rule in "${MACOS_RULES[@]}"; do
            sudo rm -f "/etc/udev/rules.d/${rule}" || return 1
        done
        macos_remove_hypr_pin || return 1
    fi
    sudo rm -f "$IGPU_MKI" || return 1
    igpu_remove_cmdline || return 1
    if [[ -f $MACOS_MKI ]]; then macos_add_cmdline || return 1; fi
    sudo udevadm control --reload || return 1
    sudo udevadm trigger -s drm -s pci || return 1
    sync_boot_files || return 1
    if [[ -f $MACOS_MKI ]]; then
        macos_verify_cmdline present || return 1
        say "experimental Intel graphics disabled; brightness and NVRAM saving retained — reboot"
    else
        verify_cmdline '' 'i915.vbt_firmware=imac18-3/headless-vbt.bin' || return 1
        say "reboot to return to the plain boot with Intel graphics hidden"
    fi
}
