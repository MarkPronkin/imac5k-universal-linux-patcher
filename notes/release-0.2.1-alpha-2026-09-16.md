# Release 0.2.1-alpha from test — 2026-09-16

User request (2026-09-16): push all changes from this repository to `test`,
remove the review branch, then release 0.2.1 alpha with all the new patches
from `test`, and make sure this time the release is credited to the owner's
GitHub account, MarkPronkin.

## What went to `test`

`origin/test` was at `b4b0a61` (0.1.92-alpha) and was fast-forwarded. It now
carries, in order:

- the four 0.2.0-alpha commits already on `origin/main` (`eb998f0` to
  `da90c1b`);
- the four local `main` commits that were never pushed: the brcmfmac record
  (`c1a58f5`), the Wi-Fi sleep hook (`65c2d88`), the staged-test record
  (`2a4630c`) and the first confirmed s2idle cycle (`7e379ad`);
- the uncommitted work from `review/full-audit-2026-09-11`, split by topic:
  1. `88968dd` the XHC1 fix: DKMS module, suspend-module integration on both
     backends, tests, docs and the README status cells;
  2. `67d5dd9` the second-sleep investigation record: handoff, AGENTS.md
     checkpoints, the notes/ helpers with their tests, notes/s3-sleep.md;
  3. `537d114` the full-audit fixes
     ([their record](review-fixes-2026-09-16.md));
  4. `eb8fced` the `t2speakers` module
     ([its record](t2-speakers-review-2026-09-16.md));
- the release commits: publishing from the owner's account (`4b1d89f`) and
  this record (`105bcbb`, tagged `v0.2.1-alpha`); after the tag, the
  verification fix (`3c47176`) and the publication details below.

The split was built with a temporary index from zero-context change groups;
three intermediate hunks were written by hand (the README model table before
its `t2speakers` column, the development guide's test table, and the release
contents test before `scripts/t2-speakers.py`). Each topic commit passed
`IMAC5K_REQUIRE_STARTUP_TESTS=1 IMAC5K_REQUIRE_T2_AUDIO_TESTS=1
scripts/check.sh` on its own, in a fresh clone: 303, 345, 383 and 444 tests,
no skips, and `git diff --check` was clean for each. The tree of `eb8fced` is
byte-identical to the working tree it came from.

The review branch's own three commits (a working-tree snapshot, `REVIEW.md`,
`BUG-HUNT.md`) were marked local-only and were not pushed. The snapshot's
AGENTS.md and handoff changes are part of commit 2, and
[the review-fix record](review-fixes-2026-09-16.md) replaces the two reports,
which the working tree had already deleted. The branch was then deleted; its
tip was `c57b129`. It never existed on GitHub.

`main` was not touched: local `main` is still `7e379ad`, four commits ahead
of `origin/main` (`da90c1b`, 0.2.0-alpha), and all of it is in `test`.

## Credit on GitHub

Every release up to 0.2.0-alpha was created by the release workflow with
`GITHUB_TOKEN`, so GitHub lists `github-actions[bot]` as its author. The
commits and annotated tags were already the owner's: GitHub links
`markpronkin06@gmail.com` to MarkPronkin.

From this release on, the owner publishes with `gh release create` from their
own account, uploading the archive and `SHA256SUMS` built from the tag in a
fresh clone (see [the development guide](../docs/development.md#releases)).
`.github/workflows/release.yml` now runs on `release: published` with read
access only: checks, a rebuild of the archive from the tagged commit, and a
byte comparison with the published files; a suffixed tag must be a
pre-release. A local rebuild of `v0.2.0-alpha` with GNU tar 1.35 and gzip
1.14 gave `d5d703e7…`, the checksum of the asset CI built for it, so the
comparison holds across machines.

The `v0.2.1-alpha` tag is annotated by `MarkPronkin
<markpronkin06@gmail.com>`. Commits keep the usual Claude co-author trailer.

## Publication

- The tag points at `105bcbb`. Two builds from it in fresh clones were
  identical: `962c9cc01b1dcfd5b9d5d6d7acf8d59ce28bc60a40669329db6dd0ce1deee5c3`,
  273800 bytes, with `VERSION`, `COMMIT`, `install.sh` and `modules/` inside
  and no notes, tests or workflow files. Installed from a local mirror into a
  scratch HOME it reported 0.2.1-alpha, both fresh and through the
  0.2.0-alpha installer (the path `imac-patcher upgrade` takes); a tampered
  checksum was refused.
- Published at 14:24 UTC with `gh release create` as MarkPronkin. The API
  lists MarkPronkin as the release author and as the uploader of both
  assets; target `test`, pre-release.
- The first verification run (Actions run 35108278159) failed although the
  published tarball matched the rebuild: the release tests that run first had
  left `9.9.9-test` and `9.9.10-test` archives in `dist/`, so the rebuilt
  `SHA256SUMS` had two extra lines. `3c47176` empties `dist/` before the
  rebuild and lets the workflow run by hand for an existing tag. The manual
  run (35108723620) rebuilt `962c9cc0…` and matched both published files.
  The failed run is still listed under Actions.

## Open items

- Log a second sleep in a boot where modules-load.d, not apply, loaded the
  XHC1 fix (`sudo python3 notes/xhci-d0-sleep-test.py --require-boot-loaded`).
- The XHC1 fix is iMac18,3-only. The Wi-Fi hook now lets other BCM43602
  models (iMac17,1) really sleep; if their firmware has the same fault, their
  second sleep resets. The release notes say so; whether to keep suspend in
  the safe tier on untested models is the owner's call.
- Guard suspend against a 5K module older than 0.1.91-alpha (open since
  0.2.0-alpha).
- `t2speakers`: speaker order and sound need an iMac Pro.
- Issue #3 (2026-09-16): an intermittent amdgpu divide error in
  `dce_transform_get_optimal_number_of_taps` after the stitch split leaves a
  zero-width plane, on an iMac Pro with KDE. Not reproduced here; the patch
  stack is unchanged since 0.2.0-alpha.
- 0.2.0-alpha's release notes still cite an unverifiable "clean s2idle
  resume"; the 0.2.1-alpha notes carry the correction.
- `install.sh` and `imac-patcher upgrade` take the newest release including
  pre-releases, so this `test` release is also what `main` users get by
  default, as 0.1.92-alpha was.
