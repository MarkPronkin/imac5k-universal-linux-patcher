# Release 0.3.0-alpha to main — 2026-10-20

The owner: "push new release to github with the stuff from hdr and test
branch, to main. mark the new release 0.3.0 alpha".

## Scope

- The `hdr` branch no longer exists: its work moved to `test` on 2026-10-06.
  What was still uncommitted on 2026-10-20 was the `hdr` patcher module the
  owner asked for on 2026-10-17, built and offline-tested then. It is
  committed on `test` as `6878431`, together with the 2026-10-07 real-desktop
  test (`experiments/hdr/desktop.py`).
- The Fedora 7.2.9+ fix for issue #12 is committed as `f36c1cf`.
- `main` is fast-forwarded to `test`. Local `main` carried one unpushed
  commit, `bd139a7` (the Ahmad credit of #4 on top of `c1086d2`); both lines
  it adds are already in `test`'s README through `e34adf6`, so nothing is lost.
- Left uncommitted on purpose: the owner's external-display notes
  (`notes/atomdis.py`, `notes/dce112-display-state.sh`,
  `notes/external-display-dp-2026-09-22.md`). They belong to neither branch.
- `v0.2.6-alpha` stays a draft. This release supersedes it. The local
  `v0.2.3-alpha` and `v0.2.4-alpha` tags are still not pushed.

## Changes since 0.2.2-alpha

The newest release anyone but the owner has seen is `v0.2.2-alpha`
(0.2.6-alpha was public for 13 minutes on 2026-09-21), so the notes cover
everything since it:

- `hdr` (new, experimental tier, iMac18,3, Hyprland 0.56.2 under uwsm): the
  EDR desktop as a module. Neither `safe` nor `all` applies it. EDR itself
  was verified on the panel (Chromium HDR video, mpv HDR10); a login through
  the module itself and sleep with EDR on have not been tried.
- `macos` (iMac18,3): verified on Omarchy/Limine; Arch-family GRUB 2.12+
  supported but not booted on hardware. Ported from Ahmad (@ahmadtv).
- Sleep split (`52dd6e8`): `suspend` is the iMac18,3's module; `t2suspend`
  holds the T2 rules (untested on T2 hardware); n/a on the 2014-2015 models
  and the iMac19,1, with earlier releases' leftovers shown as partial.
- `eq`: the #6 retune, with `IMAC5K_EQ_TUNING=legacy` for the old one.
- Fedora 7.2.9+ (#12): both stacks re-anchored; see `patches/README.md`.
- Video documentation: which application reaches which GPU, WebKit VP9.

## Validation before tagging

- Fresh clone of `test` at `6878431`, whose runtime tree is the release's
  (the release commit adds only this record and AGENTS.md):
  `IMAC5K_REQUIRE_STARTUP_TESTS=1 IMAC5K_REQUIRE_T2_AUDIO_TESTS=1
  IMAC5K_REQUIRE_EQ_AUDIO_TESTS=1 ./scripts/check.sh` passed **575 tests, no
  skips** (30 of them the new `test_hdr.py`, with real Lua and uwsm).
- Read-only `imac-patcher --status` from that clone on this iMac18,3
  (7.2.5-3-omarchy): every module as before, `hdr` not applied
  [experimental].
- #12: both stacks apply at `--fuzz=0` to pristine 7.2.2-7.2.11 and to the
  four Fedora 44 sources; the lean `amdgpu.ko` built against Fedora
  7.2.10-200. Details in `patches/README.md` and commit `f36c1cf`.
- Nothing was applied to this machine, and nothing was booted.

## Publication

- Published [v0.3.0-alpha](https://github.com/MarkPronkin/imac5k-universal-linux-patcher/releases/tag/v0.3.0-alpha)
  at 07:55:48 UTC, 2026-10-20, as a prerelease targeting `main`. GitHub
  confirms `MarkPronkin` as release author and uploader of both assets.
- The annotated tag points at `5de443c596eeebb5809f0fe49c164f755337e863`.
  `test` (from `77c3367`), `main` (from `c1086d2`) and the tag were pushed
  atomically with explicit refspecs; both branches fast-forwarded. No other
  tag was pushed.
- Archive: 367842 bytes, 101 entries. SHA-256:
  `ebfc03443e298652e747a6ced9bb014c4d1c5cb0f84bd4d1e33065794d336bfb`.
- Two builds from the tag in fresh clones from GitHub were byte-identical,
  including the single-release `SHA256SUMS`. In the archive, VERSION is
  `0.3.0-alpha` and COMMIT the tagged commit; it carries
  `scripts/hypr-edr.py`, `patches/hyprland-0.56.2-edr.patch`, `docs/hdr.md`
  and both re-anchored hunks, and no tests, notes or workflow files.
- The public downloads, fetched without authentication, are byte-identical
  to the build. The unauthenticated release list now starts with
  `v0.3.0-alpha`, then `v0.2.2-alpha`; the `v0.2.6-alpha` draft stays hidden.
- `main`'s own `install.sh`, fetched from raw.githubusercontent.com and
  identical to the released one, resolved the newest release by itself and
  installed it into scratch HOME, data and bin directories: `checksum
  verified`, `--version` 0.3.0-alpha, COMMIT the tag. No host installation or
  live module was changed.
- GitHub [release verification 39389808923](https://github.com/MarkPronkin/imac5k-universal-linux-patcher/actions/runs/39389808923)
  passed: tag and prerelease metadata, offline checks, required isolated
  startup checks, and a rebuild compared byte-for-byte with both published
  assets.
- Branch checks passed at the released commit on
  [main 39389625488](https://github.com/MarkPronkin/imac5k-universal-linux-patcher/actions/runs/39389625488)
  and [test 39389625236](https://github.com/MarkPronkin/imac5k-universal-linux-patcher/actions/runs/39389625236).
  The documentation-only commit that follows records this on both branches;
  the tag stays at `5de443c`.

## Open

- `hdr`: the owner's real `imac-patcher --apply hdr`, a login through it,
  and one s2idle cycle with EDR on.
- #12: a Fedora 7.2.9+ boot with the rebuilt module; the reporter can now
  re-run `imac-patcher --apply 5k` after `imac-patcher upgrade`.
- `macos` on GRUB and `t2suspend` remain untested on hardware.
