#!/usr/bin/env bash
#
# patch-imac5k-amdgpu.sh — build a 5K-patched amdgpu module for the CURRENTLY
# running kernel and swap it in, WITHOUT installing a second kernel.
#
# What it does:
#   1. Fetches kernel source matching your running kernel version
#   2. Applies the iMac 5K patch stack (wake + stitch + genlock)
#   3. Builds ONLY the amdgpu module (against your kernel's own config +
#      Module.symvers, so it loads into the running kernel)
#   4. Backs up the stock amdgpu.ko and installs the patched one
#   5. Rebuilds the initramfs and adds `amdgpu.tiled_stitch=1`
#
# Re-run it after a kernel update to rebuild for the new kernel.
#   Restore the stock module any time with:  sudo ./patch-imac5k-amdgpu.sh --restore
#
# ── HONEST LIMITS — READ THESE ─────────────────────────────────────────────
# * The patch is version-specific. It is verified for kernels 7.1.x-7.2.x. On a kernel
#   whose amdgpu source differs enough (e.g. a future 7.3+), the patch will
#   FAIL TO APPLY and this script aborts cleanly without touching anything.
#   That case needs a human to re-port the patch — it is not a "just re-run" fix.
# * This replaces a core GPU module on your real system. If the built module
#   fails to load, you get software rendering until you --restore (your desktop
#   still boots). TEST ON THE USB CLONE FIRST, never first on your only install.
# * Needs ~8 GB free and 20–40 min of compile time (amdgpu/display is large).
# ───────────────────────────────────────────────────────────────────────────
set -euo pipefail

PATCH_KVER_SUPPORTED="7.1 7.2"   # kernel series this patch is verified to apply to
SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
source "${SCRIPT_DIR}/lib/platform.sh"
if imac_is_fedora; then
    exec "${SCRIPT_DIR}/fedora-imac5k" "$@"
fi
# Two Arch-family backends: Limine (Omarchy) and GRUB. GRUB edits the cmdline
# in /etc/default/grub + grub-mkconfig instead of limine-entry-tool drop-ins.
GRUB=0
if imac_has_limine; then
    :
elif imac_is_arch_grub; then
    GRUB=1
    source "${SCRIPT_DIR}/lib/grub.sh"
else
    echo "This installer needs an Omarchy/Limine or Arch-family GRUB installation." >&2
    echo "On Fedora use: imac-patcher --apply 5k" >&2
    exit 1
fi
# Which stack to build. "lean" (default since 2026-09-07): the lean core (the
# upstream candidate) plus the stitch layer -- same features as the verbose
# stack minus its logging -- plus the post-commit link-health recovery that
# repairs a tile losing DP link lock during the boot modeset (the "stretched
# 5K desktop" fix, promoted to the default on 2026-09-08 after a passing boot).
# "verbose": the original full-stack patch plus the follow-up patches, kept as
# a fallback (IMAC5K_STACK=verbose).
IMAC5K_STACK="${IMAC5K_STACK:-lean}"
case "$IMAC5K_STACK" in
lean)
	PATCH_FILE="${SCRIPT_DIR}/../patches/imac5k-lean-core-7.2.x.patch"
	EXTRA_PATCHES=("${SCRIPT_DIR}/../patches/imac5k-stitch-layer-7.x.patch" "${SCRIPT_DIR}/../patches/5k-going-down-stop-resync.patch" "${SCRIPT_DIR}/../patches/5k-post-commit-link-recovery.patch"
		# iMac Pro (iMacPro1,1, Vega 10 / DCE 12). Each is gated on the Apple
		# panel ID or on DCE 12, so the iMac18,3 (Polaris / DCE 11.2) build
		# is unchanged by them. See patches/README.md, "iMac Pro".
		"${SCRIPT_DIR}/../patches/imacpro-slave-dp-panel-mode.patch"
		"${SCRIPT_DIR}/../patches/dce120-enable-crtc-reset.patch"
		"${SCRIPT_DIR}/../patches/dce12-multisync-master-first.patch"
		"${SCRIPT_DIR}/../patches/dce110-genlock-master-from-pipe0.patch"
		# A modeset postpones the queued post-commit pass; see the patch header.
		"${SCRIPT_DIR}/../patches/5k-resync-postpone-on-modeset.patch")
	;;
