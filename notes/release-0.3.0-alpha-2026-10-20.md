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
