#!/usr/bin/env bash
# Shared Debian/Ubuntu graphics build and transactional install/restore.
# Build without root; only installation/restoration use sudo.
set -Eeuo pipefail
export PATH="/usr/sbin:/sbin:$PATH"
source "$SCRIPT_DIR/lib/grub.sh"
source "$SCRIPT_DIR/lib/apt-platform.sh"
imac_apt_configure "$IMAC_APT_DISTRO" || return 1
KREL=$(uname -r)
KSERIES=${KREL#*.}; KSERIES=${KREL%%.*}.${KSERIES%%.*}
WORK=${IMAC5K_WORK:-${HOME}/.cache/kernel-5k-build/${IMAC_APT_DISTRO}-${KREL}}
BUILD=/lib/modules/${KREL}/build
DEST=/lib/modules/${KREL}/updates/imac5k/amdgpu.ko.xz
DEPMOD_CONF=/etc/depmod.d/imac5k-${KREL}.conf
STATE=/var/lib/imac-patcher/5k-${KREL}
INITRD=/boot/initrd.img-${KREL}
KERNEL=/boot/vmlinuz-${KREL}
ENTRY=/etc/grub.d/09_imac5k-${KREL}
# initramfs-tools accepts dots and dashes in hook names, but skips a '+' —
# present in Debian 13's ABI names. The hook still checks the exact release.
INITRAMFS_HOOK=/etc/initramfs-tools/hooks/imac5k-${KREL//+/_}
say() { printf '==> %s\n' "$*"; }
warn() { printf 'ERROR: %s\n' "$*" >&2; }
die() { warn "$*"; exit 1; }
need_root() { [[ $EUID == 0 ]] || die "Use sudo for $1."; }
need_tools() {
    local tool
    for tool in "$@"; do command -v "$tool" >/dev/null || die "Missing $tool; see ${IMAC_APT_GUIDE} for APT dependencies."; done
}
supported_kernel() { imac_apt_kernel_supported; }
source_version() { imac_apt_read_source && printf '%s\n' "$IMAC_APT_SOURCE_VERSION"; }
check_signing() {
    local lockdown status
    lockdown=$(cat /sys/kernel/security/lockdown 2>/dev/null || true)
    status=$(mokutil --sb-state 2>/dev/null || true)
    if [[ $lockdown == *'[integrity]'* || $lockdown == *'[confidentiality]'* ||
          $status == *'SecureBoot enabled'* || -n ${IMAC5K_SIGN_KEY:-}${IMAC5K_SIGN_CERT:-} ]]; then
        [[ -f ${IMAC5K_SIGN_KEY:-} && -f ${IMAC5K_SIGN_CERT:-} ]] ||
            die "Module signing required: set IMAC5K_SIGN_KEY and IMAC5K_SIGN_CERT to an enrolled key and DER certificate. See ${IMAC_APT_GUIDE}."
        [[ -x $BUILD/scripts/sign-file ]] || die "Matching headers lack scripts/sign-file."
        mokutil --test-key "$IMAC5K_SIGN_CERT" >/dev/null || die "Signing certificate is not enrolled; enroll it and reboot first."
    fi
}
check_layout() {
    imac_has_grub && ! imac_has_limine || die "${IMAC_APT_NAME} 5K requires GRUB with /etc/default/grub; Limine/UKI layouts are unsupported."
    [[ -f $KERNEL && -f $INITRD ]] || die "Missing ${IMAC_APT_NAME} kernel or initramfs for ${KREL} under /boot."
    grub_kernel_entry "${KERNEL##*/}" "${INITRD##*/}" imac-patcher-5k- >/dev/null || die "No normal GRUB entry for ${KREL}; run sudo update-grub and retry."
}
check() {
    supported_kernel || die "${IMAC_APT_NAME} 5K supports $IMAC_APT_SERIES; ${KREL} needs a patch port."
    need_tools gcc make ld strip bc pahole flex bison patch xz tar apt-get dpkg-query dpkg-deb python3 modinfo depmod mkinitramfs lsinitramfs grub-mkconfig mokutil flock
    [[ $IMAC_APT_DISTRO != ubuntu ]] || need_tools bzip2
    [[ -f $BUILD/Module.symvers && -f $BUILD/.config ]] || die "Install matching headers: sudo apt-get install linux-headers-${KREL}"
    # Ubuntu's installed Makefile can report the upstream stable version for
    # `make kernelrelease` (7.0.14), while its generated module ABI is the
    # packaged release (7.0.0-38-generic). Kbuild uses UTS_RELEASE for vermagic.
    grep -qxF "#define UTS_RELEASE \"$KREL\"" "$BUILD/include/generated/utsrelease.h" || die "Installed headers do not match ${KREL}."
    source_version >/dev/null || die "Cannot identify the exact ${IMAC_APT_NAME} source version from the headers."
    check_signing
    check_layout
    say "${IMAC_APT_NAME} ${KREL}: build prerequisites present."
}
patch_stack() {
    supported_kernel || die "Unsupported kernel: $KREL"
    if [[ $KSERIES == 6.12 ]]; then
        [[ ${IMAC5K_STACK:-lean} == lean ]] || die "${IMAC_APT_NAME} 6.12 supports the lean stack only."
        printf '%s\n' imac5k-debian-6.12.patch
    elif [[ $KSERIES == 7.0 ]]; then
        [[ ${IMAC5K_STACK:-lean} == lean ]] || die "Ubuntu 7.0 supports the lean stack only."
        printf '%s\n' imac5k-ubuntu-7.0.patch
    else
        [[ ${IMAC5K_STACK:-lean} == lean ]] || die "The APT backend supports the lean stack only."
        printf '%s\n' imac5k-lean-core-7.2.x.patch imac5k-stitch-layer-7.x.patch \
            5k-going-down-stop-resync.patch 5k-post-commit-link-recovery.patch \
            5k-logical-modeset-guard.patch 5k-resume-drop-cached-peer.patch 5k-resume-arm-link-health.patch \
            imacpro-slave-dp-panel-mode.patch dce120-enable-crtc-reset.patch \
            dce12-multisync-master-first.patch dce110-genlock-master-from-pipe0.patch 5k-resync-postpone-on-modeset.patch \
            5k-root-plane-zero-width-guard.patch
    fi
}
validate_module() {
    local actual expected params
    [[ -f $1 ]] || die "Module not found: $1"
    expected=$(modinfo -k "$KREL" -F vermagic amdgpu)
    actual=$(modinfo -F vermagic "$1")
    [[ ${actual%% *} == "$KREL" && $actual == "$expected" ]] || die "Module vermagic does not match the running ${IMAC_APT_NAME} kernel."
    [[ $(modinfo -F name "$1") == amdgpu ]] || die "Expected an amdgpu module."
    params=$(modinfo -F parm "$1")
    [[ $params == *'tiled_stitch:'* ]] || die "Module lacks the tiled_stitch parameter."
}
build_module() (
    [[ $EUID != 0 ]] || die "Build as your normal user: scripts/${IMAC_APT_HELPER} --build."
    check
    local version package stage src module f source_package
    local patches=() make_args=()
    imac_apt_read_source || die "Cannot identify matching kernel sources."
    version=$IMAC_APT_SOURCE_VERSION
    source_package=$IMAC_APT_SOURCE
    package=$(imac_apt_source_binary)
    mapfile -t patches < <(patch_stack)
    ((${#patches[@]})) || die "No patch stack selected."
    mkdir -p "$WORK"
    WORK=$(realpath "$WORK")
    exec {build_lock}>"$WORK/.build.lock"
    flock -n "$build_lock" || die "Another graphics build is using $WORK."
    python3 - "$WORK" <<'PY'
import shutil, sys
if shutil.disk_usage(sys.argv[1]).free < 10 * 1024**3:
    sys.exit('At least 10 GiB free in IMAC5K_WORK is required.')
PY
    stage=$(mktemp -d "$WORK/build.XXXXXX")
    trap 'rm -rf -- "$stage"' EXIT
    say "Downloading exact ${IMAC_APT_NAME} source: ${package}=${version}"
    # APT verifies the package against signed repository metadata. No deb-src
    # setup or root is needed, and an older running ABI never uses latest source.
    (cd "$stage"; apt-get download "${package}=${version}") || die "Matching source is unavailable. Update ${IMAC_APT_NAME}, reboot, and retry; a newer source package is not a substitute."
    local debs=("$stage"/*.deb)
    ((${#debs[@]} == 1)) && [[ -f ${debs[0]} ]] || die "Expected one source package."
    [[ $(dpkg-deb -f "${debs[0]}" Package) == "$package" && $(dpkg-deb -f "${debs[0]}" Version) == "$version" ]] || die "Downloaded source package metadata does not match the headers."
    local owner
    owner=$(dpkg-deb -f "${debs[0]}" Source)
    [[ $owner == "$source_package" || $owner == "$source_package ($version)" ]] || die "Downloaded source belongs to $owner, not $source_package."
    dpkg-deb -x "${debs[0]}" "$stage/package"
    local archives=("$stage/package/usr/src/${package}.tar."*)
    ((${#archives[@]} == 1)) && [[ -f ${archives[0]} ]] || die "Expected one kernel source archive in $package."
    tar -xf "${archives[0]}" -C "$stage"
    src=$stage/$package
    [[ -f $src/drivers/gpu/drm/amd/amdgpu/Makefile ]] || die "Unexpected source archive layout in $package."
    for f in "${patches[@]}"; do
        say "Applying $f"
        patch -d "$src" -p1 --batch --forward --fuzz=0 --dry-run < "$SCRIPT_DIR/../patches/$f"
        patch -d "$src" -p1 --batch --forward --fuzz=0 < "$SCRIPT_DIR/../patches/$f"
    done
    if imac_kernel_uses_clang "$KREL"; then
        need_tools clang ld.lld llvm-ar llvm-nm llvm-objcopy llvm-objdump llvm-readelf llvm-strip
        make_args+=(LLVM=1)
    fi
    say "Building amdgpu against ${IMAC_APT_NAME}'s exact headers and symbol versions"
    make "${make_args[@]}" -C "$BUILD" -j"${IMAC5K_JOBS:-$(nproc)}" M="$src/drivers/gpu/drm/amd/amdgpu" \
        "CFLAGS_amdgpu_trace_points.o=-I$src/include/trace" modules
    module=$src/drivers/gpu/drm/amd/amdgpu/amdgpu.ko
    validate_module "$module"
    install -m644 "$module" "$WORK/amdgpu.ko"
    say "Built: $WORK/amdgpu.ko"
)
prepare_entry() {
    # Copy GRUB's root/encryption/microcode setup, including paths for a
    # separate /boot or btrfs. Only this entry gets the patched-only parameter;
    # adding it globally would stop stock fallback kernels loading amdgpu.
    grub_kernel_entry "${KERNEL##*/}" "${INITRD##*/}" imac-patcher-5k- | python3 -c '
import re, sys
krel = sys.argv[1]
lines = sys.stdin.read().splitlines()
if not lines or not re.fullmatch(r"[a-zA-Z0-9._+\-]+", krel):
    sys.exit("Invalid kernel entry")
header = re.sub(r"^\s*menuentry\s+([\x27\x22]).*?\1", "menuentry \x27iMac 5K - " + krel + "\x27", lines[0], count=1)
header = re.sub(r"\s+(?:\$menuentry_id_option|--id)\s+([\x27\x22]).*?\1", "", header)
header = re.sub(r"\s*\{\s*$", " --id \x27imac-patcher-5k-" + krel + "\x27 {", header)
if not header.startswith("menuentry \x27iMac 5K - "):
    sys.exit("Cannot retitle GRUB entry")
lines[0] = header
count = 0
for i, line in enumerate(lines):
    if re.match(r"\s*linux(?:efi)?\s", line):
        # Keep GRUB quoting and expansions verbatim. Display parameters have
        # no whitespace or quoting in grub-mkconfig output.
        line = re.sub(r"(?<!\S)(?:amdgpu\.tiled_stitch=\S+|video=eDP-1:\S+)(?=\s|$)", "", line)
        lines[i] = line.rstrip() + " amdgpu.tiled_stitch=1"
        count += 1
if count != 1:
    sys.exit("Expected one Linux command")
print("#!/bin/sh\nexec tail -n +3 \x22$0\x22")
print("\n".join(line for line in lines if not re.match(r"\s*savedefault(?:\s|$)", line)))
' "$KREL"
}
restore_stock_image() {
    local image
    image=$(mktemp "${INITRD}.restore.XXXXXX") || return 1
    if ! cp -p "$STATE/initramfs.stock" "$image" || ! mv -f "$image" "$INITRD"; then
        rm -f "$image"; warn "Restore $INITRD from $STATE/initramfs.stock before rebooting."; return 1
    fi
}
apt_grub_regen() {
    local generated result=0
    generated=$(mktemp "${GRUB_CFG}.imac-new.XXXXXX") || return 1
    if grub-mkconfig -o "$generated"; then mv -f "$generated" "$GRUB_CFG" || result=1
    else result=1; fi
    rm -f "$generated"
    return "$result"
}
rollback_install() {
    trap - ERR
    local result=0
    warn "Install failed; restoring the saved module selection, initramfs and GRUB menu."
    if ((previously_installed)); then
        cp -p "$tmp/module.previous" "$DEST" || result=1
        cp -p "$tmp/depmod.previous" "$DEPMOD_CONF" || result=1
        cp -p "$tmp/entry.previous" "$ENTRY" || result=1
        cp -p "$tmp/hook.previous" "$INITRAMFS_HOOK" || result=1
        cp -p "$tmp/initramfs.previous" "$INITRD" || result=1
    else
        restore_stock_image || result=1
        rm -f "$DEST" "$DEPMOD_CONF" "$ENTRY" "$INITRAMFS_HOOK" || result=1
    fi
    depmod "$KREL" || result=1
    cp -p "$tmp/grub.cfg.previous" "$GRUB_CFG" || result=1
    rm -f "${INITRD}.imac-new" || result=1
    if ((result)); then
        touch "$STATE/recovery-needed" || true
        warn "Automatic recovery incomplete; keep $STATE and retry --restore."
    else
        rm -f "$STATE/recovery-needed"
        ((previously_installed)) || rm -f "$STATE/installed"
    fi
    exit 1
}
install_module() (
    need_root --install
    supported_kernel || die "Unsupported kernel: $KREL"
    need_tools modinfo depmod mkinitramfs lsinitramfs grub-mkconfig xz strip mokutil flock python3
    validate_module "$1"
    check_signing
    check_layout
    mkdir -p "$STATE"
    exec {install_lock}>"$STATE/operation.lock"
    flock -n "$install_lock" || die "Another 5K operation is running for $KREL."
    [[ ! -e $STATE/recovery-needed ]] || die "Previous recovery is incomplete; run --restore first."
    if [[ ! -f $STATE/initramfs.stock ]]; then
        [[ ! -e $DEST && ! -e $DEPMOD_CONF && ! -e $ENTRY && ! -e $INITRAMFS_HOOK ]] || die "Unmanaged imac5k module/config already exists."
        cp -p "$INITRD" "$STATE/initramfs.stock"
    fi
    local tmp previously_installed=0
    tmp=$(mktemp -d)
    trap 'rm -rf -- "$tmp"' EXIT
    # A failed repair must retain the previously working patched installation,
    # while the first stock image remains available for explicit removal.
    if [[ -f $STATE/installed ]]; then
        cp -p "$DEST" "$tmp/module.previous"
        cp -p "$DEPMOD_CONF" "$tmp/depmod.previous"
        cp -p "$ENTRY" "$tmp/entry.previous"
        cp -p "$INITRAMFS_HOOK" "$tmp/hook.previous"
        cp -p "$INITRD" "$tmp/initramfs.previous"
        previously_installed=1
    fi
    cp -p "$GRUB_CFG" "$tmp/grub.cfg.previous"
    prepare_entry > "$tmp/entry"
    cp "$1" "$tmp/amdgpu.ko"
    strip --strip-debug "$tmp/amdgpu.ko"
    if [[ -n ${IMAC5K_SIGN_KEY:-} ]]; then
        "$BUILD/scripts/sign-file" sha256 "$IMAC5K_SIGN_KEY" "$IMAC5K_SIGN_CERT" "$tmp/amdgpu.ko"
    fi
    xz --check=crc32 --lzma2=dict=1MiB -c "$tmp/amdgpu.ko" > "$tmp/amdgpu.ko.xz"
    say "Recovery: boot another ${IMAC_APT_NAME} kernel, or sudo $0 --restore while running ${KREL}."
    trap rollback_install ERR
    touch "$STATE/recovery-needed"
    mkdir -p "${DEST%/*}" "${DEPMOD_CONF%/*}" "${INITRAMFS_HOOK%/*}"
    install -m644 "$tmp/amdgpu.ko.xz" "$DEST"
    printf 'override amdgpu %s updates/imac5k\n' "$KREL" > "$DEPMOD_CONF"
    depmod "$KREL"
    [[ $(realpath "$(modinfo -k "$KREL" -n amdgpu)") == "$(realpath "$DEST")" ]]
    # MODULES=most does not guarantee KMS drivers (e.g. a minimal installation
    # without the firmware package's hook). Persist this for future image
    # refreshes, but leave every other installed kernel's image unchanged.
    printf '%s\n' '#!/bin/sh' 'case "${1:-}" in prereqs) exit 0 ;; esac' \
        "[ \"\${version:-}\" = '$KREL' ] || exit 0" \
        '. /usr/share/initramfs-tools/hook-functions' 'manual_add_modules amdgpu' > "$tmp/hook"
    install -m755 "$tmp/hook" "$INITRAMFS_HOOK"
    mkinitramfs -o "$tmp/initramfs" "$KREL"
    lsinitramfs "$tmp/initramfs" | grep -E '(^|/)(usr/)?lib/modules/[^/]+/updates/imac5k/amdgpu\.ko(\.xz)?$' >/dev/null
    install -m600 "$tmp/initramfs" "${INITRD}.imac-new"
    mv -f "${INITRD}.imac-new" "$INITRD"
    install -m755 "$tmp/entry" "$ENTRY"
    apt_grub_regen
    grep -qF "imac-patcher-5k-${KREL}" "$GRUB_CFG"
    touch "$STATE/installed"
    rm -f "$STATE/recovery-needed"
    trap - ERR
    say "Installed. Reboot and select 'iMac 5K - ${KREL}' in GRUB."
    say "Other kernels keep their original arguments. Reapply after each kernel update."
)
restore_module() (
    need_root --restore
    need_tools depmod mkinitramfs grub-mkconfig flock
    [[ -f $STATE/initramfs.stock ]] || die "No 5K backup for ${KREL}; boot the patched kernel before restoring it."
    exec {install_lock}>"$STATE/operation.lock"
    flock -n "$install_lock" || die "Another 5K operation is running for $KREL."
    local result=0 rebuilt
    restore_stock_image || result=1
    rm -f "$DEST" "$DEPMOD_CONF" "$ENTRY" "$INITRAMFS_HOOK" || result=1
    depmod "$KREL" || result=1
    rebuilt=$(mktemp "${INITRD}.rebuild.XXXXXX") || return 1
    if ((result == 0)) && mkinitramfs -o "$rebuilt" "$KREL"; then
        mv -f "$rebuilt" "$INITRD" || result=1
    else result=1; fi
    rm -f "$rebuilt"
    apt_grub_regen || result=1
    if ((result)); then
        touch "$STATE/recovery-needed"
        warn "Restore incomplete; stock backup retained in $STATE. Retry --restore."
        return 1
    fi
    rm -f "$STATE/installed" "$STATE/recovery-needed"
    say "Stock amdgpu restored for ${KREL}. Reboot."
)
apt_imac5k_main() {
case ${1:-} in
    --help|-h) echo "Usage: $0 [--check | --build | --install MODULE | --restore]"; exit 0 ;;
    ''|--check|--build|--restore) (($# <= 1)) || die "Unexpected arguments." ;;
    --install) (($# == 2)) || die "--install requires a module path." ;;
    *) die "Unknown option: $1" ;;
esac
"imac_is_${IMAC_APT_DISTRO}" || die "This backend requires ${IMAC_APT_NAME} (not an ID_LIKE derivative)."
imac_is_retina5k || die "This driver targets Retina 5K iMacs (detected: $(imac_product_name))."
[[ $KREL =~ ^[a-zA-Z0-9][a-zA-Z0-9._+-]*$ ]] || die "Invalid kernel release."
[[ $EUID == 0 ]] || GRUB_SUDO=sudo
[[ ${1:-} == --restore ]] || imac_has_amdgpu || die "The 5K display patch requires a GPU using amdgpu."
case ${1:-} in
    --check) check ;;
    --build) build_module ;;
    --install) install_module "$2" ;;
    --restore) restore_module ;;
    '') build_module; sudo --preserve-env=IMAC5K_SIGN_KEY,IMAC5K_SIGN_CERT "$0" --install "$WORK/amdgpu.ko" ;;
esac
}