verbose)
	PATCH_FILE="${SCRIPT_DIR}/../patches/imac5k-amdgpu-7.2.2.patch"
	# Applied in order, on top of PATCH_FILE. Each must apply cleanly or we abort.
	EXTRA_PATCHES=("${SCRIPT_DIR}/../patches/5k-early-modeset.patch" "${SCRIPT_DIR}/../patches/5k-genlock-deterministic.patch" "${SCRIPT_DIR}/../patches/5k-genlock-settle-resync.patch" "${SCRIPT_DIR}/../patches/5k-latch-clear.patch" "${SCRIPT_DIR}/../patches/5k-latch-clear-going-down-only.patch" "${SCRIPT_DIR}/../patches/5k-slave-link-verify-retrain.patch" "${SCRIPT_DIR}/../patches/5k-slave-link-preserve-lock.patch" "${SCRIPT_DIR}/../patches/5k-going-down-stop-resync.patch" "${SCRIPT_DIR}/../patches/5k-post-commit-link-recovery.patch")
	;;
*) echo "IMAC5K_STACK must be 'lean' or 'verbose'" >&2; exit 1 ;;
esac
WORK="${IMAC5K_WORK:-/home/${SUDO_USER:-$USER}/.cache/kernel-5k-build}"
KREL="$(uname -r)"                        # e.g. 7.2.2-arch1-1
KVER="${KREL%%-*}"                        # e.g. 7.2.2
KSERIES="${KVER%.*}"                      # e.g. 7.2
MODDIR="/usr/lib/modules/${KREL}/kernel/drivers/gpu/drm/amd/amdgpu"
BUILDLINK="/usr/lib/modules/${KREL}/build"

