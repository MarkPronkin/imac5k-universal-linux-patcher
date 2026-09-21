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
