#!/usr/bin/env bash
# Configuration and source-package rules for the supported APT distributions.
# The same initramfs/GRUB transaction is used on both; source ABIs are distinct.
imac_apt_configure() {
    IMAC_APT_DISTRO=$1
    IMAC_APT_DKMS_PACKAGES=()
    case $1 in
        debian)
            IMAC_APT_NAME=Debian
            IMAC_APT_SERIES='6.12 7.1 7.2'
            IMAC_APT_DKMS_CERT=/var/lib/dkms/mok.pub ;;
        ubuntu)
            IMAC_APT_NAME=Ubuntu
            IMAC_APT_SERIES='7.0 7.1 7.2'
            IMAC_APT_DKMS_PACKAGES=(zstd)
            IMAC_APT_DKMS_CERT=/var/lib/shim-signed/mok/MOK.der ;;
        *) printf 'Unsupported APT backend: %s\n' "$1" >&2; return 1 ;;
    esac
    IMAC_APT_HELPER=${1}-imac5k
    IMAC_APT_GUIDE=docs/${1}.md
}
imac_apt_kernel_supported() { [[ " $IMAC_APT_SERIES " == *" $KSERIES "* ]]; }
imac_apt_read_source() {
    local metadata status extra
    metadata=$(dpkg-query -W -f='${db:Status-Status} ${source:Package} ${source:Version}' "linux-headers-${KREL}") || return 1
    read -r status IMAC_APT_SOURCE IMAC_APT_SOURCE_VERSION extra <<< "$metadata"
    [[ $status == installed && -z $extra && $IMAC_APT_SOURCE_VERSION =~ ^[0-9][a-zA-Z0-9.+:~_-]*$ ]] || return 1
    if [[ $IMAC_APT_DISTRO == debian ]]; then
        [[ $IMAC_APT_SOURCE == linux ]] || { warn "Use Debian's headers built from its linux source package."; return 1; }
    else
        # Generic and HWE kernels have corresponding linux-source binary
        # packages. OEM, cloud, mainline PPA and third-party kernels need their
        # own source/ABI integration; ID_LIKE does not establish compatibility.
        [[ $KREL =~ ^[0-9]+\.[0-9]+\.[0-9]+-[0-9]+-generic$ ]] || {
            warn "Ubuntu 5K supports official generic/HWE kernels; ${KREL} is a different flavour."; return 1;
        }
        [[ $IMAC_APT_SOURCE == linux || $IMAC_APT_SOURCE =~ ^linux-hwe-[0-9]+\.[0-9]+$ ]] || {
            warn "Use Ubuntu's official generic/HWE headers, not ${IMAC_APT_SOURCE}."; return 1;
        }
    fi
}
imac_apt_source_binary() {
    if [[ $IMAC_APT_DISTRO == ubuntu ]]; then printf 'linux-source-%s\n' "${KREL%%-*}"
    else printf 'linux-source-%s\n' "$KSERIES"; fi
}
