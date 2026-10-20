# Experimental iMac EDR compositor

This is a working rendering prototype on the `test` branch, first developed on
a separate `hdr` branch from `52dd6e8`. It adds `cm = "edr"` to **Hyprland 0.56.2**, rendering HDR
content within the existing Display P3 / gamma 2.2 output of the 2017
iMac18,3. Since 2026-10-17 it is also the experimental patcher module `hdr`
(`imac-patcher --apply hdr`, see [docs/hdr.md](../../docs/hdr.md)): the patch
moved to `patches/hyprland-0.56.2-edr.patch`, and the build below is
`scripts/hypr-edr.py`'s, shared with the module. This directory keeps the test
harnesses.

The full compositor builds. Offscreen shader tests and a nested Wayland
session pass, including SDR/PQ reference-white matching, highlight roll-off and
HDR10 video in mpv. The iMac's own 5K panel has run it in a test session with no
visible issues, and as the everyday desktop through `desktop.py`, where
Chromium played HDR video.

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
submodules, and Glaze; applies `patches/hyprland-0.56.2-edr.patch` without
fuzz; and builds only the compositor. It writes under the chosen directory and never installs packages,
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
`hyprctl`, `grim`, a C compiler, `wayland-scanner`, Wayland client/protocol
development files, `mpv` and `ffmpeg` with libx265 available:

```bash
python3 experiments/hdr/verify-nested.py "$HOME/.cache/imac5k-edr/build/Hyprland"
```

This briefly opens a nested compositor window with three colour-managed test
patterns, a transparent overlay to exercise blur, and a real HDR10 video in
mpv. It uses a private runtime/configuration directory, prevents physical
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
install or load this profile; the test session below does, without touching the
desktop configuration. The `hdr` module does not use this file: its wrapper
configuration adds the same profile to the user's own `eDP-1` rule.

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

[`video.py`](video.py) writes the same bars as a six-second, 60 fps HDR10 clip
(HEVC Main 10, PQ, BT.2020, 1,000-nit mastering metadata), with a ramp to
1,000 nits and a 1,000-nit square crossing at a constant 480 px/s. It wraps
from the right edge to the left, so the looped clip has no jumps or
judder of its own:

```bash
python3 experiments/hdr/video.py /tmp/hdr-test.mkv
```

### HDR video in mpv

mpv 0.41 negotiates HDR over the Wayland colour-management protocol. It reads
the EDR output's preferred description (gamma 2.2, P3, 500-nit target), and
in the nested compositor it produced these captures of the clip's bars,
against the pattern client's reference:

| Client, mode | Bars 1–7 in capture; desktop white is 229 |
|---|---|
| Pattern client, PQ | 0, 137, 187, **229**, 243, 251, 255 |
| mpv `--target-colorspace-hint-mode=source` | 0, 136, 186, **228**, 243, 248, 251 |
| mpv defaults (target mode, `spline` curve) | 0, 110, 152, **204**, 225, 235, 241 |
| mpv target mode, `--tone-mapping=bt.2390 --hdr-compute-peak=no` | 0, 137, 187, **229**, 243, 249, 252 |

In source mode mpv hands PQ to the compositor, whose tone mapping keeps the
video's reference white on desktop white. By default mpv tone-maps to the
500-nit target itself; highlights survive, but libplacebo's `spline` curve,
further moved by peak detection, puts 203-nit content about a third below
desktop white. That is mpv's curve, not a mismatch with EDR: its `bt.2390`
or `clip` curves land exactly on desktop white. The test session plays the
clip in source mode.

## Test on the iMac's display

Stage a session next to a finished build, from the repository in the desktop:

```bash
python3 experiments/hdr/session.py stage "$HOME/.cache/imac5k-edr"
```

This builds the test pattern, verifies a session configuration with the
patched binary and writes `BUILD_DIRECTORY/start`. It refuses a build from a
different patch. Nothing is installed and the desktop configuration is not
read or changed.

