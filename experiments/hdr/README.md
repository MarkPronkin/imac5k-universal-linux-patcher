# Experimental iMac EDR compositor

This is a working rendering prototype on the `hdr` branch, based on `test`
at `52dd6e8`. It adds `cm = "edr"` to **Hyprland 0.56.2**, rendering HDR
content within the existing Display P3 / gamma 2.2 output of the 2017
iMac18,3. It is not an installable patcher module yet.

The full compositor builds. Offscreen shader tests and a nested Wayland
session pass, including SDR/PQ reference-white matching and highlight roll-off.
**The physical 5K output has not been switched to this compositor.**

## What it does

The starting profile estimates a 500-nit panel peak and sets desktop reference
white to 200 nits, leaving 2.5× headroom for highlights. Ordinary white becomes
`(200 / 500)^(1 / 2.2) = 0.65935` in the panel signal; an HDR highlight can
reach 1.0. These are calculated code values, not measured panel luminance.

The patch:

- Publishes a P3/gamma 2.2 image description with separate peak and reference
  luminance through the existing Wayland colour-management protocol.
- Normalizes source reference white so untagged SDR, tagged SDR, PQ and scRGB
  agree. Uses floating-point, linear composition to preserve highlights
  between rendering passes, including the temporary gamma encoding for blur.
- Uses Hyprland's existing alternate tone-mapping knee for content brighter
  than the panel estimate. The supplied 200/500 profile keeps reference white
  below that knee.
- Composites cursors and disables direct scanout and hardware colour-transform
  bypasses on EDR outputs, so those paths cannot skip the conversion.
- Keeps the physical output gamma-encoded. It does not advertise native PQ
  support through DRM or send HDR10 metadata to this panel.

