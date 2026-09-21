# Release 0.2.4-alpha from test — 2026-09-21

The owner requested pushing the complete local `test` branch and publishing
`v0.2.4-alpha` from `test`. This supersedes the previous local-only instruction
for the speaker retune. `main` is outside this release's scope.

## Changes since 0.2.3-alpha

- `macos`: iMac18,3 on Omarchy/Limine only. Apple's set_os firmware path
  exposes a headless Intel HD 630 for Quick Sync and makes the ACPI backlight
  dim the panel. The Radeon retains the desktop. A validated rewrite of the
  firmware brightness table extends the range; if validation or iasl is
  unavailable, the original range remains supported. An mkinitcpio post hook
  preserves the setup across kernel updates, and a shutdown unit saves the
  brightness in NVRAM. Ported from Ahmad Al-Awadi's work.
- Hardware checks on iMac18,3 / 7.2.5-3-omarchy confirmed the headless Intel
  device, Radeon compositor, unaffected audio, working dimming, full-range
  table and two successful s2idle cycles in one boot. This is limited testing,
  not long-term suspend validation. iMac Pro has no iGPU and is unsupported by
  this module; other models/backends remain gated out.
- `eq`: taprobane99's issue #6 retune, pinned to `d82e423`, with crossover/EQ
  in four new 48 kHz FIRs. Previous tuning is retained via
  `IMAC5K_EQ_TUNING=legacy`. All bundled WAVs are installed; missing responses
  are refused. Stable sink naming, headphone switching and detected speaker
  routing are retained, and a digest detects older tuning.
- Expanded video documentation describes DRM versus Wayland VA-API defaults
  and the tested WebKit/Epiphany Flatpak cross-GPU VP9 path. It does not promise
  Intel decoding in every browser or application.
- Release preparation corrects two stale macOS-mode descriptions that still
  claimed sleep was untested.

## Validation

- Speaker integration work: 516 tests passed without failures or skips,
  including real current and legacy DSP graphs on a private PipeWire server.
- Subsequent read-only live verification: the installed retuned graph and
  four `-48k.wav` files match the bundle; the active service started after the
  config was installed; all four DSP links actively feed the built-in 4.0
  speakers, and the tuned sink is the default. Listening/acoustic validation
  remains pending; upstream's ±4 dB claim is not a local measurement.
- The release is built from an annotated tag in a fresh clone and includes
  `VERSION`, `COMMIT`, runtime files and attribution. Tests and notes are not
  shipped. GitHub's release workflow rebuilds and compares the uploaded assets.

## User actions

Upgrade the tool, then `imac-patcher --apply eq` to install the new tuning.
To opt into macOS mode on a supported system, run `imac-patcher --apply macos`
and reboot. Upgrading the tool alone applies neither module.

Publication details and verification results will be recorded after publishing.
