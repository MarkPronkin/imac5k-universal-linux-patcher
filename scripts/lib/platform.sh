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
# Apple's XHC1._PS3 resets the iMac18,3 on the PCH USB controller's second D3
# entry. Other models' firmware has not been examined; they keep stock xHCI PM.
imac_xhci_fix_supported() { [[ ${product:-$(imac_product_name)} == iMac18,3 ]]; }
# The suspend module's sleep fixes were each found and verified on the
# iMac18,3. The 2014-2015 models (iMac15,1, iMac17,1) sleep with the stock
# kernel, T2 models have their own module (t2suspend, below), and the
# iMac19,1 is untested, so none of them is offered the iMac18,3's fixes.
imac_suspend_supported() { [[ ${product:-$(imac_product_name)} == iMac18,3 ]]; }
# Models with an Apple T2 (iMac Pro, 2020 iMacs). Their internal devices sit
# behind the T2's BCE, which linux-t2's t2bce driver stack suspends and
# resumes itself; the t2suspend module follows t2linux's rules on these.
imac_has_t2() {
    case ${product:-$(imac_product_name)} in
        iMacPro1,1|iMac20,1|iMac20,2) return 0 ;;
        *) return 1 ;;
    esac
}
# The iMac Pro's built-in audio is the T2 (t2bce_audio, ALSA card AppleT2x4,
# UCM profiles), not the CS8409 codec the EQ chain targets: there is no
# four-channel CS8409 device to pin the chain to, and the tuning was measured
# on CS8409 machines. Other models keep their existing gate (a card that
# offers the 4.0 profile).
imac_eq_supported() { [[ ${product:-$(imac_product_name)} != iMacPro1,1 ]]; }
# The iMac Pro (iMacPro1,1) drives 4 speaker drivers through the T2's Pro Audio
# path (PCM devices 0, 4, 100). Only 2 of the 4 play without an explicit
# channel map, so this gate is the complement of the CS8409 ones above.
imac_t2speakers_supported() { [[ ${product:-$(imac_product_name)} == iMacPro1,1 ]]; }
# macOS mode (apple_set_os): iMac18,3 only. The Intel HD 630 at 00:02.0, the
# Radeon's PCI address the udev rules key on, the no-outputs VBT built for
# Kaby Lake and the firmware's ABCL brightness table were all verified on that
# machine and nowhere else. iMacPro1,1 is a permanent no: its Xeon W has no
# integrated graphics at all, so there is nothing for set_os to expose, and its
# panel is not driven through this backlight path. The other 5K models do carry
# an iGPU (15,1 Haswell, 17,1 Skylake, 19,1 Coffee Lake, 20,x Comet Lake), but
# each one needs its own VBT, PCI addresses and ACPI table shape checked first.
imac_macos_mode_supported() { [[ ${product:-$(imac_product_name)} == iMac18,3 ]]; }

# Vega 10 / DCE 12 (iMac Pro): the tile pair latches only when the stream is
# brought up at the panel's native 10 bpc. Hyprland's default 8 bpc leaves the
# second tile unlocked and the desktop stretched. See patches/README.md.
imac_panel_needs_10bpc() { [[ ${product:-$(imac_product_name)} == iMacPro1,1 ]]; }

imac_is_fedora() { ( [[ -r /etc/os-release ]] && . /etc/os-release; [[ ${ID:-} == fedora ]] ); }
imac_is_arch() { ( [[ -r /etc/os-release ]] && . /etc/os-release; [[ ${ID:-} == arch || ${ID:-} == archlinux || " ${ID_LIKE:-} " == *" arch "* || " ${ID_LIKE:-} " == *" archlinux "* ]] ); }
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
# Omarchy's limine hook names the default UKI after the kernel package base:
# omarchy_linux.efi for linux, omarchy_linux-t2.efi for linux-t2 (the T2 iMac
# Pro). Every helper that looks for "the default UKI" must derive it, not
# assume linux.
imac_default_uki() {   # $1 = kernel release, default the running one
    local pkgbase
    pkgbase=$(imac_kernel_pkgbase "${1:-$(uname -r)}") || return 1
    printf '/boot/EFI/Linux/omarchy_%s.efi\n' "$pkgbase"
}
imac_kernel_uses_clang() {
    grep -qx 'CONFIG_CC_IS_CLANG=y' "/usr/lib/modules/${1:-$(uname -r)}/build/.config" 2>/dev/null
}
# One tool-to-package table for every module, so the startup installer and the
# per-module preflights name the same packages. Names follow DEPENDENCIES.md;
# anything unlisted is its own package name on both families.
imac_tool_package() {   # $1 = command name
    if imac_is_fedora; then
        case $1 in
            ld|strip|objcopy|ar|nm|objdump|readelf) echo binutils ;;
            modinfo|depmod|lsmod|modprobe) echo kmod ;;
            pahole)                 echo dwarves ;;
            iasl)                   echo acpica-tools ;;
            rpmbuild)               echo rpm-build ;;
            pactl)                  echo pulseaudio-utils ;;
            pw-cli|pw-dump)         echo pipewire-utils ;;
            wpctl|wireplumber)      echo wireplumber ;;
            kscreen-doctor)         echo kscreen ;;
            systemctl)              echo systemd ;;
            grub-mkconfig)          echo grub2-tools ;;
            hyprctl)                echo hyprland ;;
            ld.lld)                 echo lld ;;
            llvm-*)                 echo llvm ;;
            *)                      echo "$1" ;;
        esac
        return
    fi
    case $1 in
        gcc|make|ld|strip|objcopy|flex|bison) echo base-devel ;;
        modinfo|depmod|lsmod|modprobe) echo kmod ;;
        pactl)                  echo libpulse ;;
        pw-cli|pw-dump)         echo pipewire ;;
        wpctl|wireplumber)      echo wireplumber ;;
        kscreen-doctor)         echo kscreen ;;
        python3)                echo python ;;
        iasl)                   echo acpica ;;
        systemctl)              echo systemd ;;
        cargo)                  echo rust ;;
        grub-mkconfig)          echo grub ;;
        limine-mkinitcpio)      echo limine-mkinitcpio-hook ;;
        hyprctl)                echo hyprland ;;
        ld.lld)                 echo lld ;;
        llvm-*)                 echo llvm ;;
        *)                      echo "$1" ;;
    esac
}
# The install command for this distribution, as a word list for `read -ra`.
# Fedora never falls back to a pacman that happens to be installed.
imac_pkg_installer() {
    if imac_is_fedora; then
        command -v dnf >/dev/null && { echo "sudo dnf install -y"; return 0; }
    elif command -v pacman >/dev/null; then echo "sudo pacman -S --needed --noconfirm"; return 0
    elif command -v dnf >/dev/null; then echo "sudo dnf install -y"; return 0
    fi
    return 1
}
# The headers/development package for a kernel, which carries no command of its
# own and so never shows up in the tool scan.
imac_kernel_headers_package() {   # $1 = kernel release, default the running one
    local krel=${1:-$(uname -r)} pkgbase
    if imac_is_fedora; then printf 'kernel-devel-%s\n' "$krel"; return 0; fi
    pkgbase=$(imac_kernel_pkgbase "$krel") || return 1
    printf '%s-headers\n' "$pkgbase"
}
imac_require_limine() {
    if imac_is_fedora || [[ ! -f /etc/default/limine ]]; then
        echo "This helper requires an Omarchy/Limine installation. On Fedora use imac-patcher --apply/--remove 5k." >&2
        exit 1
    fi
}
