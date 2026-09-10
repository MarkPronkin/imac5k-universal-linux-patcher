# Handoff: resume-linkarm test, audio after resume, colours. 2026-09-10 ~12:45

## Update ~13:50 — SHELVED, needs additional testing

**Owner decision: shelve the colour problem for now; it needs additional
testing.** Do not continue investigating until the owner reopens it.

Where it ended:

- Relogin + full reboot (13:39 boot, still linkarm entry): colours **still
  off**. Verified after reboot: no HDR blob on connector 93, zero `HDR SB`
  lines this boot, `cm=dp3` applied, XRGB8888, scale 2. → The HDR-sideband
  theory is **falsified as the colour cause**. The aquamarine
  `restoreAfterVT()` zero-blob behaviour below is a real bug worth fixing on
  its own, but it is not what the owner sees.
- New key fact: this system was **reinstalled this morning** — `pacman.log`
  line 1 is an archinstall run into `/mnt` at 10:04. The reinstall reset the
  live `monitors.lua` (that's when `bitdepth = 10` was lost) and pulled in
  fresh packages (hyprland 0.56.2-2, aquamarine 0.15.0-2, mesa 26.2.2).
  Owner: "before work on suspend fix colors were fine".
- CM render test, inconclusive: fullscreen pure sRGB red via `imv -f
  /tmp/pure-red.png`, captured with `grim -t ppm` → pixels read (255,0,0), not
  the P3-re-encoded (~246,124,104). Either the dp3 transform is not running in
  the render path, or grim captures pre-CM in 0.56.2 — the follow-up source
  check was stopped; resolve that before trusting this test.
- Open suspects, in order: (1) missing `bitdepth = 10` in live monitors.lua
  (known-good config had it since Sep 6; restoring it is a modeset → genlock
  re-roll → needs owner OK); (2) this morning's package builds not actually
  applying the dp3 transform; (3) today's kernel patch-stack changes.

When resuming: first answer the screencopy-CM question (does grim capture
post-CM on 0.56.2), then re-run the red test; then try restoring
`bitdepth = 10` with owner OK. Reference images `/tmp/color-reference.png`
(6 bars) and `/tmp/pure-red.png` may be gone after reboot — regenerate if
needed.

## Update 13:36 — colour root cause found, relogin test in progress

**NOTE: the conclusion below was later FALSIFIED as the colour cause (see
13:50 update). The aquamarine behaviour described is real and still worth a
kernel-side suppression fix, but it does not explain the off colours.**

**Root cause of "colours like before the wide-gamut fix" (owner's hypothesis,
confirmed in source):** after a resume, aquamarine's `CDRMBackend::restoreAfterVT()`
(libseat/logind session re-activation) re-commits every connector with
`modeset=true` and **unconditionally** attaches its zero-initialized
`hdrMetadata` as a 32-byte all-zero `HDR_OUTPUT_METADATA` blob
(aquamarine v0.15.0: DRM.cpp:596/630-644, Atomic.cpp:586-606; normal commit
path in DRM.cpp:2728 is gated on `AQ_OUTPUT_STATE_HDR`, which is why the blob
was absent at boot). The kernel then sends an HDR Static Metadata SDP down eDP
(`fill_hdr_info_packet`, `amdgpu_dm.c:9706` in the linkarm build tree; logged
as `HDR SB:01 1a 00…` at 12:27:40, never at boot). The panel appears to react
to the SDP's presence → colours shift. Unfixed in aquamarine main; no
config/env suppresses it. The property is exposed by **mainline**
`amdgpu_dm.c` (~10515) for all eDP/DP/HDMI.

**Live state at the stop:** blob still attached on connector 93 (prop 8,
32 zero bytes; verify: `modetest -M amdgpu -c | sed -n '/^93/,/^95/p'`).
Cannot clear it from userspace — Hyprland is DRM master (`modetest -w` →
EACCES). CRTC 71 CTM is identity and GAMMA_LUT unset — normal for Hyprland's
shader-based CM, not the bug. eDP-1 max bpc=8 (live monitors.lua lost
`bitdepth = 10` in the 10:15 rewrite — separate open question, owner's call).

**Test in progress:** owner logging out/in (fresh session = gated commit path
= no blob). Reference image `/tmp/color-reference.png` (6 bars: sRGB R, G, B,
skin 255/200/150, mid-gray, white) was shown with `imv -f` — reopen after
login. Relogin re-rolls tile genlock (seam may return — separate issue).

**After relogin, verify:** (1) owner says colours look normal again;
(2) `modetest -M amdgpu -c` shows no blob value on connector 93;
(3) `journalctl -k -b | grep "HDR SB"` shows no lines after the relogin
(only the 12:27:40 ones). If all three → hypothesis confirmed.

**Then (agreed):** permanent fix = stop exposing `HDR_OUTPUT_METADATA` on the
internal eDP panel in the 5k patch stack (panel isn't HDR-capable; external DP
keeps it). Rebuild module in `~/.cache/kernel-5k-build-linkarm`, reboot,
re-run `pm_test=devices`, confirm colours survive resume. Still parked after
that: wire guard + both resume patches into installers, `platform` stage,
audio-after-resume fix is live-installed but uncommitted and untested on a
real resume (see "Audio" below).

## Original 12:45 record

Stopped mid-investigation at the owner's request: "colors look more like
before wide-color-gamut fix". Nothing is committed. Check Git and machine
state against this record before continuing.

## Machine state at the stop

- Booted `/Test - 5K-resume-linkarm` (`omarchy_linux-5K-resume-linkarm.efi`,
  amdgpu srcversion `22572AED4C06B4EB3C314CC`), boot at 12:24.
- All four sleep targets masked, `pm_test=none`.
- One `pm_test=devices` (deep) run at 12:27: PASS. Run dir
  `/var/tmp/imac-pm-devices-1h6yaq_r`. Recorded in the TODO.md checkpoint and
  in `patches/README.md`. `dm_complete()` armed link-health after resume
  (pass 1/8 healthy). Hyprland's HDR-metadata commit then re-armed it, and
  that run reached PASS 8/8.
- The owner has **not** answered whether the panel looked normal after the
  run, or which step comes next. The options were to wire the guard and both
  resume patches into the installers (recommended), or to run the `platform`
  stage.

## Audio (fixed live, repo edited, uncommitted)

After the 12:27 resume there was no sound, and only "Dummy Output" showed.
The filter-chain module of `imac-speaker-eq` had unloaded, but its process
kept running. The trigger is not understood: a WirePlumber restart re-creates
the card too, and the chain survives that. Details are in TODO.md under
"Audio after a resume".

- Fix in `scripts/imac-audio-jack-switch`. There is a new `reconcile()`, and
  the watcher also wakes on `'remove' on sink`. With the speakers in use and
  the tuned sink gone, it *restarts* the chain; `to_speakers` now uses
  `restart` when the sink is missing. There are 3 new tests in
  `tests/test_audio_jack.py`. The comment in `scripts/imac-patcher` was
  updated to match.
- Installed to `~/.local/bin/imac-audio-jack-switch` (identical to the repo
  copy) and the watcher was restarted. Verified by destroying the tuned sink's
  node: the chain restarted within 1 s and the default was restored. A real
  resume with the fix is **untested**.
- `./scripts/check.sh`: 230 tests OK. shellcheck is not installed.

## Colours (SUPERSEDED — root cause found, see "Update 13:36" above)

Facts gathered:

- Hyprland: `colorManagementPreset: dp3`, `currentFormat: XRGB8888` (8-bit).
  The kernel reports eDP-1 `max bpc` = 8, `Colorspace` = Default.
  `HDR_OUTPUT_METADATA` reads as all zeros. The kernel logged `HDR SB:01 1a...`
  twice at 213.35, after resume. No HDR SB line appeared at boot.
- The live `~/.config/hypr/monitors.lua` has `cm = "dp3"`, but **no
  `bitdepth = 10`**, and uses `scale = "auto"`. The repo's
  `configs/monitors.lua` has `bitdepth = 10` (`e3f66ed`) and `scale = 2`.
  The Hyprland log shows XR24 buffers from the first modeset at login, so the
  8-bit output predates the resume.
- The live file was rewritten at 10:15:32 today. Its backup,
  `monitors.lua.bak-1789028132` (646 bytes), is 12 bytes shorter: exactly
  `, cm = "dp3"`. That matches the patcher's `color` module apply
  (`scripts/imac-patcher` ~1150). So before 10:15 the file had neither `cm`
  nor `bitdepth`, and the colour module re-added only `cm`. No Claude
  transcript for this project mentions who ran it; an earlier Codex session
  is likely.

Not yet known: whether colours changed at the resume or were already off
since boot / 10:15. Hypotheses:

1. After resume, Hyprland's colour-management state (CRTC CTM / gamma LUT,
   the DCE path from `5a11e97`) wasn't re-applied, or the HDR-metadata commit
   changed it.
2. 8 bpc with no `bitdepth = 10` (`a169cea`: at 8 bpc `cm=auto` resolves to
   sRGB; `dp3` is explicit, so this is less likely on its own).

Next steps:

1. Ask the owner whether the colours changed right after the 12:27 test, or
   were already off.
2. Read the CRTC 71 colour properties: `modetest -M amdgpu -p`, CTM,
   GAMMA_LUT and DEGAMMA_LUT values. If CTM is missing or identity with
   `cm=dp3`, the colour management was dropped.
3. Before any fix, remember that a Hyprland reload or monitor re-apply is a
   fresh modeset, and the repo comment says any modeset re-rolls tile genlock.
   Get the owner's OK. Restoring `bitdepth = 10` in the live config is a
   separate question: the patcher's colour module doesn't write it, and it's
   the owner's call.

## Uncommitted changes (all of the working tree)

Pre-existing, not from this session: `AGENTS.md`, `scripts/imac-alt-entry`,
`notes/imac-pm-stage.py` (not executable; run it with `sudo python3`), the
three `patches/5k-*.patch` files, the stale `notes/standby-handoff-2026-09-10.md`,
and most of the TODO.md and `patches/README.md` checkpoint text.

This session: TODO.md (linkarm boot, devices PASS, audio entry),
`patches/README.md` (linkarm status), `scripts/imac-audio-jack-switch`,
`tests/test_audio_jack.py`, the `scripts/imac-patcher` comment, this note, and
the AGENTS.md pointer to it.
