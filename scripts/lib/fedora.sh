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
# Same policy as the Omarchy suspend module — every sleep target masked off —
# plus migration for the retired idle=poll variant: grubby strips the argument
# from the current kernel's BLS entry.
mod_suspend_tier() {
    # Boot tier only while the retired argument is on the GRUB entry.
    grubby --info "/boot/vmlinuz-${KREL}" 2>/dev/null | grep -q "$NO_CSTATES_PARAM" && echo boot || echo safe
}
mod_suspend_desc()  { echo "Suspend and hibernate hard-hang this machine, every time — recovery is a hard power-cycle, and idle=poll does not rescue it. Masks all four sleep targets so nothing triggers them. Also removes the retired idle=poll argument from this kernel's GRUB entry if present. Leave this off if sleep works on your model."; }
mod_suspend_detect() {
    local masked=0
    for t in "${SLEEP_TARGETS[@]}"; do
        [[ "$(systemctl is-enabled "$t" 2>/dev/null)" == masked ]] && (( masked++ ))
    done
    local stale=0
    grubby --info "/boot/vmlinuz-${KREL}" 2>/dev/null | grep -q "$NO_CSTATES_PARAM" && stale=1
    if (( masked == ${#SLEEP_TARGETS[@]} && ! stale )); then echo applied
    elif (( masked || stale )); then echo partial
    else echo not-applied; fi
}
fedora_suspend_drop_no_cstates() {
    grubby --info "/boot/vmlinuz-${KREL}" 2>/dev/null | grep -q "$NO_CSTATES_PARAM" || return 0
    sudo grubby --update-kernel "/boot/vmlinuz-${KREL}" --remove-args "$NO_CSTATES_PARAM" || return 1
    say "removed stale ${NO_CSTATES_PARAM} from the GRUB entry"
}
mod_suspend_apply() {
    fedora_mutable || return 1
    sudo systemctl mask "${SLEEP_TARGETS[@]}" || return 1
    fedora_suspend_drop_no_cstates
}
mod_suspend_remove() {
    fedora_mutable || return 1
    sudo systemctl unmask "${SLEEP_TARGETS[@]}"
    fedora_suspend_drop_no_cstates
    say "sleep re-enabled"
}
mod_audio_apply() {
    fedora_mutable || return 1
    imac_audio_supported || { warn "The bundled CS8409 driver supports only iMac18,3; keep this model's existing audio driver."; return 1; }
    local codec found=0
    for codec in /sys/bus/hdaudio/devices/*/chip_name; do
        [[ -f $codec && $(cat "$codec") == CS8409* ]] && found=1
    done
    ((found)) || { warn "CS8409 codec was not detected."; return 1; }
    fedora_deps dkms "kernel-devel-${KREL}" gcc make patch wget git elfutils-libelf-devel openssl-devel mokutil || return 1
    if [[ -d $AUDIO_SRC/.git ]]; then
        git -C "$AUDIO_SRC" pull --ff-only || return 1
    else
        git clone --depth 1 "$AUDIO_REPO" "$AUDIO_SRC" || return 1
    fi
    # Use DKMS directly: the upstream wrapper assumes updates/dkms and loops
    # over every kernel, sometimes hiding a failed build behind a later success.
    # DKMS copies this checkout to /usr/src; future builds do not need the cache.
    local status
    status=$(dkms status -m snd_hda_macbookpro -v 0.2) || return 1
    if [[ $status == *broken* ]]; then
        warn "Broken audio registration: run sudo dkms remove snd_hda_macbookpro/0.2 --all, then retry."
        return 1
    fi
    if [[ -z $status ]]; then
        sudo dkms add "$AUDIO_SRC" || return 1
    fi
    sudo dkms install -m snd_hda_macbookpro -v 0.2 -k "$KREL" || return 1
    status=$(dkms status -m snd_hda_macbookpro -v 0.2 -k "$KREL") || return 1
    [[ $status == *installed* ]] || { warn "Audio DKMS build failed for ${KREL}."; return 1; }
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
    sudo dkms remove snd_hda_macbookpro/0.2 --all || return 1
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
    if ((installed && live && active)); then echo applied
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
    "$SCRIPT_DIR/fedora-imac5k" 2>&1 | tee "$log"
}
mod_5k_remove() {
    fedora_mutable || return 1
    sudo "$SCRIPT_DIR/fedora-imac5k" --restore
}