Then switch to a text console with Ctrl+Alt+F3, log in and run
`BUILD_DIRECTORY/start`. It lists the keys for leaving and waits for Enter.
The patched compositor then takes the display while the desktop keeps running
on its own console. The session has the desktop's monitor rules plus
`edr.lua`, the Radeon pinning of `imac-gpu.lua`, the console keyboard layout, a
terminal and no desktop services. A terminal opens with a guide and the
recorded display state, which warns if EDR, 10-bit output or the software
cursor is missing. Keys:

| Keys | Action |
|---|---|
| Esc, or any key but a modifier | Close the test pattern |
| Super+1 / 2 / 3 | Fullscreen PQ pattern / SDR comparison / 1,000-nit PQ |
| Super+4 | PQ in the top half, SDR in the bottom half |
| Super+5 | The HDR10 clip in mpv, fullscreen and looping (`q` closes it) |
| Super+Return, Super+W, Super+F | Terminal, close window, fullscreen |
| Brightness keys, or Super+Up / Super+Down | Desktop white in 25-nit steps |
| Super+B | Headroom on or off, at the same desktop white |
| Super+M | Start or stop measuring the backlight, matching two states by eye |
| Super+D | Display off for three seconds, then on |
| Super+H | The guide again |
| Super+Escape, Ctrl+Alt+Backspace | End the session and return to the console |
| Ctrl+Alt+F1 | Switch to the desktop; the test keeps running |

One pattern is shown at a time: a new one replaces any that are open. The
first physical run showed why. Patterns then ignored keys and stacked, covering
the guide, and the owner had to power off with no visible way out.

For the video, mpv times frames to the compositor's presentation feedback
(`--video-sync=display-resample`), and [`mpv-stats.lua`](mpv-stats.lua)
records its frame timing each second in the run directory. The summary
prints the last sample: video and measured display rate, vsync jitter, and
dropped, delayed and mistimed frames.

### Brightness, and the backlight traded for headroom

The panel has one backlight and no local dimming, so headroom exists only while
desktop white sits below the panel's peak: a permanent 200-nit white costs 60%
of the panel's brightness even with nothing HDR on screen.
[`headroom.py`](headroom.py) does what Apple's EDR does instead. It raises the
backlight and scales the desktop down by the same factor, so desktop white keeps
its luminance while the gap above it opens up, and it gives the backlight back
afterwards:

```bash
python3 headroom.py state     # backlight, desktop white, panel peak, headroom
python3 headroom.py step 25   # desktop white up a step, keeping the setting
python3 headroom.py toggle    # headroom on or off at the same desktop white
python3 headroom.py check     # alternate between the two to judge them by eye
python3 headroom.py match     # measure what a backlight level is really worth
```

It only runs against an `edr` output, so it cannot move the desktop's backlight,
and the session restores the backlight it found when it ends. Changing an EDR
output's luminances live costs no modeset: `hyprctl eval` with the monitor rule
updates the image description within a frame, logging nothing. The video asks
for headroom while it plays through [`mpv-stats.lua`](mpv-stats.lua) and gives
it back at exit; a shipping version belongs in the compositor, which is the only
part that knows when an HDR surface is actually visible.

Toggling on the panel behaved as designed: highlights collapsed onto white when
headroom was released, blacks improved, and desktop white moved only slightly.
That slight move is the open assumption. The ACPI backlight's 96 steps are not
proportional to luminance, so the level chosen for a given white is a little too
low. `match` measures it. Super+M starts a background loop that alternates the
low backlight at full signal against the full backlight scaled to W nits, about
a second each; the brightness keys move W while it runs, without applying
anything themselves; Super+M again stops it. When white stops changing between
the two states, W is what that backlight level is really worth, and
`curve = ln(W / 500) / ln(level / top)` is stored and used from then on. Judge
it on a white area, so show the SDR pattern first. The measurement runs in its
own session and the launcher stops it if it outlives the compositor. The panel's 500-nit peak is still Apple's figure, and it only
sets the scale of the nit labels, not the match. At full desktop white there is
nothing to trade: headroom only appears below it.

