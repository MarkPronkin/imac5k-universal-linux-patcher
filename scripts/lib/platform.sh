#!/usr/bin/env bash
# Shared platform detection. Never infer the bootloader from an installed tool.
imac_product_name() { cat /sys/class/dmi/id/product_name 2>/dev/null || echo unknown; }
# Apple's complete Retina 5K family, including the 5K iMac Pro. Do not match
# iMac* indiscriminately: adjacent identifiers include 4K and non-Retina Macs.
# https://support.apple.com/en-us/108054
imac_is_retina5k() {
    case "${1:-$(imac_product_name)}" in
        iMac15,1|iMac17,1|iMac18,3|iMac19,1|iMac20,1|iMac20,2|iMacPro1,1) return 0 ;;
        *) return 1 ;;
    esac
}
imac_has_amdgpu() {
    local driver
    for driver in /sys/class/drm/card*/device/driver; do
        [[ $(readlink -f "$driver") == */amdgpu ]] && return 0
    done
    return 1
}
# Whether the panel is running stitched. The mode is a property of the driver,
# not of the compositor: the root eDP connector advertises 5120x2880 only once
# the second tile has been folded in. Reading it from sysfs works on every
# desktop and from a TTY, where hyprctl and kscreen-doctor report nothing.
IMAC_DRM_DIR="${IMAC_DRM_DIR:-/sys/class/drm}"
imac_panel_has_stitched_mode() {
    local modes
    for modes in "$IMAC_DRM_DIR"/card*-eDP-*/modes; do
        [[ -r $modes ]] && grep -qx '5120x2880' "$modes" && return 0
    done
    return 1
}
# The bundled driver has board-specific CS8409 initialization and its own
# iMac18,3 gate. Other models must retain their existing audio drivers.
imac_audio_supported() { [[ ${product:-$(imac_product_name)} == iMac18,3 ]]; }

imac_is_fedora() { ( . /etc/os-release; [[ ${ID:-} == fedora ]] ); }
imac_is_arch() { ( . /etc/os-release; [[ ${ID:-} == arch || " ${ID_LIKE:-} " == *" arch "* ]] ); }
imac_is_atomic() { [[ -e /run/ostree-booted ]]; }
imac_is_kde() { local desktop=${XDG_CURRENT_DESKTOP:-}; [[ ${desktop,,} == *kde* ]]; }
# Bootloaders are identified by the configs they maintain, never by installed
# tools: /etc/default/limine for Limine, /etc/default/grub for GRUB.
imac_has_limine() { [[ -f /etc/default/limine ]]; }
imac_has_grub() { [[ -f /etc/default/grub ]]; }
# Arch-family system booting GRUB (Arch, EndeavourOS, CachyOS, ...). Limine wins
# when both configs exist, so an Omarchy install keeps its backend even with a
# stale /etc/default/grub left over from another setup.
imac_is_arch_grub() { ! imac_is_fedora && imac_is_arch && imac_has_grub && ! imac_has_limine; }
# The Arch-style kernel package base ("linux", "linux-lts", "linux-cachyos",
# ...), from packaging metadata every such kernel ships. Headers for it are the
# "<pkgbase>-headers" package.
imac_kernel_pkgbase() {
    local krel=${1:-$(uname -r)} pkgbase
    pkgbase=$(cat "/usr/lib/modules/${krel}/pkgbase" 2>/dev/null) || pkgbase=linux
    [[ $pkgbase =~ ^[a-zA-Z0-9][a-zA-Z0-9._+-]*$ ]] || return 1
    printf '%s\n' "$pkgbase"
}
imac_kernel_uses_clang() {
    grep -qx 'CONFIG_CC_IS_CLANG=y' "/usr/lib/modules/${1:-$(uname -r)}/build/.config" 2>/dev/null
}
imac_require_limine() {
    if imac_is_fedora || [[ ! -f /etc/default/limine ]]; then
        echo "This helper requires an Omarchy/Limine installation. On Fedora use imac-patcher --apply/--remove 5k." >&2
        exit 1
    fi
}
