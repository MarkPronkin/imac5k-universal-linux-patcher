# HDR on the iMac18,3 (`hdr`, experimental)

`imac-patcher --apply hdr` gives the 2017 iMac's panel HDR the way macOS
does it. The panel cannot take an HDR signal: its EDID describes Display P3,
gamma 2.2 and 10 bits per channel, and no PQ transfer. So instead of sending
HDR10 to the panel, a patched Hyprland renders HDR content into the panel's
ordinary signal, with desktop white set below the panel's peak. The room above
desktop white is the HDR headroom: an HDR video's highlights are brighter than
any white window around them, as on a Mac. Apple calls this
[EDR](https://developer.apple.com/videos/play/wwdc2021/10161/).

The module is **experimental**. It never runs as part of `--apply safe` or
`--apply all`; name it or pick it in the menu.

## What it does to the picture

The profile estimates the panel's peak at 500 nits, Apple's figure for this
model, and puts desktop white at 200 nits. That is 2.5× headroom. Ordinary
white is therefore signal level `(200 / 500)^(1 / 2.2) ≈ 0.66` instead of
1.0, and only HDR content reaches full signal.

So **ordinary windows look dimmer than on the stock desktop**. Keep the
brightness at maximum: the profile assumes it, and at a lower backlight both
the desktop and the highlights scale down together. Both figures are
estimates, not measurements; a colorimeter would replace them.

To trade headroom for a brighter desktop, set your own values on the
built-in display's rule in `~/.config/hypr/monitors.lua`. For example, this
keeps white at 300 nits and leaves 1.67× headroom:

```lua
hl.monitor({ output = "eDP-1", mode = "preferred", position = "auto", scale = "auto",
             cm = "dp3", sdr_max_luminance = 300 })
```

`max_luminance` sets the panel peak the same way. Both are stock Hyprland
settings, so the file still loads if a login falls back to the stock
compositor (see below).

## Verified so far

On the iMac18,3 under Omarchy, with the same patch and build run as the
desktop through the HDR experiment (`experiments/hdr/`):

- A 10-bit EDR modeset of the stitched 5K panel, both tiles healthy, no
  amdgpu errors.
- HDR video in **Chromium** with Omarchy's default flags, nothing added.
- HDR10 video in **mpv** at 60 fps with no dropped or mistimed frames.
- A full day as the everyday desktop.

The module's own install was built and checked end to end in a scratch home
directory: the build, your real configuration verified through the wrapper
below, and the installed login check. It has **not yet started a real
login**, and **sleep with HDR on is untested**.

## Requirements

- iMac18,3. Other models need their own profile first; on them the module is
  n/a.
- Omarchy, or another Hyprland desktop that keeps its configuration in
  `~/.config/hypr/hyprland.lua` and starts through uwsm.
- **Hyprland 0.56.2**, the version the patch is written for. The module
  refuses any other.
- CMake 3.30 or newer, a C++ compiler, `make`, `patch` and `pkg-config`. The
  module offers to install `cmake`, `base-devel` and `pkgconf` when any are
  missing. Hyprland's own libraries and headers come with the `hyprland`
  package.
- About 10 minutes for the build and about 450 MB of temporary space in
  `~/.cache`. The installed compositor is 20 MB.

## Applying and removing it

```bash
imac-patcher --apply hdr
```

The build downloads checksum-pinned sources for Hyprland 0.56.2 and its
submodules, applies `patches/hyprland-0.56.2-edr.patch` without fuzz, and
builds the compositor. Before installing anything, it runs your whole Hyprland
configuration through the new build with `--verify-config`. Afterwards the
build tree is deleted; the verified downloads stay for a rebuild. Log out and
back in, or restart, to start it.

```bash
imac-patcher --remove hdr
```

Removal takes out every file the module wrote. A running HDR session keeps
going until you log out; the next login is stock.

`imac-patcher --status` reports `partial` when something needs attention and
says what underneath the table: Hyprland upgraded, an install from an earlier
release, or a missing piece. It also says when the install takes effect only
at the next login.

## What gets installed

Everything is in your home directory. Nothing system-wide changes, and no
package is replaced.

| Path | What it is |
|---|---|
| `~/.local/share/imac-patcher/hdr/Hyprland` | The patched compositor |
| `~/.local/share/imac-patcher/hdr/hyprland.lua` | The wrapper configuration (below) |
| `~/.local/share/imac-patcher/hdr/launch` | What each login starts |
| `~/.local/share/imac-patcher/hdr/hypr-edr.py` | The check the launcher runs |
| `~/.local/share/imac-patcher/hdr/build.json` | Hyprland version, patch hash and library versions of the build |
| `~/.local/share/wayland-sessions/hyprland.desktop` | The session entry |

Omarchy's login runs `uwsm start … hyprland.desktop`, and uwsm looks for that
entry in your own data directory before the system's. The module's entry
therefore replaces `/usr/share/wayland-sessions/hyprland.desktop` for you
alone, and runs `launch` instead of `/usr/bin/start-hyprland`. The launcher
starts the patched compositor through the stock `start-hyprland` watchdog, so
uwsm, the systemd session and crash recovery behave as they do on the stock
desktop. If `~/.local/share/wayland-sessions/hyprland.desktop` is already
yours, the module refuses rather than replace it.

## Your configuration

Your configuration runs unchanged, from the wrapper. Before loading it, the
wrapper intercepts `hl.monitor`, so every rule for the built-in display,
`eDP-1`, keeps your mode, position and scale and gains:

| Setting | Value | |
|---|---|---|
| `cm` | `"edr"` | always; stock Hyprland does not have this mode |
| `bitdepth` | `10` | always: 8 bits would band in the extra range |
| `supports_hdr` | `-1` | always: never switch the panel to PQ |
| `sdr_max_luminance` | `200` | unless your rule sets it |
| `max_luminance` | `500` | unless your rule sets it |

If you have no `eDP-1` rule, one is made from your catch-all rule. Other
outputs, including `DP-1`, the panel's second tile, are left exactly as you
configured them. Edits to your files reload automatically, as before.

## When Hyprland is upgraded

The build is linked against the Hyprland libraries installed when it was made,
and its configuration language is 0.56.2's. Before every login the launcher
checks that the system's Hyprland is still 0.56.2 and that its libraries
(aquamarine, hyprutils, hyprlang, hyprcursor, hyprgraphics) are the versions it
was built against. If not, that login starts the **stock compositor** instead,
and a notification says why. Your desktop is never left on a build that no
longer fits.

- Libraries updated, same Hyprland version: `imac-patcher --apply hdr`
  rebuilds.
- A new Hyprland version: HDR stays off until an imac-patcher release carries
  the patch for that version. Then `imac-patcher upgrade` and apply `hdr`
  again.

## Applications

- **Chromium** uses Wayland's colour-management protocol with Omarchy's default
  flags. Verified with HDR video.
- **mpv** uses it too. Its default tone curve plays HDR10 noticeably darker than
  the rest of the desktop. For the source's own brightness, use
  `--target-colorspace-hint=yes --target-colorspace-hint-mode=source`.
- **Firefox** has HDR behind `gfx.color_management.hdr`; untested here.
- Everything without colour management is SDR and appears at desktop white.

## Limits

- No HDR10 signal or metadata reaches the panel, and there is no local
  dimming: contrast is the panel's own. This is headroom over desktop white,
  not DisplayHDR.
- The 500 and 200 nit figures are estimates for a full backlight.
- The hardware cursor and direct scanout are off on the built-in display, so
  that nothing bypasses the colour conversion. Composition costs a little more
  GPU time and power than on the stock desktop.
- Screenshots and screen sharing are normalised to desktop white.
- Only the built-in display gets EDR. External displays keep their own rules.
- Sleep with HDR on has not been tried yet.
- Hyprland's own exit crash ([hyprwm/aquamarine#383](https://github.com/hyprwm/aquamarine/issues/383))
  happens with this build too; it is harmless, as on the stock desktop.

## Recovery

`imac-patcher --remove hdr` works from a text console as well
(Ctrl+Alt+F3, log in). Without the patcher, deleting the session entry is
enough:

```bash
rm ~/.local/share/wayland-sessions/hyprland.desktop
```

The next login is then the stock desktop. Keep the entry and the rest of
`~/.local/share/imac-patcher/hdr/` together: uwsm fails a login whose entry
points at a missing launcher, rather than falling back to the system entry.

## Development

The patch is `patches/hyprland-0.56.2-edr.patch`. The build, install and check
code is `scripts/hypr-edr.py`; the experiment's `experiments/hdr/build.py`
uses the same build. Test sessions, patterns, the HDR10 test clip and the
dynamic-headroom prototype are in [`experiments/hdr/`](../experiments/hdr/README.md).
The investigation is recorded in
[`notes/hdr-handoff-2026-09-22.md`](../notes/hdr-handoff-2026-09-22.md). Offline
tests are `tests/test_hdr.py`; the wrapper tests need a Lua interpreter.
