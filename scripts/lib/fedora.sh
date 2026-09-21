#!/usr/bin/env bash
# Sourced after the original modules; preserves the Omarchy implementation.
fedora_mutable() {
    imac_is_atomic && { warn "Fedora Kinoite/Atomic is not supported; see docs/fedora-kde.md."; return 1; }
    return 0
}
fedora_deps() {
    local packages=("$@") missing=() package
    for package in "${packages[@]}"; do
        rpm -q "$package" >/dev/null 2>&1 || missing+=("$package")
    done
    ((${#missing[@]})) || return 0
    say "Required packages: ${missing[*]}"
    confirm "Install the missing Fedora packages with DNF?" || return 1
    sudo dnf install "${missing[@]}" || return 1
    [[ -f /usr/lib/modules/${KREL}/build/Module.symvers ]] || {
        warn "Matching kernel-devel is unavailable. Update Fedora, reboot, and retry."; return 1;
    }
}
mod_boot_detect() { echo n/a; }
mod_boot_apply() { warn "Limine boot repair does not apply to Fedora GRUB."; return 1; }
mod_boot_remove() { mod_boot_apply; }
# Both sleep modules (suspend on the iMac18,3, t2suspend on T2 models) keep
# the Omarchy logic. What differs is re-pointed here: image-based Fedora is
# refused, there is no Omarchy hibernation setup, and the retired idle=poll
# variant is migrated by grubby, which strips the argument from the current
# kernel's BLS entry. Boot tier only while that argument is on the entry.
suspend_backend_ok() { fedora_mutable; }
hibernation_setup_present() { return 1; }
suspend_no_cstates_present() {
    grubby --info "/boot/vmlinuz-${KREL}" 2>/dev/null | grep -q "$NO_CSTATES_PARAM"
}
suspend_drop_no_cstates() {
    suspend_no_cstates_present || return 0
    sudo grubby --update-kernel "/boot/vmlinuz-${KREL}" --remove-args "$NO_CSTATES_PARAM" || return 1
    say "removed stale ${NO_CSTATES_PARAM} from the GRUB entry"
}
mod_suspend_desc()  { echo "The iMac18,3's sleep fixes. Suspend there failed five ways: the stitch-layer driver bug is fixed in the kernel by the 5K module (rebuild it first if it predates release 0.1.91-alpha), and this module covers the other four. A sleep hook unbinds the Thunderbolt NHI, whose noirq suspend wedges the kernel in both deep and s2idle mode, before sleep and rebinds it after resume, and a second one does the same for the BCM43602 Wi-Fi, whose driver refuses most suspends (Wi-Fi reconnects after wake). A small DKMS module for this kernel, loaded at every boot, stops Apple's USB-controller power method (XHC1._PS3) from resetting the machine on every second sleep; with Secure Boot the DKMS key must be enrolled. Deep S3 still resets (firmware), so a systemd drop-in (MemorySleepMode=s2idle, systemd 256 or newer) makes every suspend use s2idle — treat it as experimental. Unmasks suspend.target. Hibernate still hard-hangs, so hibernate, hybrid-sleep and suspend-then-hibernate stay masked. Also removes the retired idle=poll argument from this kernel's GRUB entry if present. The 2014-2015 models sleep without any of this and T2 models have t2suspend; on the other models it only takes back what an earlier release installed."; }
mod_t2suspend_desc() { echo "Sleep on T2 models (iMac Pro, 2020 iMacs), following t2linux. Requires linux-t2's t2bce driver, which suspends and resumes the T2 itself, and refuses while an old hook or service unloads the T2 driver around sleep, naming the files. Keeps the kernel's sleep mode instead of forcing s2idle. Installs the Thunderbolt sleep hook as a precaution — it unbinds the NHI before sleep and rebinds it after resume — and removes the iMac18,3's Wi-Fi hook and s2idle drop-in where an earlier release installed them. Unmasks suspend.target; hibernate, hybrid-sleep and suspend-then-hibernate stay masked. Also removes the retired idle=poll argument from this kernel's GRUB entry if present. Not tested on T2 hardware."; }
# The USB controller fix, as for audio: built for the running kernel after an
# explicit kernel-devel preflight, and loadable under Secure Boot only once
# the DKMS signing key is enrolled.
xhci_fix_target_kernels() { printf '%s\n' "$KREL"; }
xhci_fix_deps() {
    fedora_deps dkms "kernel-devel-${KREL}" gcc make kmod elfutils-libelf-devel mokutil
}
xhci_fix_signing_ok() {
    local sb
    sb=$(mokutil --sb-state 2>/dev/null || true)
    [[ $sb == *'SecureBoot enabled'* ]] || return 0
    sudo mokutil --test-key /var/lib/dkms/mok.pub && return 0
    warn "Enroll the DKMS key: sudo mokutil --import /var/lib/dkms/mok.pub, reboot and confirm enrollment, then re-run suspend installation."
    return 1
}
audio_target_kernels() {
    # Fedora's explicit kernel-devel preflight targets the running kernel.
    audio_kernel_supported "$KREL" && printf '%s\n' "$KREL"
}
mod_audio_apply() {
    fedora_mutable || return 1
    imac_audio_supported || { warn "The bundled CS8409 driver supports only iMac18,3; keep this model's existing audio driver."; return 1; }
    audio_check_hardware || return 1
    audio_kernel_supported "$KREL" || { warn "The headset driver requires Linux 6.17+."; return 1; }
    fedora_deps dkms "kernel-devel-${KREL}" gcc make patch wget git tar xz kmod dracut elfutils-libelf-devel openssl-devel mokutil || return 1
    audio_install_driver || return 1
    local sb
    sb=$(mokutil --sb-state 2>/dev/null || true)
    if [[ $sb == *'SecureBoot enabled'* ]]; then
        sudo mokutil --test-key /var/lib/dkms/mok.pub || {
            warn "Enroll the DKMS key: sudo mokutil --import /var/lib/dkms/mok.pub, reboot and confirm enrollment, then re-run audio installation."
            return 1
        }
    fi
    sudo dracut --force "/boot/initramfs-${KREL}.img" "$KREL" || return 1
    say "Audio installed for ${KREL}; reboot to load it."
}
mod_audio_remove() {
    fedora_mutable || return 1
    audio_remove_driver || return 1
    # DKMS removal affects every installed kernel; update their initramfs too.
    sudo dracut --regenerate-all --force || return 1
    say "Stock audio modules restored; reboot."
}
mod_5k_desc() { echo "Builds amdgpu from matching Fedora sources, installs a module override and rebuilds this kernel's dracut image. Enables 5K in this kernel's GRUB entry."; }
mod_5k_detect() {
    local installed=0 live=0 active=0
    [[ -f /usr/lib/modules/${KREL}/updates/imac5k/amdgpu.ko.xz ]] && installed=1
    ((installed)) || imac_has_amdgpu || { echo n/a; return; }
    [[ $(cat /sys/module/amdgpu/parameters/tiled_stitch 2>/dev/null) =~ ^(1|Y)$ ]] && live=1
    if imac_is_kde; then
        python3 "$SCRIPT_DIR/kde-display.py" --5k-active 2>/dev/null && active=1
    elif command -v hyprctl >/dev/null; then
        local outputs
        outputs=$(hyprctl monitors 2>/dev/null)
        [[ $outputs == *5120x2880* ]] && active=1
    fi
    if ((installed && live && active)) && five_k_has_10bpc; then echo applied
    elif ((installed || live)); then echo partial
    else echo not-applied; fi
}
mod_5k_preflight() {
    imac_has_amdgpu || { warn "The 5K display patch requires a GPU using amdgpu."; return 1; }
    fedora_mutable || return 1
    [[ $KSERIES == 7.1 || $KSERIES == 7.2 ]] || {
        warn "Kernel ${KREL} needs a patch port; supported series: 7.1 and 7.2."; return 1;
    }
    fedora_deps "kernel-devel-${KREL}" gcc make binutils bc dwarves flex bison patch xz curl tar \
        rpm-build koji python3 python3-rpm-macros elfutils-libelf-devel openssl-devel dracut grubby mokutil \
        perl-interpreter findutils diffutils git || return 1
    "$SCRIPT_DIR/fedora-imac5k" --check
}
mod_5k_apply() {
    mod_5k_preflight || return 1
    say "Recovery: select another Fedora kernel in GRUB. To undo this kernel: $0 --remove 5k"
    confirm "Build and install 5K support for ${KREL}?" || return 1
    local log="$LOGDIR/apply-5k-$(date +%Y%m%d-%H%M%S).log"
    "$SCRIPT_DIR/fedora-imac5k" 2>&1 | tee "$log" || return 1
    five_k_set_10bpc
}
mod_5k_remove() {
    fedora_mutable || return 1
    sudo "$SCRIPT_DIR/fedora-imac5k" --restore
}