Super+D repeats the DPMS cycle that restored a stretched panel before (see
`TODO.md`). It switches off half a second after the key press, because any key
event wakes the display.

The session ends after 20 minutes unless started with `--minutes` (1..120);
`BUILD_DIRECTORY/start --stop` ends it from any terminal. While it runs it
blocks system sleep and does not update the desktop's systemd/D-Bus
activation environment. When the compositor exits, the console prints a
summary. Its log, the recorded display state, the kernel log for the period
and any crash report are kept in `BUILD_DIRECTORY/session/runs/`.

The desktop locks itself after five idle minutes while its console is in the
background. If it returns stretched or half dark, cycle its display with a
three-second pause. The first pause lets the Enter key's release go by, since
Omarchy wakes the display on any key event:

```bash
sleep 1; hyprctl eval 'hl.dispatch(hl.dsp.dpms({ action = "off" }))'; sleep 3
hyprctl eval 'hl.dispatch(hl.dsp.dpms({ action = "on" }))'
```

## Run it as the desktop, for one login

The test session has no desktop services. To try EDR with the real desktop
(bar, notifications, lock screen, browsers, every application and binding),
arm the next login:

```bash
python3 experiments/hdr/desktop.py arm "$HOME/.cache/imac5k-edr"
python3 experiments/hdr/desktop.py status   # what runs now, and at the next login
python3 experiments/hdr/desktop.py disarm   # keep the next login stock
```

`arm` writes `BUILD_DIRECTORY/desktop/`: a configuration that runs
`~/.config/hypr/hyprland.lua` unchanged and then `edr.lua`, whose eDP-1 rule
replaces the desktop's (Hyprland keeps the last rule per output), verified with
the patched binary. It then writes `~/.local/share/wayland-sessions/hyprland.desktop`.
uwsm searches the user's data directory first, so that entry shadows
`/usr/share/wayland-sessions/hyprland.desktop`, which the login runs through
`uwsm start … hyprland.desktop`. Its launcher removes the entry before anything
else, so the login after it is stock again, whatever happens in between: a
restart, a crash, a logout. A missing build falls back to the stock compositor.

The launcher starts the patched binary through the stock `start-hyprland`
watchdog (`--path`), so uwsm, the systemd activation environment and the
crash-restart behave as on the stock desktop. It blocks system sleep while it
runs, since resume with this compositor is untested. Each login gets
`BUILD_DIRECTORY/desktop/runs/<timestamp>/`: Hyprland's log written directly
there (it survives a power-off), `monitors.json` and `state.txt` recorded at
start, the kernel log for the session and any crash report. A notification at
start says whether EDR, 10-bit output and the software cursor are in effect.
Omarchy's brightness keys move the backlight as usual; the 200/500 profile
assumes it at maximum.

## Validation and remaining work

On 2026-09-22, the full build, shader checks and nested protocol/compositor
tests passed on the development iMac. All 543 existing patcher tests passed.
Reference white matched for tagged SDR,
PQ and the 1,000-nit PQ pattern; PQ highlights remained distinct. Blur softened
the bar edges while preserving their centers, including peak highlights. The isolated
shader test additionally covered untagged SDR and scRGB. These results are
software validation, not a physical HDR certification or calibration.

The persistent build of the same patch, with full source provenance, then
passed the nested test again. That build's longer instance signature exposed a
harness bug: the nested runtime directory made Hyprland's IPC socket path
exceed the 107-byte limit. The harness now uses a short runtime directory. The
staged session's keys are tested in a nested compositor with real key events:

```bash
python3 experiments/hdr/verify-session.py "$HOME/.cache/imac5k-edr"
```