say()  { printf '\033[1;33m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;31m!!\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "run with sudo: sudo $0 ${*:-}"

if ((GRUB)); then
	command -v mkinitcpio >/dev/null || die "install mkinitcpio first (this GRUB backend requires mkinitcpio presets)"
	command -v grub-mkconfig >/dev/null || die "install the grub package first"
	grub_read_cmdlines || die "unsupported GRUB command-line configuration; nothing installed"
	grub_require_layout || die "unsupported or stale GRUB boot layout"
fi

# ── restore mode ───────────────────────────────────────────────────────────
find_amdgpu() { find "$(dirname "$MODDIR")" -maxdepth 2 \( -name amdgpu.ko -o -name amdgpu.ko.zst -o -name amdgpu.ko.xz \) 2>/dev/null | head -1; }
if [[ "${1:-}" == "--restore" ]]; then
	AMDKO="$(find_amdgpu)" || true
	BAK="${AMDKO}.stock-backup"
	[[ -f "$BAK" ]] || die "no backup found at ${BAK} — nothing to restore"
	say "restoring stock amdgpu module"
	cp -v "$BAK" "$AMDKO"
	depmod "$KREL"
	if ((GRUB)); then
		grub_cmdline_remove 'amdgpu.tiled_stitch=1'
	elif [[ -f /etc/limine-entry-tool.d/imac5k-stitch.conf ]]; then
		say "removing the amdgpu.tiled_stitch drop-in"
		rm -f /etc/limine-entry-tool.d/imac5k-stitch.conf
	fi
	say "rebuilding initramfs"
	if ((GRUB)); then mkinitcpio -P; grub_regen
	elif command -v limine-mkinitcpio >/dev/null; then limine-mkinitcpio; else mkinitcpio -P; fi
	say "done — reboot to run the stock module."
	exit 0
fi

# ── sanity / version gate ──────────────────────────────────────────────────
imac_is_retina5k || die "This driver targets Retina 5K iMacs (detected: $(imac_product_name))."
imac_has_amdgpu || die "The 5K display patch requires a GPU using amdgpu."
[[ -f "$PATCH_FILE" ]] || die "patch not found: $PATCH_FILE"
say "running kernel: ${KREL}  (source version ${KVER}, series ${KSERIES})"
if [[ " ${PATCH_KVER_SUPPORTED} " != *" ${KSERIES} "* ]]; then
	cat >&2 <<EOF
$(printf '\033[1;31mABORT:\033[0m') this patch is verified for kernel series ${PATCH_KVER_SUPPORTED} but you are on ${KVER}.
It will not apply to a different amdgpu source and would produce a broken module.
This needs the patch re-ported to ${KSERIES}.x first (a human step, not a re-run).
Nothing was changed.
EOF
	exit 1
fi

command -v gcc >/dev/null || die "install build tools first:  pacman -S --needed base-devel bc cpio pahole"
[[ -e "$BUILDLINK/Module.symvers" ]] || die "install kernel headers first:  pacman -S $(imac_kernel_pkgbase "$KREL")-headers  (needed so the module matches this kernel)"
MAKE_ARGS=()
if ((GRUB)) && imac_kernel_uses_clang "$KREL"; then
	for tool in clang ld.lld llvm-ar llvm-nm llvm-objcopy llvm-objdump llvm-readelf llvm-strip; do
		command -v "$tool" >/dev/null || die "missing $tool — install clang llvm lld for this kernel"
	done
	MAKE_ARGS+=(LLVM=1)
fi

# ── fetch matching kernel source (for the driver .c files) ─────────────────
mkdir -p "$WORK"; cd "$WORK"
SRC="linux-${KVER}"
if [[ ! -d "$SRC" ]]; then
	say "downloading kernel ${KVER} source"
	MAJ="${KVER%%.*}"
	curl -fL --retry 3 -o "${SRC}.tar.xz" \
		"https://cdn.kernel.org/pub/linux/kernel/v${MAJ}.x/${SRC}.tar.xz" \
		|| die "could not download ${SRC}.tar.xz from kernel.org"
	say "extracting"
	tar -xf "${SRC}.tar.xz"
fi
cd "$SRC"

# ── configure to match the running kernel exactly (vermagic + symbols) ─────
say "configuring to match the running kernel"
if ((GRUB)); then
	# CachyOS and other custom kernels change configuration and internal ABI.
	# Use their prepared Kbuild tree directly, including Clang/LTO settings.
	# Regenerating a kernel.org .config can silently discard those settings.
	BUILTREL="$(make "${MAKE_ARGS[@]}" -s -C "$BUILDLINK" kernelrelease)"
else
cp "$BUILDLINK/.config" .config
cp "$BUILDLINK/Module.symvers" Module.symvers 2>/dev/null || true
# Arch's kernel release is e.g. 7.2.2-arch1-1 while kernel.org source builds
# as plain 7.2.2 -- write the suffix into a localversion file so the built
# module's vermagic matches `uname -r` exactly (else it refuses to load).
KSUFFIX="${KREL#"$KVER"}"                 # e.g. -arch1-1
printf '%s' "$KSUFFIX" > localversion
scripts/config --disable LOCALVERSION_AUTO 2>/dev/null || true
scripts/config --set-str LOCALVERSION "" 2>/dev/null || true
make olddefconfig >/dev/null
BUILTREL="$(make -s kernelrelease)"
fi
[[ "$BUILTREL" == "$KREL" ]] || die "computed kernelrelease '$BUILTREL' != running '$KREL' — refusing to build a module that won't load"
say "kernelrelease matches running kernel: $BUILTREL"

# ── apply the 5K patch stack (idempotent: skip if already applied) ─────────
# Idempotency is tracked with a stamp per patch rather than a reverse-apply
# dry-run: once two patches touch the same context, reversing the first one no
# longer matches and a correctly-patched tree looks unpatched. The stamp records
# the patch content hash, so editing a patch re-applies it on the next run.
STAMPDIR=".imac5k-applied"
apply_patch() {          # apply_patch <file> <label>
	local f="$1" label="$2" sum stamp
	[[ -f "$f" ]] || die "patch not found: $f"
	sum="$(sha256sum "$f" | cut -c1-16)"
	stamp="${STAMPDIR}/$(basename "$f").${sum}"
	mkdir -p "$STAMPDIR"

	if [[ -f "$stamp" ]]; then
		say "${label} already applied — reusing"
		return
	fi
	if patch -p1 --dry-run --force < "$f" >/dev/null 2>&1; then
		say "applying ${label}"
		patch -p1 < "$f"
		touch "$stamp"
		return
	fi
	die "${label} did not apply cleanly to ${KVER} source. It likely needs re-porting for this kernel. Nothing installed. If this tree was patched by an older version of this script, delete it and re-run:  rm -rf ${WORK}/${SRC}"
}

apply_patch "$PATCH_FILE" "iMac 5K patch stack"
for extra in "${EXTRA_PATCHES[@]}"; do
	apply_patch "$extra" "$(basename "$extra")"
done

# ── build just the amdgpu module ───────────────────────────────────────────
say "building amdgpu module — this is the slow part (~20-40 min)"
if ((GRUB)); then
	make "${MAKE_ARGS[@]}" -C "$BUILDLINK" -j"$(nproc)" \
		M="$PWD/drivers/gpu/drm/amd/amdgpu" \
		"CFLAGS_amdgpu_trace_points.o=-I$PWD/include/trace" modules \
		|| die "module build failed against the installed kernel headers"
else
make modules_prepare >/dev/null
make -j"$(nproc)" M=drivers/gpu/drm/amd/amdgpu modules \
	|| make -j"$(nproc)" drivers/gpu/drm/amd/amdgpu/amdgpu.ko \
	|| die "module build failed"
fi

BUILT="$(find drivers/gpu/drm/amd/amdgpu -name amdgpu.ko | head -1)"
[[ -f "$BUILT" ]] || die "built amdgpu.ko not found"

# quick sanity: vermagic must match the running kernel or it won't load
VM="$(modinfo -F vermagic "$BUILT" 2>/dev/null | awk '{print $1}')"
[[ "$VM" == "$KREL" ]] || die "built vermagic '$VM' != running '$KREL' — refusing to install"
if ((GRUB)); then
	EXPECTED_VM="$(modinfo -k "$KREL" -F vermagic amdgpu)"
	[[ "$(modinfo -F vermagic "$BUILT")" == "$EXPECTED_VM" ]] \
		|| die "built module ABI flags differ from the installed kernel — refusing to install"
fi

# ── install (compressed to match Arch's .ko.zst) with a stock backup ───────
AMDKO="$(find_amdgpu)" || die "stock amdgpu module not found under $MODDIR"
BAK="${AMDKO}.stock-backup"
[[ -f "$BAK" ]] || { say "backing up stock module -> $BAK"; cp "$AMDKO" "$BAK"; }

say "stripping debug info (matches stock packaging)"
strip --strip-debug "$BUILT"

say "installing patched amdgpu module"
case "$AMDKO" in
	*.zst) zstd -q -f -19 "$BUILT" -o "$AMDKO" ;;
	*.xz)  xz  -c "$BUILT" > "$AMDKO" ;;
	*)     cp "$BUILT" "$AMDKO" ;;
