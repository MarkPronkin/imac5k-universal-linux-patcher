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

Prepared for `main`, with an annotated `v0.3.1-alpha` tag. The release assets
are built from the tag in a fresh checkout, with a one-release SHA256SUMS.
The publication record will be completed after download/installer and CI
verification.

## Upgrade

`imac-patcher upgrade`, then `imac-patcher --apply macos`, then reboot.
The tool upgrade alone does not change already-installed patches.

## Hardware limits

The previous firmware brightness path was verified on iMac18,3 under
Omarchy/Limine. The 0.3.1-alpha iGPU-disabled configuration has not been
reboot-tested on hardware. The independent `igpu` module also awaits a hardware boot; its original
combined headless configuration was verified in earlier releases. The GRUB
path remains hardware-untested.
