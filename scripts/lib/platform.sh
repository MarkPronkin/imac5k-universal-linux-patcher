#!/usr/bin/env bash
# Shared platform detection. Never infer the bootloader from an installed tool.
imac_is_fedora() { ( . /etc/os-release; [[ ${ID:-} == fedora ]] ); }
imac_is_atomic() { [[ -e /run/ostree-booted ]]; }
imac_is_kde() { local desktop=${XDG_CURRENT_DESKTOP:-}; [[ ${desktop,,} == *kde* ]]; }
imac_require_limine() {
    if imac_is_fedora || [[ ! -f /etc/default/limine ]]; then
        echo "This helper requires an Omarchy/Limine installation. On Fedora use imac-patcher --apply/--remove 5k." >&2
        exit 1
    fi
}
