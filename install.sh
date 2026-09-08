#!/usr/bin/env bash
#
# imac5k-universal-linux-patcher installer.
#
#   curl -fsSL https://raw.githubusercontent.com/MarkPronkin/imac5k-universal-linux-patcher/main/install.sh | bash
#
# Downloads a release tarball -- not the whole repository, which carries ~50k
# lines of development notes the tool never reads -- verifies its checksum,
# unpacks it under ~/.local/share, and links `imac-patcher` into ~/.local/bin.
#
# It installs the patcher. It applies nothing: the patcher itself asks before
# touching anything, and this script hands you back to it.
#
# Options (also settable in the environment, for `curl ... | bash`):
#   --version <tag>   install a specific release      IMAC5K_VERSION=v0.1.0-alpha
#   --bin-dir <dir>   where to link the launcher      IMAC5K_BIN_DIR=~/bin
#   --no-verify       skip the checksum check         IMAC5K_NO_VERIFY=1
#   --uninstall       remove an installed copy
#
# IMAC5K_BASE_URL overrides where the assets are fetched from, and
# IMAC5K_API_URL where releases are listed, for a mirror or a local dry run.
#
set -euo pipefail

# Everything lives in main(), called on the last line: a `curl | bash` that is
# cut off mid-transfer then runs nothing at all, rather than half an installer.
main() {
    REPO=MarkPronkin/imac5k-universal-linux-patcher
    NAME=imac5k-patcher
    DATA_DIR="${XDG_DATA_HOME:-${HOME}/.local/share}/${NAME}"
    BIN_DIR="${IMAC5K_BIN_DIR:-${HOME}/.local/bin}"
    VERSION="${IMAC5K_VERSION:-}"
    VERIFY=1; [[ -n ${IMAC5K_NO_VERIFY:-} ]] && VERIFY=0
    KEEP=3          # previous versions kept, so a bad release can be rolled back
    action=install

    while (($#)); do
        case "$1" in
            --version)   VERSION="${2:?--version needs a tag}"; shift 2 ;;
            --bin-dir)   BIN_DIR="${2:?--bin-dir needs a path}"; shift 2 ;;
            --no-verify) VERIFY=0; shift ;;
            --uninstall) action=uninstall; shift ;;
            -h|--help)   usage; exit 0 ;;
            *) die "unknown option: $1  (try --help)" ;;
        esac
    done

    [[ $action == uninstall ]] && { uninstall; return; }

    preflight
    resolve_version
    fetch_and_install
    link_launcher
    prune_old
    epilogue
}

say()  { printf '\033[1;33m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;31m!!\033[0m %s\n' "$*" >&2; }
die()  { warn "$*"; exit 1; }
usage() {
    cat <<'USAGE'
install.sh -- install the iMac18,3 patcher from a published release.

  --version <tag>   install a specific release   (env IMAC5K_VERSION)
  --bin-dir <dir>   where to link the launcher   (env IMAC5K_BIN_DIR)
  --no-verify       skip the checksum check      (env IMAC5K_NO_VERIFY)
  --uninstall       remove an installed copy

IMAC5K_BASE_URL and IMAC5K_API_URL point at a mirror instead of GitHub.
Installs the patcher only; it applies nothing on its own.
USAGE
}