Apple specifies [500 nits, P3 and one billion colours for this model](https://support.apple.com/en-sa/111969).
Its inspected EDID describes 10 bpc and gamma 2.2, with no PQ/HDR declaration.
The approach is similar in principle to
[Apple's explanation of EDR headroom](https://developer.apple.com/videos/play/wwdc2021/10161/).
It does not add local dimming, increase physical contrast, or establish
DisplayHDR certification. A colorimeter is unnecessary to develop the
pipeline, but needed to replace these luminance, gamma and gamut assumptions
with measurements.

## Build without installing

Run from the repository root as your desktop user:

```bash
python3 experiments/hdr/build.py "$HOME/.cache/imac5k-edr" --jobs 4
```

The script downloads checksum-pinned Hyprland, its protocol and udis86
submodules, and Glaze; applies the patch without fuzz; and builds only the
compositor. It writes under the chosen directory and never installs packages,
replaces the running compositor, or edits desktop/boot configuration.
`--prepare-only` stops after extraction and patching. After changing the patch,
use a new build directory; `--cache` can reuse the verified downloads.

Required: Python 3.12+, GNU patch, pkg-config, CMake 3.30+, make, a compiler
supporting Hyprland's C++26 requirements, and the development dependencies
listed in the pinned
[Hyprland CMakeLists.txt](https://github.com/hyprwm/Hyprland/blob/efb50993780079460b0cbed1363e2166a2de1d9f/CMakeLists.txt).
In particular, the Hyprland libraries and generated protocol tools must match
this version; this is not a patch for arbitrary older distribution packages.
The development machine used Aquamarine 0.15.0, Hyprutils 0.14.2,
Hyprgraphics 0.5.1, Hyprcursor 0.1.13 and Hyprlang 0.6.8.

The resulting executable is `BUILD_DIRECTORY/build/Hyprland`.
Its reported version includes the pinned source commit and `imac-edr` tag;
this is a patched build, not an upstream release.

## Verify the renderer

The offscreen test compiles the actual upstream GLSL and the patch's luminance
helper. It requires EGL/GLES development libraries and Mesa's software renderer:

```bash
g++ -std=c++20 -O2 -Wall -Wextra \
  -I "$HOME/.cache/imac5k-edr/source" \
  experiments/hdr/verify-render.cpp -lEGL -lGLESv2 -o /tmp/imac-edr-verify
LIBGL_ALWAYS_SOFTWARE=1 /tmp/imac-edr-verify "$HOME/.cache/imac5k-edr/source"
```

It checks black, matching SDR/PQ/scRGB white, highlight preservation through
the output and blur passes, and a monotonic, bounded roll-off for 1,000-nit content. It does not measure
the physical display or validate saturated-colour gamut mapping.

For the full compositor path, run inside an existing Wayland session with
`hyprctl`, `grim`, a C compiler, `wayland-scanner`, and Wayland client/protocol
development files available:

```bash
python3 experiments/hdr/verify-nested.py "$HOME/.cache/imac5k-edr/build/Hyprland"
```

This briefly opens a nested compositor window with three colour-managed test
patterns and a transparent overlay to exercise blur. It uses a private runtime/configuration directory, prevents physical
seat access, and stops its child processes on completion. Logs, sampled values
and captures are left in the printed `/tmp/imac-edr-nested-*` directory.
The checks exercise the actual Wayland protocol and compositor, including
the EDR policy when ordinary FP16 composition is disabled in configuration.
The captures receive Hyprland's separate SDR conversion; they are not raw
panel code values and cannot establish physical brightness.

## Profile and visual pattern

[`edr.lua`](edr.lua) is an opt-in profile for the iMac18,3's `eDP-1`: native
mode, scale 2, requested 10-bit output, P3/gamma 2.2, estimated 500-nit peak
and 200-nit reference white. It assumes the backlight is at maximum and its
full range is working. It does not move the brightness slider.

Only load this profile in a session running the patched binary, after existing
monitor rules. Stock Hyprland rejects `cm = "edr"`. The build and tests do not
install or load this profile. Physical-session launch/recovery integration is
still to be implemented before making this a patcher option.

The native Wayland demo can be used in that session:

```bash
python3 experiments/hdr/demo.py                  # PQ, about 500-nit target peak
python3 experiments/hdr/demo.py --sdr            # same scene clipped to SDR white
python3 experiments/hdr/demo.py --peak 1000      # exercise highlight roll-off
```

Each window closes after 30 seconds; `--seconds` and `--fullscreen` are
available. It uses a 10-bit shared-memory buffer when supported and otherwise
falls back to 8-bit. Seven neutral bars occupy the top, with a ramp underneath.
For the default PQ pattern, the target bars are approximately
0, 50, 100, 200, 300, 400 and 500 estimated nits. In the SDR comparison the
last four bars all stop at reference white.

## Validation and remaining work

On 2026-09-22, the full build, shader checks and nested protocol/compositor
tests passed on the development iMac. All 543 existing patcher tests passed.
Reference white matched for tagged SDR,
PQ and the 1,000-nit PQ pattern; PQ highlights remained distinct. Blur softened
the bar edges while preserving their centers, including peak highlights. The isolated
shader test additionally covered untagged SDR and scRGB. These results are
software validation, not a physical HDR certification or calibration.

Before shipping:

- Validate real 5120×2880 10-bpc scanout and both panel tiles, gradients, cursor
  brightness, performance and recovery after suspend.
- Measure peak/black/gamma/primaries and implement backlight-aware headroom.
  Changing the backlight currently invalidates the nits estimate. A different
  reference/peak ratio also needs tone-mapping validation.
- Define screenshot, screen-sharing and mirrored-output behaviour. Current SDR
  captures apply another tone map; in the nested test, reference white was
  229/255 in captures although the calculated panel code was about 168/255.
- Check real HDR applications. HLG, browser/video/game negotiation, ICC profiles,
  mixed monitors and saturated wide-gamut colours are not validated.
- Add an isolated physical-session launcher, recovery path and eventual
  apply/detect/remove support. No kernel or EDID override is part of this prototype.

The existing desktop remains on stock Hyprland with `cm = "dp3"`. All source,
build and test artifacts created for this experiment were outside system
installation paths.