It needs `wtype`, and checks every binding, closing patterns with Esc and other
keys, pattern replacement, the video (Super+5, replaced by a pattern, closed
with `q`), the guide and its recorded state, the Super+D cycle and both exit
keys. The supervisor was exercised with a stand-in compositor
for normal exit, `--stop`, the time limit, a forced kill, a crash report and
the start prompt.

**First physical run (2026-09-22, 03:31).** The panel came up in
`XRGB2101010` with `edr`, 200-nit desktop white, the software cursor and
direct scanout blocked for colour management. DP-1 stayed a non-desktop tile.
The kernel's link check passed on both tiles with no recovery, and logged no
amdgpu errors or HDR metadata packets. The owner saw the patterns but could not
leave them (see above).

**Video on the panel (04:32).** The moving square looked right, was the
brightest thing on screen, and nothing changed as it crossed the tile seam in
the middle. Its motion looked jittery. That clip was 30 fps with an eased
sweep: up to 84 physical pixels a frame. It is now 60 fps at a constant speed,
and the session records mpv's frame timing to tell content judder from
missed refreshes. With that clip the owner reported smooth motion, and the
panel run recorded **no dropped, delayed or mistimed frames** for 60.00 fps
video: measured display rate 59.87 Hz median (59.79–60.33) and vsync jitter
0.073 median, against 0.009 in the small nested window. EDR's 5K
floating-point composition, which also blocks direct scanout, therefore
sustains 60 fps video with every frame on time; the earlier judder was the
30 fps clip.

**Second physical run (03:49–03:53), with the escape fixes.** The owner found
everything as described, with no issues: HDR highlights above desktop white,
SDR clipped at it, matching halves, a smooth ramp and a normal pointer. They
switched patterns, closed them, and ended the test with Super+Escape. The
recorded state was the same as in the first run. The kernel's link check passed
on both tiles, with no recovery, when the test started and again when the
desktop took the display back.

That exit also exposed a stock bug. The compositor segfaults in aquamarine
0.15.0 after `Hyprland has reached the end.`: `~CDRMBackend` resets each
connector after disconnecting it, and disconnecting a later connector that owns
an output runs `flushAsyncCommitEvents()`, which dereferences the reset slot.
The global `backendInUse` in aquamarine's `Session.cpp` holds the backend until
static destruction, so this happens during `exit()`. On this iMac the 5K
stitch's DP-1 is the second connector with an output, so **the stock desktop
Hyprland crashes the same way at every logout and shutdown**: the journal has
one such segfault at every clean shutdown since 2026-09-21. It is not caused by
this patch and is unfixed upstream
([hyprwm/aquamarine#383](https://github.com/hyprwm/aquamarine/issues/383)). The
shutdown itself completes, so it is on hold; see `TODO.md`.

Before shipping:

- Validate real 5120×2880 10-bpc scanout and both panel tiles, gradients, cursor
  brightness, performance and recovery after suspend.
- Measure peak/black/gamma/primaries, and the backlight's own curve, with a
  colorimeter: `headroom.py` assumes it is proportional to luminance. Move its
  policy into the compositor, which knows when an HDR surface is visible, and
  validate tone mapping at reference/peak ratios other than 200/500.
- Define screenshot, screen-sharing and mirrored-output behaviour. Current SDR
  captures apply another tone map; in the nested test, reference white was
  229/255 in captures although the calculated panel code was about 168/255.
- Check real HDR applications beyond mpv, whose HDR10 playback is validated in
  the nested compositor. Decide whether to ship an mpv source-mode setting.
  HLG, browsers, games, ICC profiles, mixed monitors and saturated wide-gamut
  colours are not validated.
- Start the `hdr` module's install at a real login, and try sleep with it on.
  No kernel or EDID override is part of this work.

All source, build and test artifacts created for this experiment were outside
system installation paths.
