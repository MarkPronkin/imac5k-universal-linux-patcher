#!/usr/bin/env bash
# Shared GRUB helpers for Arch-family systems. Callers define say()/warn().
# Detection belongs to platform.sh; installed commands never choose a backend.
# GRUB_SUDO is empty in root-run helpers and "sudo" in the user-run patcher.
GRUB_DEFAULT_FILE=${GRUB_DEFAULT_FILE:-/etc/default/grub}
GRUB_CFG=${GRUB_CFG:-/boot/grub/grub.cfg}
GRUB_CUSTOM=${GRUB_CUSTOM:-/etc/grub.d/40_custom}
GRUB_BOOT_DIR=${GRUB_BOOT_DIR:-/boot}
GRUB_MODULES_DIR=${GRUB_MODULES_DIR:-/usr/lib/modules}
GRUB_PRESET_DIR=${GRUB_PRESET_DIR:-/etc/mkinitcpio.d}
GRUB_SUDO=${GRUB_SUDO:-}

grub_regen() {
    command -v grub-mkconfig >/dev/null || { warn "grub-mkconfig not found — install the grub package"; return 1; }
    $GRUB_SUDO grub-mkconfig -o "$GRUB_CFG"
}

# Read literal shell assignments without executing the configuration. Preserve
# quotes, indentation and comments; the final assignment to each variable wins.
# Refuse computed/multiline values rather than replacing boot-critical options.
grub_read_cmdlines() {
    local line value key i=0 prefix suffix quote
    local assignment='^([[:space:]]*(export[[:space:]]+)?(GRUB_CMDLINE_LINUX(_DEFAULT)?)=)(.*)$'
    local quoted="^([\"'])(.*)\\1([[:space:]]*(#.*)?)$"
    GRUB_LINES=(); GRUB_KEYS=(); GRUB_PREFIXES=(); GRUB_VALUES=(); GRUB_QUOTES=(); GRUB_SUFFIXES=()
    GRUB_LINUX=; GRUB_LINUX_DEFAULT=; GRUB_DEFAULT_INDEX=-1
    [[ -r $GRUB_DEFAULT_FILE ]] || { warn "cannot read $GRUB_DEFAULT_FILE"; return 1; }
    while IFS= read -r line || [[ -n $line ]]; do
        GRUB_LINES[i]=$line
        if [[ $line =~ $assignment ]]; then
            prefix=${BASH_REMATCH[1]}; key=${BASH_REMATCH[3]}; value=${BASH_REMATCH[5]}
            quote=; suffix=
            if [[ $value =~ $quoted ]]; then
                quote=${BASH_REMATCH[1]}; value=${BASH_REMATCH[2]}; suffix=${BASH_REMATCH[3]}
            elif [[ $value =~ ^([^[:space:]]*)([[:space:]]*(#.*)?)$ ]]; then
                value=${BASH_REMATCH[1]}; suffix=${BASH_REMATCH[2]}
            else
                warn "use a single literal assignment for $key in $GRUB_DEFAULT_FILE"; return 1
            fi
            # Embedded quotes/escapes need a shell parser, and expansions could
            # hide parameters. Never eval/source a file merely to edit it.
            if [[ $value == *"$quote"* && -n $quote ]] \
                || [[ $quote != "'" && ( $value == *'$'* || $value == *'`'* || $value == *'\'* || $value == *'"'* || $value == *"'"* || $value == *';'* ) ]]; then
                warn "computed or escaped $key is unsupported; use a literal quoted value in $GRUB_DEFAULT_FILE"; return 1
            fi
            GRUB_KEYS[i]=$key; GRUB_PREFIXES[i]=$prefix; GRUB_VALUES[i]=$value
            GRUB_QUOTES[i]=$quote; GRUB_SUFFIXES[i]=$suffix
            if [[ $key == GRUB_CMDLINE_LINUX_DEFAULT ]]; then
                GRUB_LINUX_DEFAULT=$value; GRUB_DEFAULT_INDEX=$i
            else
                GRUB_LINUX=$value
            fi
        fi
        i=$((i + 1))
    done < "$GRUB_DEFAULT_FILE"
}

grub_has_token() {
    local token words=()
    read -r -a words <<< "$1"
    for token in "${words[@]}"; do [[ $token == "$2" ]] && return 0; done
    return 1
}

grub_cmdline_has() {
    grub_read_cmdlines || return 1
    grub_has_token "$GRUB_LINUX $GRUB_LINUX_DEFAULT" "$1"
}

# Backups in grub.d must NOT be executable: grub-mkconfig otherwise runs them
# as additional generators and resurrects every old test entry.
grub_backup() {
    local file=$1 backup="$1.backup-$(date +%Y%m%d-%H%M%S-%N)"
    $GRUB_SUDO cp -aL "$file" "$backup" || return 1
    if [[ $file == "$GRUB_CUSTOM" ]]; then
        $GRUB_SUDO chmod a-x "$backup" || return 1
    fi
    printf '%s\n' "$backup"
}

# Commit a prepared file, regenerate, and restore both inputs and generated
# output on failure. A failed update must remain retryable.
grub_commit_file() {   # source, destination
    local src=$1 dest=$2 backup= cfg_backup= mode=
    command -v grub-mkconfig >/dev/null || { warn "install the grub package first"; return 1; }
    if [[ -f $dest ]]; then
        mode=$($GRUB_SUDO stat -Lc '%a' "$dest") || return 1
        backup=$(grub_backup "$dest") || return 1
    fi
    if [[ -f $GRUB_CFG ]]; then cfg_backup=$(grub_backup "$GRUB_CFG") || return 1; fi
    if $GRUB_SUDO cp "$src" "$dest" \
        && { [[ $dest != "$GRUB_CUSTOM" ]] || $GRUB_SUDO chmod 755 "$dest"; } \
        && grub_regen; then
        return 0
    fi
    if [[ -n $backup ]]; then
        $GRUB_SUDO cp "$backup" "$dest" || warn "restore $dest from $backup before rebooting"
        $GRUB_SUDO chmod "$mode" "$dest" || warn "restore the permissions of $dest before rebooting"
    else
        $GRUB_SUDO rm -f "$dest" || return 1
    fi
    if [[ -n $cfg_backup ]]; then
        $GRUB_SUDO cp "$cfg_backup" "$GRUB_CFG" || warn "restore $GRUB_CFG from $cfg_backup before rebooting"
    else
        $GRUB_SUDO rm -f "$GRUB_CFG" || return 1
    fi
    warn "GRUB update failed"
    return 1
}

grub_cmdline_edit() {   # add/remove, one literal kernel parameter
    local action=$1 param=$2 i value quote tmp words=() keep=()
    [[ $param =~ ^[a-zA-Z0-9_.=:/@,+-]+$ ]] || { warn "invalid kernel parameter: $param"; return 1; }
    grub_read_cmdlines || return 1
    if [[ $action == add ]]; then
        grub_has_token "$GRUB_LINUX $GRUB_LINUX_DEFAULT" "$param" && return 0
        if (( GRUB_DEFAULT_INDEX < 0 )); then
            GRUB_LINES+=("GRUB_CMDLINE_LINUX_DEFAULT=\"$param\"")
        else
            i=$GRUB_DEFAULT_INDEX
            value=${GRUB_VALUES[i]}
            quote=${GRUB_QUOTES[i]:-\"}
            GRUB_LINES[i]="${GRUB_PREFIXES[i]}${quote}${value:+$value }${param}${quote}${GRUB_SUFFIXES[i]}"
        fi
    else
        grub_has_token "$GRUB_LINUX $GRUB_LINUX_DEFAULT" "$param" || return 0
        for i in "${!GRUB_KEYS[@]}"; do
            keep=(); read -r -a words <<< "${GRUB_VALUES[i]}"
            for value in "${words[@]}"; do [[ $value == "$param" ]] || keep+=("$value"); done
            quote=${GRUB_QUOTES[i]:-\"}
            GRUB_LINES[i]="${GRUB_PREFIXES[i]}${quote}${keep[*]}${quote}${GRUB_SUFFIXES[i]}"
        done
    fi
    tmp=$(mktemp) || return 1
    printf '%s\n' "${GRUB_LINES[@]}" > "$tmp"
    local result=0
    grub_commit_file "$tmp" "$GRUB_DEFAULT_FILE" || result=$?
    rm -f "$tmp"
    ((result == 0)) || return "$result"
    say "$action $param in $GRUB_DEFAULT_FILE"
}
grub_cmdline_add() { grub_cmdline_edit add "$1"; }
grub_cmdline_remove() { grub_cmdline_edit remove "$1"; }

grub_entry_begin() { printf '# >>> imac-patcher test entry: %s >>>\n' "$1"; }
grub_entry_end()   { printf '# <<< imac-patcher test entry: %s <<<\n' "$1"; }
grub_entry_exists() { grep -qxF "$(grub_entry_begin "$1")" "$GRUB_CUSTOM" 2>/dev/null; }
grub_list_entries() {
    [[ -f $GRUB_CUSTOM ]] || return 0
    sed -n 's|^# >>> imac-patcher test entry: \(.*\) >>>$|\1|p' "$GRUB_CUSTOM"
}

# Select the normal entry for the running kernel's package, including entries
# inside submenus. The first entry may boot a different installed kernel.
# Retain GRUB's own root, encryption, subvolume and microcode paths.
grub_kernel_entry() {
    local pkgbase
    pkgbase=$(imac_kernel_pkgbase "${KREL:-$(uname -r)}") || return 1
    $GRUB_SUDO awk -v kernel="vmlinuz-$pkgbase" -v initrd="initramfs-$pkgbase.img" '
        /^[[:space:]]*menuentry[[:space:]]/ {
            block=""; linux=0; image=0; inside=1
            match($0, /^[[:space:]]*/); indent=substr($0, 1, RLENGTH)
        }
        inside {
            block=block $0 "\n"
            if ($1 == "linux" || $1 == "linuxefi") {
                path=$2; gsub(/[\047\042]/, "", path); sub(/^.*\//, "", path)
                linux=(path == kernel)
            }
            if ($1 == "initrd" || $1 == "initrdefi") {
                path=$NF; gsub(/[\047\042]/, "", path); sub(/^.*\//, "", path)
                image=(path == initrd)
            }
            if ($0 == indent "}") {
                if (linux && image) { printf "%s", block; found=1; exit }
                inside=0
            }
        }
        END { if (!found) exit 1 }
    ' "$GRUB_CFG"
}

grub_without_entry() {   # copy everything except one complete marker block
    awk -v b="$(grub_entry_begin "$1")" -v e="$(grub_entry_end "$1")" '
        $0 == b { if (skip) exit 1; skip=1; next }
        $0 == e { if (!skip) exit 1; skip=0; next }
        !skip { print }
        END { if (skip) exit 1 }
    ' "$GRUB_CUSTOM"
}

grub_clone_entry() {   # entry name, image installed beside the normal initramfs
    local name=$1 initrd=$2 block tmp pkgbase
    [[ $name =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$ ]] || { warn "invalid entry name"; return 1; }
    pkgbase=$(imac_kernel_pkgbase "${KREL:-$(uname -r)}") || return 1
    [[ $initrd == "$GRUB_BOOT_DIR/initramfs-$pkgbase-imac-$name.img" ]] || { warn "unexpected test image path: $initrd"; return 1; }
    block=$(grub_kernel_entry) || { warn "no normal $pkgbase kernel/initramfs entry in $GRUB_CFG"; return 1; }
    # Reuse the original initramfs directory as GRUB sees it (/ on a separate
    # /boot, /boot on ext4 root, /@/boot on btrfs). Linux's /boot is not portable.
    block=$(printf '%s\n' "$block" | sed -E \
        -e "1s|^[[:space:]]*menuentry[[:space:]]+['\"][^'\"]*['\"]|menuentry '/Test - $name'|" \
        -e "1s~[[:space:]]+(\\\$menuentry_id_option|--id)[[:space:]]+['\"][^'\"]*['\"]~~" \
        -e "1s|[[:space:]]*\\{[[:space:]]*$| --id 'imac-patcher-$pkgbase-$name' {|" \
        -e "/^[[:space:]]*savedefault([[:space:]]|$)/d") || return 1
    block=${block//"initramfs-$pkgbase.img"/"${initrd##*/}"}
    [[ $block == "menuentry '/Test - $name'"* ]] || { warn "could not retitle GRUB entry"; return 1; }
    tmp=$(mktemp) || return 1
    if [[ -f $GRUB_CUSTOM ]]; then
        if [[ $(sed -n '2p' "$GRUB_CUSTOM") != 'exec tail -n +3 $0' \
            && $(sed -n '2p' "$GRUB_CUSTOM") != 'exec tail -n +3 "$0"' ]]; then
            warn "$GRUB_CUSTOM lacks the stock 'exec tail -n +3 \$0' header"
            rm -f "$tmp"; return 1
        fi
        grub_without_entry "$name" > "$tmp" || { warn "incomplete test entry markers"; rm -f "$tmp"; return 1; }
    else
        printf '#!/bin/sh\nexec tail -n +3 $0\n' > "$tmp"
    fi
    { grub_entry_begin "$name"; printf '%s\n' "$block"; grub_entry_end "$name"; } >> "$tmp"
    local result=0
    grub_commit_file "$tmp" "$GRUB_CUSTOM" || result=$?
    rm -f "$tmp"
    ((result == 0)) || return "$result"
    say "added '/Test - $name' to $GRUB_CUSTOM"
}

grub_drop_entry() {
    local name=$1 tmp
    grub_entry_exists "$name" || return 0
    tmp=$(mktemp) || return 1
    grub_without_entry "$name" > "$tmp" || { warn "incomplete test entry markers"; rm -f "$tmp"; return 1; }
    local result=0
    grub_commit_file "$tmp" "$GRUB_CUSTOM" || result=$?
    rm -f "$tmp"
    ((result == 0)) || return "$result"
    say "removed '/Test - $name' from $GRUB_CUSTOM"
}

# Test images use the running package's regular /boot layout.
grub_image_path() {
    printf '%s/initramfs-%s-imac-%s.img' "$GRUB_BOOT_DIR" "$(imac_kernel_pkgbase "${KREL:-$(uname -r)}")" "$1"
}

# lsinitcpio skips prepended microcode archives correctly. bsdtar alone stops
# at the first cpio trailer. mkinitcpio may also store modules decompressed;
# normalize the recovered module to .ko.zst for both helper scripts.
grub_image_module() (
    set -o pipefail
    local image dest tmp module suffix
    image=$(realpath "$1") || return 1
    dest=$(realpath -m "$2") || return 1
    tmp=$(mktemp -d) || return 1
    trap 'rm -rf "$tmp"' EXIT
    cd "$tmp" || return 1
    lsinitcpio --extract --cpio "$image" >/dev/null || return 1
    module="usr/lib/modules/${KREL:-$(uname -r)}/kernel/drivers/gpu/drm/amd/amdgpu/amdgpu.ko"
    for suffix in .zst .xz .gz ''; do
        [[ -f $module$suffix ]] || continue
        case $suffix in
            .zst) cp "$module$suffix" "$dest" ;;
            .xz) xz -dc "$module$suffix" | zstd -q -c > "$dest" ;;
            .gz) gzip -dc "$module$suffix" | zstd -q -c > "$dest" ;;
            '') zstd -q -c "$module" > "$dest" ;;
        esac || return 1
        [[ -s $dest ]]; return
    done
    return 1
)

grub_build_image() {   # output, optional private module tree
    local out=$1 root=${2:-} args=(--kernel "${KREL:-$(uname -r)}" -g "$1" --addmodules amdgpu)
    [[ -n $root ]] && args+=(--moduleroot "$root")
    mkinitcpio "${args[@]}"
}

# Conventional Arch mkinitcpio presets only. Do not install into a stale
# running-kernel tree while /boot already holds the next kernel after an update.
grub_require_layout() {
    local pkgbase kernel installed expected actual
    pkgbase=$(imac_kernel_pkgbase "$KREL") || return 1
    kernel="$GRUB_BOOT_DIR/vmlinuz-$pkgbase"
    installed="$GRUB_MODULES_DIR/$KREL/vmlinuz"
    [[ -f $GRUB_PRESET_DIR/$pkgbase.preset && -f $GRUB_BOOT_DIR/initramfs-$pkgbase.img ]] || {
        warn "GRUB support requires the mkinitcpio preset for $pkgbase and its regular /boot initramfs; dracut/UKI-only layouts are unsupported"
        return 1
    }
    expected=$($GRUB_SUDO sha256sum "$installed") || return 1
    actual=$($GRUB_SUDO sha256sum "$kernel") || return 1
    [[ ${expected%% *} == "${actual%% *}" ]] || {
        warn "$kernel differs from the running kernel $KREL; reboot into the installed kernel before patching"
        return 1
    }
    grub_kernel_entry >/dev/null || { warn "no normal GRUB entry for $pkgbase"; return 1; }
}

# Normalize a supplied module before any live module/default image is changed.
grub_prepare_module() {
    local src=$1 dest=$2 vm
    case $src in
        *.ko.zst|*.ko.zst.stock-backup|*.ko.zst.prev-*) cp "$src" "$dest" || return 1 ;;
        *.ko|*.ko.stock-backup|*.ko.prev-*) zstd -q -f "$src" -o "$dest" || return 1 ;;
        *) warn "module must end in .ko or .ko.zst"; return 1 ;;
    esac
    vm=$(modinfo -F vermagic "$dest") || return 1
    [[ ${vm%% *} == "$KREL" ]] || { warn "module vermagic '${vm%% *}' != running kernel '$KREL'"; return 1; }
}
