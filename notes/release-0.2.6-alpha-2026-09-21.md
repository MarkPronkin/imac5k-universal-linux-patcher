# Release 0.2.6-alpha from test — 2026-09-21

The owner asked to push `test` to GitHub and publish `v0.2.6-alpha` from it,
pushing this release to `test` only. `main` is outside this release's scope.

## What GitHub already has

`v0.2.3-alpha` and `v0.2.4-alpha` were published earlier on 2026-09-21. Their
tags were deleted on GitHub at 02:43 UTC the same day, and neither release
exists there any more. Both tags remain in this local repository and are not
pushed with this release, which pushes only `test` and `v0.2.6-alpha`. There
has never been a 0.2.5-alpha. The latest release on GitHub before this one is
`v0.2.2-alpha`, so the release notes cover every change since it.

## Changes since 0.2.2-alpha

- `macos` (iMac18,3): Apple's set_os firmware path exposes a headless Intel HD
  630 for Quick Sync and makes the ACPI backlight dim the panel, over the full
  range where the firmware's brightness table can be rebuilt and verified.
  The Radeon keeps the desktop. Ported from Ahmad Al-Awadi's work.
  - Omarchy/Limine: verified on iMac18,3 / 7.2.5-3-omarchy. That covered the
    headless iGPU, the Radeon compositor, unaffected audio, working dimming,
    the full-range table and two s2idle cycles in one boot.
  - **Arch-family GRUB, new in this release** (`4ed973e`). The hook edits the
    kernel image GRUB loads, `/boot/vmlinuz-<pkgbase>`. The parameters go in
    `GRUB_CMDLINE_LINUX`, and removal restores the kernel image. GRUB 2.12+
    is required, checked in the installed `linux.mod`, because only it starts
    the kernel through the EFI stub. Offline tests only; not booted on
    hardware.
  - On both backends the hook is now installed last, so a failed apply cannot
    leave it editing images that lack the parameters.
- `eq`: taprobane99's reviewed retune from issue #6 (`d82e423`), with crossover
  and EQ in four 48 kHz FIRs. The previous tuning stays selectable with
  `IMAC5K_EQ_TUNING=legacy`.
- `suspend` on T2 iMacs follows t2linux. It requires linux-t2's `t2bce`,
  refuses while anything unloads the T2 driver around sleep, and keeps the
  kernel's sleep mode. Not tested on T2 hardware.
- Documentation on which application reaches which GPU for video, and the
  tested WebKit (Epiphany Flatpak) cross-GPU VP9 path.

## Validation before tagging

- `./scripts/check.sh` on the release commit's tree: 550 tests passed
  (34 new for the GRUB work).
- The set_os hook's GRUB modes ran against a scratch copy of the real
  `7.2.5-3-omarchy` kernel. The edit changed 14 bytes, `--same-kernel`
  accepted the edited copy, and `--restore` gave back a byte-identical image.
- Read-only `imac-patcher --status` on this Omarchy machine still reports
  macOS mode applied after the refactor.
- No GRUB command was run on this machine, which boots Limine.

## User actions

Upgrade the tool, then apply what is wanted: `imac-patcher --apply eq` for
the new tuning, `imac-patcher --apply macos` and a reboot for macOS mode.
Upgrading the tool alone applies neither.

## Publication

- Published [v0.2.6-alpha](https://github.com/MarkPronkin/imac5k-universal-linux-patcher/releases/tag/v0.2.6-alpha)
  at 03:33:40 UTC, 2026-09-21, as a prerelease targeting `test`. Its notes
  cover every change since `v0.2.2-alpha` and say that the GRUB path has not
  been booted on hardware.
- The annotated tag points at `e7d61710b93bc8ea56d47a6b439e762211e19ebe`.
  `test` (fast-forward from `892eef9`) and the tag were pushed atomically with
  explicit refspecs. `main` stayed at `c1086d2`, and the local `v0.2.3-alpha`
  and `v0.2.4-alpha` tags were not pushed.
- GitHub confirms `MarkPronkin` as release author and uploader of both assets.
- Archive: 346354 bytes, 98 entries. SHA-256:
  `716d624ef5bf149a53734d1176b3aa05da228ab0a8c931404e117f7534a74854`.
- Two builds from the tag in fresh clones were byte-identical, including the
  single-release `SHA256SUMS`. The published files were downloaded and compared
  byte-for-byte with the build. In the archive, VERSION is `0.2.6-alpha` and
  COMMIT the tagged commit. All runtime files are there, the GRUB work
  included, and no tests, notes or workflow files.
- Fresh tagged checkout: `IMAC5K_REQUIRE_STARTUP_TESTS=1
  IMAC5K_REQUIRE_T2_AUDIO_TESTS=1 IMAC5K_REQUIRE_EQ_AUDIO_TESTS=1
  ./scripts/check.sh` passed **550 tests, no skips**.
- The published release installed into scratch data and bin directories, with
  `checksum verified`. `--version` reports `0.2.6-alpha`, and COMMIT matches
  the tag. No host installation or live module was changed.
- GitHub [release verification 35557925238](https://github.com/MarkPronkin/imac5k-universal-linux-patcher/actions/runs/35557925238)
  passed every step: tag and prerelease metadata, offline checks, required
  isolated startup checks, and a rebuild compared byte-for-byte with both
  published assets. The rebuild's SHA-256 matches the one above.
- GitHub [branch check 35557886645](https://github.com/MarkPronkin/imac5k-universal-linux-patcher/actions/runs/35557886645)
  passed at the released commit. The documentation-only commit that follows
  records this on `test`; the release tag stays at `e7d6171`.

## Turned back into a draft

At 03:46 UTC the owner reported that the new release appeared on `main` and
should not, and it was made a draft again (`gh release edit v0.2.6-alpha
--draft=true`). GitHub releases belong to the repository, not to a branch;
`--target test` only says where the tag was cut. So a published release shows
on the repository page, which displays `main`. Worse, `main`'s README installer
and every installed `imac-patcher upgrade` take the newest release,
prereleases included, and had started to deliver 0.2.6-alpha to `main`
users.

As a draft it is invisible to everyone else. The public asset download returns
404, and the newest release anyone else sees is `v0.2.2-alpha` (target
`main`) again. It keeps its notes, both verified assets, the prerelease flag
and the `v0.2.6-alpha` tag on `test`. `gh release edit v0.2.6-alpha
--draft=false` publishes it again, and that reaches `main` users at once, so
do it only when they should get it. Until then it can be installed from a
checkout of the tag, or its assets downloaded by an account with access.
