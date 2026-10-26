#!/usr/bin/env bash
# Ubuntu package/kernel policy with shared APT module implementations.
IMAC_APT_DISTRO=ubuntu
source "$SCRIPT_DIR/lib/apt.sh"
# Keep DKMS registrations containing this backend's persistent source guard
# distinct from the existing driver version prepared on other distributions.
AUDIO_DKMS_VERSION=0.2.imac5k1.ubuntu1

# The pinned audio driver's Ubuntu path extracts the packaged sound/hda tree.
# Install the exact version and guard every later DKMS rebuild too: another
# ABI may have replaced /usr/src/linux-source-<base>.tar.bz2 in the meantime.
ubuntu_audio_source_deps() {
    local package version source metadata
    imac_apt_read_source || { warn "Cannot identify matching Ubuntu audio sources."; return 1; }
    package=$(imac_apt_source_binary)
    version=$IMAC_APT_SOURCE_VERSION
    source=$IMAC_APT_SOURCE
    apt_deps bzip2 || return 1
    metadata=$(dpkg-query -W -f='${db:Status-Status} ${source:Package} ${source:Version}' "$package" 2>/dev/null) || metadata=
    if [[ $metadata != "installed $source $version" ]]; then
        say "Required Ubuntu audio source: $package=$version"
        confirm "Install the exact matching source package with APT?" || return 1
        sudo apt-get install -y "$package=$version" || return 1
        metadata=$(dpkg-query -W -f='${db:Status-Status} ${source:Package} ${source:Version}' "$package") || metadata=
        [[ $metadata == "installed $source $version" ]] || { warn "Installed Ubuntu sources do not match the kernel headers."; return 1; }
    fi
}
audio_platform_prepare_source() {
    install -m755 "$SCRIPT_DIR/lib/ubuntu-audio-pre-build.sh" "$1/imac5k-ubuntu-pre-build" || return 1
    sed -i 's|^PRE_BUILD=.*$|PRE_BUILD="imac5k-ubuntu-pre-build $kernelver"|' "$1/dkms.conf"
}