preflight() {
    # Installing as root would put the launcher and every per-user config the
    # patcher writes into /root. The patcher calls sudo itself where it needs to.
    if [[ $EUID -eq 0 && -z ${IMAC5K_ALLOW_ROOT:-} ]]; then
        die "run this as your normal user, not root -- the patcher sudos where it must"
    fi
    local missing=() c
    for c in curl tar sha256sum install mktemp uname; do
        command -v "$c" >/dev/null || missing+=("$c")
    done
    ((${#missing[@]})) && die "missing required commands: ${missing[*]}"

    # A warning, not a gate: it is reasonable to stage the tool before moving the
    # disk into the iMac. The patcher gates on the same check when it runs.
    local product; product="$(cat /sys/class/dmi/id/product_name 2>/dev/null || echo unknown)"
    [[ $product == iMac18,3 ]] || warn "this machine is ${product}, not an iMac18,3 -- installing anyway, but the patcher will refuse to run here"
}

resolve_version() {
    if [[ -z $VERSION ]]; then
        say "looking up the latest release"
        local json
        # Newest release including pre-releases; /releases/latest hides those,
        # and every 0.x tag here is one.
        json="$(curl -fsSL -H 'Accept: application/vnd.github+json' \
                "${IMAC5K_API_URL:-https://api.github.com/repos/${REPO}/releases}?per_page=1")" \
            || die "could not reach the GitHub API -- pass --version <tag> to install a known release"
        VERSION="$(printf '%s' "$json" \
                   | grep -o '"tag_name"[[:space:]]*:[[:space:]]*"[^"]*"' \
                   | head -1 | sed 's/.*"\([^"]*\)"$/\1/')"
        [[ -n $VERSION ]] || die "no releases published yet -- clone the repo and run ./scripts/imac-patcher"
    fi
    TAG="$VERSION"
    VER="${TAG#v}"                       # tag v0.1.0-alpha -> version 0.1.0-alpha
    PREFIX="${NAME}-${VER}"
    BASE="${IMAC5K_BASE_URL:-https://github.com/${REPO}/releases/download/${TAG}}"
}

fetch_and_install() {
    tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
    say "downloading ${PREFIX}.tar.gz"
    curl -fsSL --retry 3 -o "${tmp}/${PREFIX}.tar.gz" "${BASE}/${PREFIX}.tar.gz" \
        || die "no such release asset: ${BASE}/${PREFIX}.tar.gz"

    if ((VERIFY)); then
        # This proves the tarball arrived intact from the release, not that the
        # release is trustworthy -- the checksum ships beside it. Compare the
        # printed hash against the release page if that distinction matters.
        curl -fsSL -o "${tmp}/SHA256SUMS" "${BASE}/SHA256SUMS" \
            || die "release ${TAG} publishes no SHA256SUMS -- re-run with --no-verify to install anyway"
        grep -F " ${PREFIX}.tar.gz" "${tmp}/SHA256SUMS" > "${tmp}/sum" \
            || die "SHA256SUMS has no entry for ${PREFIX}.tar.gz"
        ( cd "$tmp" && sha256sum -c sum ) >/dev/null \
            || die "checksum mismatch -- refusing to install ${PREFIX}.tar.gz"
        say "checksum verified"
    fi

    tar -xzf "${tmp}/${PREFIX}.tar.gz" -C "$tmp"
    [[ -x "${tmp}/${PREFIX}/scripts/imac-patcher" ]] \
        || die "the tarball does not look like a patcher release (no scripts/imac-patcher)"

    dest="${DATA_DIR}/versions/${VER}"
    mkdir -p "${DATA_DIR}/versions"
    rm -rf "$dest"
    mv "${tmp}/${PREFIX}" "$dest"
    ln -sfn "$dest" "${DATA_DIR}/current"
    say "installed ${VER} into ${dest}"
}

link_launcher() {
    mkdir -p "$BIN_DIR"
    # The launcher points at current/, so the next install switches every link
    # at once and a rollback is one `ln -sfn` away.
    ln -sfn "${DATA_DIR}/current/scripts/imac-patcher" "${BIN_DIR}/imac-patcher"
    say "linked ${BIN_DIR}/imac-patcher"
}

prune_old() {
    local keep=() d
    # Newest first by mtime; each install refreshes the directory it wrote.
    while IFS= read -r d; do keep+=("$d"); done < <(
        ls -1dt "${DATA_DIR}/versions/"*/ 2>/dev/null || true)
    ((${#keep[@]} > KEEP)) || return 0
    for d in "${keep[@]:KEEP}"; do
        [[ "$(readlink -f "$d")" == "$(readlink -f "${DATA_DIR}/current")" ]] && continue
        rm -rf "$d"
    done
}

uninstall() {
    # Deliberately does not un-apply patches: a boot-config or amdgpu change
    # outlives this directory, and only the patcher knows how to reverse it.
    if [[ -x "${DATA_DIR}/current/scripts/imac-patcher" ]]; then
        warn "any patches you applied stay applied -- remove them first with:"
        warn "  imac-patcher --remove <id...>     (see imac-patcher --status)"
    fi
    rm -f "${BIN_DIR}/imac-patcher"
    rm -rf "$DATA_DIR"
    say "removed ${DATA_DIR} and ${BIN_DIR}/imac-patcher"
}

epilogue() {
    echo
    case ":${PATH}:" in
        *":${BIN_DIR}:"*) say "run:  imac-patcher" ;;
        *)  warn "${BIN_DIR} is not on your PATH"
            printf '    add it:  echo '\''export PATH="%s:$PATH"'\'' >> ~/.bashrc\n' "$BIN_DIR"
            say  "or run it directly:  ${BIN_DIR}/imac-patcher" ;;
    esac
    printf '\n    imac-patcher            interactive menu\n'
    printf '    imac-patcher --status   what is applied right now\n\n'
}

main "$@"
