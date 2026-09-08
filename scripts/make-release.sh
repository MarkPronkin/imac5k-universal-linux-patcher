#!/usr/bin/env bash
#
# make-release.sh — build the release tarball that install.sh downloads.
#
#   scripts/make-release.sh 0.1.0-alpha [ref]
#
# Produces, in dist/:
#   imac5k-patcher-<version>.tar.gz   runtime tree, prefixed with its own name
#   SHA256SUMS                        checksum of that tarball
#
# The tarball carries only what the patcher needs at runtime -- scripts, the
# patch stack, the config templates and the docs -- not TODO.md, notes/ or
# tests/, which are development state and dwarf the rest.
#
# Content comes from a git ref (HEAD by default), never the dirty working tree,
# so a tarball always corresponds to a commit. Ordering, ownership, timestamps
# and the gzip header are pinned to the commit, so rebuilding the same ref gives
# a byte-identical archive and anyone can reproduce the published checksum.
#
set -euo pipefail

VERSION="${1:?usage: make-release.sh <version> [git-ref]}"
REF="${2:-HEAD}"
NAME=imac5k-patcher

REPO_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/.." && pwd)"
cd "$REPO_DIR"

# Paths the installed tool actually reads. Keep in sync with install.sh's sanity
# check, which fails the install if scripts/imac-patcher is missing.
PATHS=(scripts patches configs docs README.md DEPENDENCIES.md LICENSE)

DIST="${REPO_DIR}/dist"
PREFIX="${NAME}-${VERSION}"
TARBALL="${DIST}/${PREFIX}.tar.gz"

git rev-parse --verify --quiet "${REF}^{commit}" >/dev/null \
    || { echo "no such git ref: ${REF}" >&2; exit 1; }
COMMIT="$(git rev-parse "$REF")"
MTIME="$(git show -s --format=%cI "$COMMIT")"

stage="$(mktemp -d)"
trap 'rm -rf "$stage"' EXIT
mkdir -p "${stage}/${PREFIX}"
git archive "$COMMIT" -- "${PATHS[@]}" | tar -x -C "${stage}/${PREFIX}"

# What `imac-patcher --version` reports once installed.
printf '%s\n' "$VERSION" > "${stage}/${PREFIX}/VERSION"
printf '%s\n' "$COMMIT"  > "${stage}/${PREFIX}/COMMIT"

mkdir -p "$DIST"
tar -C "$stage" \
    --sort=name --format=gnu \
    --owner=0 --group=0 --numeric-owner \
    --mtime="$MTIME" \
    -cf - "$PREFIX" | gzip -9n > "$TARBALL"

( cd "$DIST" && sha256sum "${PREFIX}.tar.gz" > SHA256SUMS )

printf '\n%s\n' "$TARBALL"
printf '  %s\n' "$(cd "$DIST" && cat SHA256SUMS)"
printf '  %s bytes, from %s\n\n' "$(stat -c%s "$TARBALL")" "${COMMIT:0:12}"
