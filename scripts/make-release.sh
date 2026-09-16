#!/usr/bin/env bash
#
# make-release.sh — build the release tarball that install.sh downloads.
#
#   scripts/make-release.sh 0.1.0-alpha [ref]
#
# Produces, in dist/:
#   imac5k-patcher-<version>.tar.gz   runtime tree, prefixed with its own name
#   SHA256SUMS                        checksums of all release tarballs in dist/
#
# The tarball carries only what the patcher needs at runtime -- scripts, the
# kernel module sources DKMS builds, the patch stack, the config templates and
# the docs -- not TODO.md, notes/ or tests/, which are development state and
# dwarf the rest. install.sh rides along so `imac-patcher upgrade` can run it
# without fetching it first, which makes each release carry the installer for
# the one after it.
#
# Content comes from a git ref (HEAD by default), never the dirty working tree,
# so a tarball always corresponds to a commit. Ordering, ownership, timestamps
# and the gzip header are pinned to the commit, so rebuilding the same ref gives
# a byte-identical archive and anyone can reproduce the published checksum.
#
set -euo pipefail

VERSION="${1:?usage: make-release.sh <version> [git-ref]}"
[[ $VERSION =~ ^[0-9][a-zA-Z0-9._+-]*$ ]] || { echo "invalid release version: $VERSION" >&2; exit 1; }
REF="${2:-HEAD}"
NAME=imac5k-patcher

REPO_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/.." && pwd)"
cd "$REPO_DIR"

# Paths the installed tool actually reads. Keep in sync with install.sh's sanity
# check, which fails the install if scripts/imac-patcher is missing.
PATHS=(install.sh scripts modules patches configs assets docs README.md DEPENDENCIES.md LICENSE)

DIST="${REPO_DIR}/dist"
PREFIX="${NAME}-${VERSION}"
TARBALL="${DIST}/${PREFIX}.tar.gz"

git rev-parse --verify --quiet "${REF}^{commit}" >/dev/null \
    || { echo "no such git ref: ${REF}" >&2; exit 1; }
COMMIT="$(git rev-parse "${REF}^{commit}")"   # ^{commit}: an annotated tag is its own object
MTIME="$(git show -s --format=%cI "$COMMIT")"

mkdir -p "$DIST"
exec {release_lock}>"${DIST}/.release.lock"
flock -n "$release_lock" || { echo "another release build is running" >&2; exit 1; }
stage="$(mktemp -d "${DIST}/.release.XXXXXX")"
trap 'rm -rf "$stage"' EXIT
mkdir -p "${stage}/${PREFIX}"
git archive "$COMMIT" -- "${PATHS[@]}" | tar -x -C "${stage}/${PREFIX}"

# What `imac-patcher --version` reports once installed.
printf '%s\n' "$VERSION" > "${stage}/${PREFIX}/VERSION"
printf '%s\n' "$COMMIT"  > "${stage}/${PREFIX}/COMMIT"

tar -C "$stage" \
    --sort=name --format=gnu \
    --owner=0 --group=0 --numeric-owner \
    --mtime="$MTIME" \
    -cf - "$PREFIX" | gzip -9n > "${stage}/release.tar.gz"
mv "${stage}/release.tar.gz" "$TARBALL"

( cd "$DIST" && sha256sum imac5k-patcher-*.tar.gz > "${stage}/SHA256SUMS" )
mv "${stage}/SHA256SUMS" "${DIST}/SHA256SUMS"

printf '\n%s\n' "$TARBALL"
printf '  %s\n' "$(cd "$DIST" && cat SHA256SUMS)"
printf '  %s bytes, from %s\n\n' "$(stat -c%s "$TARBALL")" "${COMMIT:0:12}"
