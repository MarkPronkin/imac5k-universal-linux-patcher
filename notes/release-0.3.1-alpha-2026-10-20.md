# Release 0.3.1-alpha — 2026-10-20

Requested by the owner: keep brightness and the related firmware features
without exposing the iGPU, and add an apply-all-non-experimental action
directly below the safe batch, only when experimental patches are present.
The owner then requested a separate independent experimental iGPU exposure
feature and confirmed that the existing all-patches action keeps skipping HDR.

## Changes

- `macos`: the kernel command line now blocks `i915` alongside `i2c_i801`;
  the mkinitcpio drop-in no longer prepends `i915`. Intel exposes no DRM
  graphics/render device unless the separate experimental `igpu` module is
  explicitly enabled. The Apple firmware call still makes the PCI
  function visible in `lspci`; it is needed for the backlight path.
- Firmware brightness, the verified optional full-range ACPI table, SMBus
  enable rule, NVRAM save service, Radeon pin and compatibility files remain.
  Intel video packages are no longer offered by the preflight.
- New `igpu` module: independently enables headless Intel graphics and
  Quick Sync, with its own experimental initramfs marker and boot settings.
  It installs no brightness table or NVRAM service. Either apply order and
  either removal order preserve the other module and shared firmware files;
  the last removal restores plain boot. No legacy installation is silently
  opted into this experiment.
- Previous installations report partial, so reapplying migrates them.
  Limine handles both the earlier in-place configuration and its drop-in;
  GRUB replaces the old blacklist rather than leaving conflicting values.
  A running Intel driver or Intel DRM device keeps status partial until
  reboot. Nothing unloads a live graphics driver.
- The menu adds `Apply all non-experimental patches` immediately below
  `Apply all safe patches` in both gum and plain menus when any experimental
  module is available (including installed/partial modules, excluding n/a).
  It applies safe and boot-tier modules and excludes both HDR and iGPU exposure. The existing
  `Apply all patches` / `--apply all` semantics are preserved: experimental
  modules still require explicit selection.
- Current documentation describes the disabled-iGPU behavior; the old
  implementation and hardware evidence are preserved in
  `docs/macos-igpu-history.md`.

## Validation

- `IMAC5K_REQUIRE_STARTUP_TESTS=1 IMAC5K_REQUIRE_T2_AUDIO_TESTS=1
  IMAC5K_REQUIRE_EQ_AUDIO_TESTS=1 ./scripts/check.sh`: **602 tests passed,
  no skips**, plus Bash syntax checks (71.562 seconds).
- The new regressions cover old Limine layouts and GRUB recovery entries,
  retained ACPI/NVRAM brightness support, the running-driver/DRM reboot gate,
  no early i915 loading or Intel package offers, and conditional menu order
  and dispatch in both plain and gum menus. The independent iGPU tests cover
  standalone apply/removal, coexistence in both orders, keeping brightness
  when disabling Intel, preserving Intel when removing brightness, model
  gates, opted-in package recommendations, and rebuild/restore/verification
  failures.
- `git diff --check` passed.
- Tests use temporary roots and mock boot tools; no live patch, boot image
  or desktop configuration was changed.

## Publication

- Published [v0.3.1-alpha](https://github.com/MarkPronkin/imac5k-universal-linux-patcher/releases/tag/v0.3.1-alpha)
  at **17:31:41 UTC**, 2026-10-20, as a prerelease targeting `main`.
  GitHub confirms `MarkPronkin` as release author and uploader of both assets.
- `main` and the annotated tag were pushed atomically with explicit refspecs;
  the tagged commit is `11b95f2944d0e6ddae90835b71d8757286ed169e`.
  The `test` branch and all other tags are unchanged.
- Archive: **373018 bytes, 105 entries**. SHA-256:
  `09b39cf0a2ceb639b4b2a84b87cbee49b8c0a823a4e766311c5dc135c53b8346`.
  Two fresh tagged checkouts built byte-identical archives and single-release
  SHA256SUMS files. VERSION and COMMIT agree with the release and tag.
  The archive contains the independent iGPU library, configuration and guide,
  and the existing HDR runtime; development tests/notes/workflows are excluded.
- Public unauthenticated downloads of both files match those builds exactly.
  The installer fetched from `main` automatically selected 0.3.1-alpha,
  verified its checksum and installed into a scratch home/data/bin tree;
  its `--version`, `--help` and COMMIT agree with the tag. No host patch
  installation or boot configuration was changed.
- [Main branch check 39466826684](https://github.com/MarkPronkin/imac5k-universal-linux-patcher/actions/runs/39466826684)
  passed at the tagged commit.
- [Release verification 39466865830](https://github.com/MarkPronkin/imac5k-universal-linux-patcher/actions/runs/39466865830)
  passed: tag/prerelease metadata, offline checks, required isolated startup
  tests, and a fresh rebuild compared byte-for-byte to both published files.
- The following documentation-only main commit records publication; the tag
  remains at `11b95f2`.

## Upgrade

`imac-patcher upgrade`, then `imac-patcher --apply macos`, then reboot.
The tool upgrade alone does not change already-installed patches.

## Hardware limits

The previous firmware brightness path was verified on iMac18,3 under
Omarchy/Limine. The 0.3.1-alpha iGPU-disabled configuration has not been
reboot-tested on hardware. The independent `igpu` module also awaits a hardware boot; its original
combined headless configuration was verified in earlier releases. The GRUB
path remains hardware-untested.
