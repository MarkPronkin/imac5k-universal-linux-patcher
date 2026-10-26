#!/usr/bin/env bash
# Shared Debian/Ubuntu overrides; configuration chooses source and signing rules.
source "${SCRIPT_DIR}/lib/grub.sh"
source "${SCRIPT_DIR}/lib/apt-platform.sh"
imac_apt_configure "$IMAC_APT_DISTRO" || return 1
GRUB_SUDO=sudo
APT_5K_ENTRY=/etc/grub.d/09_imac5k-${KREL}
apt_deps() {
    local package missing=()
    for package in "$@"; do
        [[ $(dpkg-query -W -f='${db:Status-Status}' "$package" 2>/dev/null) == installed ]] || missing+=("$package")
    done
    if ((${#missing[@]})); then
        say "Required ${IMAC_APT_NAME} packages: ${missing[*]}"
        confirm "Install the missing packages with APT?" || return 1
        sudo apt-get install -y "${missing[@]}" || return 1
        for package in "${missing[@]}"; do
            [[ $(dpkg-query -W -f='${db:Status-Status}' "$package" 2>/dev/null) == installed ]] || {
                warn "$package is still missing after installation."; return 1;
            }
        done
    fi
}
apt_headers_ok() {
    [[ -f /lib/modules/${KREL}/build/Module.symvers ]] || {
        warn "Matching linux-headers-${KREL} are unavailable. Update ${IMAC_APT_NAME}, reboot into the new kernel, and retry."; return 1;
    }
}
mod_boot_detect() { echo n/a; }
mod_boot_apply() { warn "Boot repair is specific to Omarchy/Limine; ${IMAC_APT_NAME} uses its own GRUB setup."; return 1; }
mod_boot_remove() { mod_boot_apply; }
# The firmware-image edit and mkinitcpio hooks are not a Debian/Ubuntu boot path.
macos_backend_supported() { return 1; }

boot_config_has() {
    if [[ $1 == amdgpu.tiled_stitch=1 ]] && grep -qsF 'amdgpu.tiled_stitch=1' "$APT_5K_ENTRY"; then return 0; fi
    imac_has_grub && GRUB_SUDO='' grub_cmdline_has "$1"
}
hibernation_setup_present() { return 1; }
suspend_backend_ok() { return 0; }
suspend_no_cstates_present() { imac_has_grub && GRUB_SUDO='' grub_cmdline_has "$NO_CSTATES_PARAM"; }
suspend_drop_no_cstates() {
    suspend_no_cstates_present || return 0
    grub_cmdline_remove "$NO_CSTATES_PARAM"
}
xhci_fix_target_kernels() { [[ -f /lib/modules/${KREL}/build/Module.symvers ]] && printf '%s\n' "$KREL"; }
xhci_fix_deps() {
    apt_deps dkms "linux-headers-${KREL}" build-essential kmod libelf-dev mokutil "${IMAC_APT_DKMS_PACKAGES[@]}" && apt_headers_ok
}
xhci_fix_signing_ok() {
    local status lockdown certificate=${IMAC5K_DKMS_CERT:-$IMAC_APT_DKMS_CERT}
    status=$(mokutil --sb-state 2>/dev/null || true)
    lockdown=$(cat /sys/kernel/security/lockdown 2>/dev/null || true)
    [[ $status != *'SecureBoot enabled'* && $lockdown != *'[integrity]'* && $lockdown != *'[confidentiality]'* ]] && return 0
    sudo mokutil --test-key "$certificate" && return 0
    warn "Enroll the DKMS key: sudo mokutil --import $certificate, reboot and confirm enrollment, then re-run suspend installation."
    return 1
}
audio_target_kernels() {
    audio_kernel_supported "$KREL" && [[ -f /lib/modules/${KREL}/build/Module.symvers ]] && printf '%s\n' "$KREL"
}
# Keep the shared DKMS detection, but do not offer a 6.17+ driver on older
# kernels. Leftovers remain partial so they can still be removed.
_apt_audio_detect=$(declare -f mod_audio_detect)
eval "${_apt_audio_detect/mod_audio_detect/apt_audio_detect_base}"
unset _apt_audio_detect
mod_audio_detect() {
    imac_audio_supported || { echo n/a; return; }
    if audio_kernel_supported "$KREL"; then apt_audio_detect_base; return; fi
    local registered= path
    if command -v dkms >/dev/null; then
        registered=$(dkms status -m "$AUDIO_DKMS" 2>/dev/null) || {
            warn "Could not inspect DKMS registrations."; return 1;
        }
    fi
    path=$(modinfo -k "$KREL" -n snd_hda_codec_cs8409 2>/dev/null) || path=
    if [[ -n $registered || $path == */updates/* || $path == */extra/* ]]; then echo partial
    else echo n/a; fi
}
audio_refresh_initramfs() { sudo update-initramfs -u -k all; }
mod_audio_apply() {
    audio_kernel_supported "$KREL" || {
        warn "The bundled CS8409 driver requires Linux 6.17+; keep the existing audio driver on this kernel or boot a supported newer kernel."; return 1;
    }
    audio_check_hardware || return 1
    apt_deps dkms "linux-headers-${KREL}" build-essential patch wget git tar xz-utils kmod initramfs-tools libelf-dev libssl-dev mokutil "${IMAC_APT_DKMS_PACKAGES[@]}" || return 1
    apt_headers_ok || return 1
    [[ $IMAC_APT_DISTRO != ubuntu ]] || ubuntu_audio_source_deps || return 1
    audio_install_driver || return 1
    xhci_fix_signing_ok || return 1
    audio_refresh_initramfs || return 1
    say "Audio installed for ${KREL}; reboot to load it."
}
mod_audio_remove() {
    audio_remove_driver || return 1
    audio_refresh_initramfs || return 1
    say "Stock audio modules restored; reboot."
}
mod_5k_desc() { echo "Builds amdgpu from the exact matching ${IMAC_APT_NAME} linux-source package and headers, installs a module override and rebuilds this kernel's initramfs with initramfs-tools. Adds a separate iMac 5K GRUB entry; other kernels keep their original arguments. Reapply after each kernel update. Not boot-tested on ${IMAC_APT_NAME} hardware."; }
mod_5k_detect() {
    local installed=0 complete=0 live=0
    [[ -f /lib/modules/${KREL}/updates/imac5k/amdgpu.ko.xz || -f $APT_5K_ENTRY ||
       -f /etc/initramfs-tools/hooks/imac5k-${KREL//+/_} ||
       -f /var/lib/imac-patcher/5k-${KREL}/recovery-needed ]] && installed=1
    if [[ -f /lib/modules/${KREL}/updates/imac5k/amdgpu.ko.xz && -f $APT_5K_ENTRY &&
          -x /etc/initramfs-tools/hooks/imac5k-${KREL//+/_} &&
          ! -f /var/lib/imac-patcher/5k-${KREL}/recovery-needed ]]; then complete=1; fi
    ((installed)) || imac_has_amdgpu || { echo n/a; return; }
    [[ $(cat /sys/module/amdgpu/parameters/tiled_stitch 2>/dev/null) =~ ^(1|Y)$ ]] && live=1
    if ((complete && live)) && imac_panel_has_stitched_mode && five_k_has_10bpc; then echo applied
    elif ((installed || live)); then echo partial
    else echo not-applied; fi
}
mod_5k_preflight() {
    imac_has_amdgpu || { warn "The 5K display patch requires a GPU using amdgpu."; return 1; }
    imac_has_grub && ! imac_has_limine || { warn "${IMAC_APT_NAME} 5K requires GRUB and initramfs-tools; Limine/UKI layouts are unsupported."; return 1; }
    imac_apt_kernel_supported || {
        warn "Kernel ${KREL} needs a patch port; supported $IMAC_APT_NAME series: $IMAC_APT_SERIES."; return 1;
    }
    local source_tools=()
    [[ $IMAC_APT_DISTRO != ubuntu ]] || source_tools+=(bzip2)
    apt_deps "linux-headers-${KREL}" build-essential binutils bc pahole flex bison patch xz-utils "${source_tools[@]}" curl ca-certificates tar \
        python3 dpkg libelf-dev libssl-dev initramfs-tools grub-common mokutil perl findutils diffutils || return 1
    apt_headers_ok || return 1
    "$SCRIPT_DIR/$IMAC_APT_HELPER" --check
}
mod_5k_apply() {
    mod_5k_preflight || return 1
    say "Recovery: select another ${IMAC_APT_NAME} kernel in GRUB. To undo this kernel: $0 --remove 5k"
    confirm "Build and install 5K support for ${KREL}?" || return 1
    local log="$LOGDIR/apply-5k-$(date +%Y%m%d-%H%M%S).log"
    "$SCRIPT_DIR/$IMAC_APT_HELPER" 2>&1 | tee "$log" || return 1
    five_k_set_10bpc
}
mod_5k_remove() { sudo "$SCRIPT_DIR/$IMAC_APT_HELPER" --restore; }
