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
# The bundled driver has board-specific CS8409 initialization and its own
# iMac18,3 gate. Other models must retain their existing audio drivers.
imac_audio_supported() { [[ ${product:-$(imac_product_name)} == iMac18,3 ]]; }

imac_is_fedora() { ( . /etc/os-release; [[ ${ID:-} == fedora ]] ); }
imac_is_atomic() { [[ -e /run/ostree-booted ]]; }
imac_is_kde() { local desktop=${XDG_CURRENT_DESKTOP:-}; [[ ${desktop,,} == *kde* ]]; }
imac_require_limine() {
    if imac_is_fedora || [[ ! -f /etc/default/limine ]]; then
        echo "This helper requires an Omarchy/Limine installation. On Fedora use imac-patcher --apply/--remove 5k." >&2
        exit 1
    fi
}