esac
depmod "$KREL"

# ── add the boot parameter ─────────────────────────────────────────────────
# Omarchy assembles the cmdline from /etc/default/limine PLUS every
# /etc/limine-entry-tool.d/*.conf drop-in, and every piece it ships appends
# with `+=` rather than assigning with `=`. An earlier version of this script
# sed'd for `KERNEL_CMDLINE[default]="..."` in /etc/default/limine only: on a
# stock Omarchy install that pattern matches nothing, the substitution was a
# silent no-op, and the parameter never reached the cmdline -- while the next
# run's grep, looking in the same one file, kept reporting it as missing.
# Write our own drop-in instead, the way Omarchy's own hardware quirks do.
# On GRUB the equivalent is GRUB_CMDLINE_LINUX_DEFAULT in /etc/default/grub,
# applied by grub-mkconfig (grub_cmdline_add does both).
if ((GRUB)); then
	grub_cmdline_add 'amdgpu.tiled_stitch=1' || die "could not set amdgpu.tiled_stitch=1 in the GRUB cmdline"
else
	LIMINE_DROPIN_DIR=/etc/limine-entry-tool.d
	STITCH_DROPIN="${LIMINE_DROPIN_DIR}/imac5k-stitch.conf"
	if grep -qs 'amdgpu.tiled_stitch=1' /etc/default/limine "$LIMINE_DROPIN_DIR"/*.conf; then
		say "amdgpu.tiled_stitch=1 already in the boot config"
	else
		say "adding amdgpu.tiled_stitch=1 to the default cmdline ($STITCH_DROPIN)"
		mkdir -p "$LIMINE_DROPIN_DIR"
		cat > "$STITCH_DROPIN" <<'DROPIN'
# Written by imac-patcher (iMac native 5K). Delete this file to drop the
# parameter, or run: imac-patcher --remove 5k
KERNEL_CMDLINE[default]+=" amdgpu.tiled_stitch=1"
DROPIN
	fi
fi

say "rebuilding initramfs (bakes the patched module in)"
if ((GRUB)); then mkinitcpio -P; grub_regen
elif command -v limine-mkinitcpio >/dev/null; then limine-mkinitcpio; else mkinitcpio -P; fi

if (( ! GRUB )); then

# Remove shadowing limine.conf copies. Limine >= 10.3.0 loads the FIRST config
# in its search order, so a copy at EFI/limine/ or EFI/BOOT/ overrides
# /boot/limine.conf -- the file limine-mkinitcpio actually maintains. Earlier
# versions of this script created them; `limine-install` flags them as
# conflicts and says to delete them.
for shadow in /boot/EFI/limine/limine.conf /boot/EFI/BOOT/limine.conf \
	/boot/boot/limine/limine.conf /boot/limine/limine.conf; do
	[[ -f $shadow ]] || continue
	say "removing shadowing config $shadow"
	rm -f "$shadow"
done

# Refresh the fallback boot path too. On this machine \EFI\BOOT\BOOTX64.EFI is a
# COPY of the UKI (an earlier bypass of Limine), not the Limine binary — so if
# the firmware takes the fallback path it boots whatever UKI was current when
# that copy was made. Leaving it stale means booting the previous initramfs,
# with the previous amdgpu module baked in, and wondering why nothing changed.
# Only refresh it when it really is a UKI copy; never clobber a Limine binary.
UKI="$(imac_default_uki "$KREL")"
FALLBACK=/boot/EFI/BOOT/BOOTX64.EFI
# NB: `objcopy --only-section=X` exits 0 even when section X is absent -- it
# writes nothing. Testing its exit status classifies every PE binary as a UKI,
# which on a stock ESP means overwriting Limine with a kernel image.
if [[ -f "$UKI" && -f "$FALLBACK" ]]; then
	probe="$(mktemp)"
	objcopy -O binary --only-section=.cmdline "$FALLBACK" "$probe" 2>/dev/null || true
	if [[ -s $probe ]] && ! cmp -s "$UKI" "$FALLBACK"; then
		say "refreshing UKI-bypass fallback $FALLBACK from the new UKI"
		cp -f "$UKI" "$FALLBACK"
	fi
	rm -f "$probe"
fi
fi
sync

cat <<EOF

$(printf '\033[1;32mDONE.\033[0m') Patched amdgpu built for ${KREL} and installed.
Stock module backed up at: ${BAK}
Reboot to load it. Your compositor (Hyprland) must run for the single 5K output.

If anything looks wrong after reboot:  sudo $0 --restore
Re-run this script after any kernel update to rebuild for the new kernel
(it will refuse cleanly if the patch no longer applies to that version).
EOF
