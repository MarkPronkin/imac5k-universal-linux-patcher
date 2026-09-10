# iMac 5K patch — how to use, and the rules that keep you safe

For the CS8409 headset driver patch, see
[headphone setup and provenance](../docs/headphones.md). The display patch
stacks below are separate from those audio changes.

`imac5k-amdgpu-7.2.2.patch` is the complete native-5K stack for the iMac18,3's
internal tiled panel, as one diff against **kernel 7.2.2** source:

1. **Second-tile wake** — DPCD `0x4F1` root-latch pulse that powers up the
   hidden right-tile DP link (community work from
   [drm/amd#4455](https://gitlab.freedesktop.org/drm/amd/-/issues/4455) /
   [mcirsta/linux-imac-5k](https://github.com/mcirsta/linux-imac-5k), rebased
   to 7.2.2 by taprobane99)
2. **Single-display stitch** — presents both 2560×2880 tiles to userspace as
   ONE 5120×2880 output, so Hyprland (or any compositor) works unmodified
   (erik2's commits, hand-ported to 7.2.2)
3. **Genlock fix** — enables the per-frame CRTC reset for the Apple tile pair
   so both halves scan in lockstep (`sync_enabled=1`) and the panel is
   seamless under motion (mr_projects; fills a standing mainline TODO)

Boot parameter once installed: `amdgpu.tiled_stitch=1`

## Installing without a second kernel

**On Fedora KDE**, run `../scripts/imac-patcher --apply 5k` as your normal user
instead. The Fedora backend builds from the matching Fedora source RPM and
installs a module override through dracut and grubby; the Limine test-entry
workflow below is Omarchy-only. See [the Fedora guide](../docs/fedora-kde.md).

```bash
sudo ../scripts/patch-imac5k-amdgpu.sh          # build + swap the amdgpu module
sudo ../scripts/patch-imac5k-amdgpu.sh --restore  # undo everything
```

The script rebuilds **only the amdgpu module** for your *running* kernel and
swaps it in (stock module backed up first). Re-run it after a kernel update.

Since 2026-09-07 the installer builds the **lean pair** (`imac5k-lean-core-7.2.x.patch`
+ `imac5k-stitch-layer-7.x.patch`), since 2026-09-08 the default stack also
includes the post-commit link-health recovery
(`5k-going-down-stop-resync.patch` + `5k-post-commit-link-recovery.patch`), the
fix for the stretched-5K boot, and since 2026-09-10 the three suspend fixes
(`5k-logical-modeset-guard.patch`, `5k-resume-drop-cached-peer.patch`,
`5k-resume-arm-link-health.patch`, below). The verbose stack (full-stack patch + the
`5k-*.patch` follow-ups) is still available: `sudo env IMAC5K_STACK=verbose
../scripts/patch-imac5k-amdgpu.sh`.

The verbose stack includes the experimental slave-link recovery pair,
`5k-slave-link-verify-retrain.patch` then `5k-slave-link-preserve-lock.patch`.
The first check passed at stream enable yet the link later lost lock on the
2026-09-08 boot. The follow-up ports the lean stack's panel-latch HPD guard
and delays the lock checks, but its test boot also remained stretched:
the slave AUX returned EIO despite the early checks reporting lock.
A full DPMS off/on cycle restored healthy AUX status on both links, which
verified session recovery but not a boot fix. Both are superseded by the
post-commit patch below, and are kept for the record. See `TODO.md`.

`5k-post-commit-link-recovery.patch` follows them (with its going-down half in
`5k-going-down-stop-resync.patch` — the function it extends sits at a different
file position in each stack, and one patch cannot carry that hunk for both).
It moves the deferred check
after the *complete* atomic commit and re-reads both tiles' DPCD lane status up
to eight times (250 ms, then every 500 ms), running DC's link-loss recovery at
most twice per modeset when a tile is not locked. Its whole sequence is tagged,
so one command reads a boot:

```bash
journalctl -k -b 0 | grep 'APPLE5K: link-health'
```

The `build=post-commit-recovery` banner is logged at DM init, before any panel
is detected -- if it is missing, that module did not load. Each armed sequence
ends in one `PASS`, `FAIL` or `disarmed` line; on `recovery` and `FAIL` lines,
`root=`/`slave=` are per-tile health flags rather than attempt counts.

**Validated on hardware 2026-09-08:** first boot off this build came up at a
correct 5120x2880 with no VT or DPMS cycle, logging `PASS: both tiles healthy
after 1 recovery attempts` -- so the recovery ran and repaired the link before
anything reached the screen. Two details that boot corrected: the loss is *not*
slave-only (the unhealthy tile was the root, with lanes locked but sink status
0x205 = 00), and the AUX `EIO` seen earlier is a real transient that the same
recovery handles. The *cause* of the post-enable loss is still unknown -- this
repairs it after the fact. **Promoted to the default install stacks on
2026-09-08** after the owner confirmed the passing boot.

### Fedora 7.1.13 context

The lean pair also applies to Fedora `7.1.13-200.fc44`. Six hunks used to anchor
on adjacent 7.2-only firmware, HDMI, IRQ and atomic-commit code; they now anchor
on insertion points that are stable across both series. **The driver code the
patches add is unchanged** — only the surrounding match context moved. Both
patches apply in sequence at `--fuzz=0` to 7.2.x and to that Fedora source.

## Lean mainline candidate: `imac5k-lean-core-7.2.x.patch`

The upstream candidate: taprobane99's mechanism, reworked. **+355 code / +89
comment lines, 13 files** (his 7.2.3 base: +1631 / 12; the first lean pass was
+616 / +166). Same feature set as the machine runs:

- the panel-ID quirk, tile-peer wiring, `0x4F1` latch pulse, slave AUX
  pre-detect, source-table revision, stream-enable latch, root EDID re-read;
- **deterministic genlock** (both tile streams flagged before the master pick);
- **clean firmware handoff at reboot** (atomic shutdown with the going-down
  gate, slave registers cleared, root panel off for T12) — without it Apple's
  firmware draws a skewed boot logo on every warm reboot;
- **no self-inflicted re-detects**: HPD on a slave that already has its sink
  is the pulse our own latch write causes, not a plug event.

What the rework changed (lean4, 2026-09-07): the six per-role quirk flags are
two (`apple_tiled_root` / `apple_tiled_slave`) and the nine `dc_link_*` inline
helpers three; the two near-identical AUX-ready polls are one helper
(`link_apple_5k_slave_aux_ready`); `dpcd_set_link_settings()` is back to its
mainline shape with a per-write retry for the second tile instead of a
rewritten function; the panel-latch/DPCD constants live in one header; the
leftover `dmi.h`/`utsrelease.h`/`grph_object_id.h` includes from the logging
era are gone; comments say why, once. Behaviour is unchanged except the
link-config retry, which now retries each failed write rather than the whole
block.

Compiles clean; applies with zero rejects to pristine 7.1.9 and 7.2.2. Kernel
exposes two proper tiles; the compositor stitches (Mutter today, KWin in
progress). Posted upstream in drm/amd#4455.

## Stitch layer on top of it: `imac5k-stitch-layer-7.x.patch`

erik2's single-display stitch (`amdgpu.tiled_stitch`, slave tile non-desktop)
as a layer that applies **on top of** the lean core, plus the two
stitch-specific boot fixes: the early modeset before Plymouth (full-width
disk-password prompt) and the settle-and-resync after tiled commits.
**+1038 code / +276 comment lines, 10 files.** Both installers ship it, so a
compositor sees one output whether or not it supports DRM tiling — Hyprland has
no tile support, and it keeps KWin from having to stitch the halves itself.
Upstream will not take this layer.

```bash
patch -p1 < patches/imac5k-lean-core-7.2.x.patch     # core (+ genlock + reboot handoff)
patch -p1 < patches/imac5k-stitch-layer-7.x.patch    # Hyprland stitch (+ early modeset, resync)
patch -p1 < patches/5k-going-down-stop-resync.patch  # halt the resync worker on shutdown
patch -p1 < patches/5k-post-commit-link-recovery.patch  # stretched-5K boot fix
patch -p1 < patches/5k-logical-modeset-guard.patch      # stitch-layer BUG_ON fix
patch -p1 < patches/5k-resume-drop-cached-peer.patch    # stale peer on resume
patch -p1 < patches/5k-resume-arm-link-health.patch     # link-health after a clean resume
```

The last two apply on top of either stack: the lean pair and the full verbose
stack alike (verified at `--fuzz=0` on the lean pair over pristine 7.1.9).

Applies cleanly on pristine 7.1.9 and 7.2.2 after the core. One fix over
erik2's original: the saved tile-group id buffer is 9 bytes like DRM's
(`drm_tile_group.group_data[9]`); it was 8. erik2's own logging is still in
this layer; leaning it is a later pass.

**Equivalence:** core + layer is the same feature set as the verbose stack
(`imac5k-amdgpu-7.2.2.patch` + the five `5k-*.patch` increments), minus the
core-side logging.

**Status: promoted to the default on 2026-09-07** (lean3, with the slave-HPD fix: 0 re-detect rounds per boot instead of 3, no link-enable failures) after two boots from its own
entry (full-width password prompt, seam fine, straight Apple logo on the warm
reboot out of it). The verbose module is kept as the `/Test - 5K-verbose-fallback`
entry and as `amdgpu.ko.zst.prev-promote` beside the installed module; drop
both once the lean default has run for a few days.

### iMac Pro (iMacPro1,1): Vega 64X, DCE 12

Only the 5K module has been tried on the iMac Pro.

These patches ship in the default **lean** stack on both Arch backends and
Fedora. The verbose fallback does not include them and does not support the
iMac Pro. Hardware verification below is the contributor's Omarchy result;
Fedora, GRUB, and Vega 56 remain untested on this model.

The lean pair on its own leaves the iMac Pro's panel stretched 2x: the second
tile trains but never locks video, and the panel scales the one tile it sees
across the whole display. Four small patches on top of the lean pair fix it,
verified on iMacPro1,1 / Radeon Pro Vega 64X, kernel 7.1.8.

- **`imacpro-slave-dp-panel-mode.patch`** — the root cause. `dp_get_panel_mode()`
  gives the second tile `DP_PANEL_MODE_EDP`, which sets the alternate scrambler
  reset bit in DPCD `0x10A`. The iMac Pro panel's second tile does not accept it:
  the link trains (training patterns are unscrambled) but SINK_STATUS `0x205`
  stays `00`. Captured from the same panel brought up by Apple's firmware:
  `0x10A = 00`, `0x205 = 01`. Toggling that one bit on a working panel breaks and
  restores 5K reversibly. Keyed on the panel ID (`APP 0xAE1D` / `0xAE1E`); the
  iMac18,3 panel keeps eDP panel mode.
- **`dce120-enable-crtc-reset.patch`** — DCE 12's timing generator never wired
  `.enable_crtc_reset`, so the per-frame CRTC reset that genlocks the tiles could
  not be armed on Vega. Adds it, selecting GSL group 0 as the trigger source.
  DCE 12 only by construction.
- **`dce12-multisync-master-first.patch`** — `enable_timing_multisync()` hands the
  hwseq only the slave pipes, but the DCE hwseq takes its GSL master from entry 0
  and arms entries 1..n. With no master, the armed slave waits for a trigger that
  never comes (`GSL: Timeout on reset trigger!`). Puts the master first, on
  `DCE_VERSION_12_0` only.
- **`dce110-genlock-master-from-pipe0.patch`** — when entry 0 is the master, derive
  `gsl_master` from its TG instance instead of the hardcoded `0` (as
  `dce110_enable_timing_synchronization()` already does), and skip a missing
  `enable_crtc_reset`. With a slaves-only list nothing changes.
- **`5k-resync-postpone-on-modeset.patch`** — with the tiles engaged on the iMac
  Pro, the post-commit pass queued by the greeter's modeset fell due in the
  middle of the compositor's modeset and ran the timing sync while a timing
  generator was down: one `TG counter is not moving!` and one `GSL: Timeout on
  reset trigger!` per boot with that timing, repaired by the next pass 250 ms
  later. `queue_delayed_work()` (chosen so plane commits do not postpone an armed
  check) is kept for plane commits; a modeset uses `mod_delayed_work()` again, as
  the stitch layer did. Zero errors on the same DCE 12 patches without the
  post-commit patch, across four boots.

Hyprland must enable the panel at bit depth 10. On the iMac Pro the tile pair latches
only when the stream is brought up at the panel's native 10 bpc.
The patcher updates active single-line `hl.monitor({ ... })` rules for the
internal eDP output, using the default output rule if no eDP rule exists. It
preserves comments, disabled and explicitly configured external outputs, and
other iMac models' bit-depth settings. It backs up the file and leaves the
change for the next compositor start.

The post-commit scheduling follow-up applies **after** the three suspend
fixes in `test`; its context retains the resume-arming branch. The lean stack
was checked at `--fuzz=0` against pristine Linux 7.1.13 and 7.2.3 during the
merge review. See [the review record](../notes/imacpro-pr2-review-2026-09-10.md)
in the Git checkout for compile results and limits.

## Crash fix: `5k-logical-modeset-guard.patch`

**Status: promoted into both installers on 2026-09-10** after passing
`pm_test` freezer and devices cycles on the `/Test - 5K-modeset-guard` entry.

The stitch layer's "accept logical root modeset without reprogramming" shortcut
(`amdgpu_dm_tiled_stitch_has_live_root_stream()`, identical in both stacks)
judges the root stream live from the *old* CRTC state. By the time it runs, the
disable pass of the same atomic check has already removed that stream from the
new state, so every time the shortcut fires the kernel hits
`BUG_ON(dm_new_crtc_state->stream == NULL)` in `dm_update_crtc_state()`. The
oops ends the compositor's commit with the display locks held: the screen
freezes for good, which looks like a hard hang.

It fires on any commit that marks the lit panel `mode_changed` while leaving it
on, such as HDR output metadata switched on or off, or a colorspace or
content-type change. On 2026-09-10 it fired right after a `pm_test` freezer
cycle, when Hyprland's first commit added an SDR-EOTF HDR metadata blob:

```
TILED_STITCH: accept logical root modeset without reprogramming connector=eDP-1 crtc=71 ...
kernel BUG at ../display/amdgpu_dm/amdgpu_dm.c:13678!
```

The patch lets the shortcut keep only a stream the new state still holds, so
those commits take mainline's full remove-and-add modeset, the path every boot
already takes. It applies last, at `--fuzz=0`, on top of either full stack on
7.2.3. Suspend testing needs it first: the only staged suspend test so far
ended in this crash.

## Resume fix: `5k-resume-drop-cached-peer.patch`

**Status: promoted into both installers on 2026-09-10** after passing
`pm_test` freezer and devices cycles on the `/Test - 5K-resume-peer` entry.
It is built on top of `5k-logical-modeset-guard.patch`.

`dm_destroy_cached_state()` releases the cached root stream before the resume
commit, but not the stitched CRTC's `stream_peer`. The resume commit then sees
the stale peer, skips creating a new one, and the plane split fails:

```
dc_state_add_plane: Existing stream not found; failed to attach surface!
```

`drm_atomic_helper_resume()` returns an error that `dm_resume()` ignores, and
the stale peer's reference leaks. The panel only came back because a later
commit took the normal path. The patch releases the peer next to the root
stream.

On the `/Test - 5K-resume-peer` entry, a `pm_test=devices` (deep) cycle
resumed with every device callback returning 0. The resume commit itself added
a fresh peer, with no `Existing stream not found`, and the panel came back
normal.

## Resume follow-up: `5k-resume-arm-link-health.patch`

**Status: promoted into both installers on 2026-09-10** after a passing
`pm_test=devices` cycle on the `/Test - 5K-resume-linkarm` entry. It stacks on
`5k-post-commit-link-recovery.patch` and `5k-resume-drop-cached-peer.patch`.

With the resume commit working, a resumed panel was never link-health checked
or timing-synced. Both are queued at the end of each tiled modeset commit, and
that queue skips commits made while `adev->in_suspend` is set, which includes
the resume commit. The patch notes such a modeset, and a new DM `.complete`
hook arms both once `amdgpu_device_resume()` has cleared `in_suspend`.

On the `/Test - 5K-resume-linkarm` entry, a `pm_test=devices` (deep) cycle
armed the check from the new hook right after `resume of devices complete`.
Its first pass was healthy before `PM: suspend exit`. Hyprland's first commit
after resume (an HDR metadata change) then forced a full tiled modeset, which
re-armed the check, and that run reached `link-health PASS` with 0 recoveries.
On this desktop a post-resume modeset always follows. So the resume-armed
run's own 8/8 PASS, with no intervening modeset, has not been observed.

## Booting any build from its own entry: `scripts/imac-alt-entry`

```bash
sudo scripts/imac-alt-entry add  5K-lean path/to/amdgpu.ko   # new UKI + Limine entry
sudo scripts/imac-alt-entry list
sudo scripts/imac-alt-entry drop 5K-lean
```

Builds a separate UKI from a private copy of the running kernel's module tree
(`mkinitcpio --moduleroot`), so `/usr/lib/modules`, the default UKI and any
other test entry are untouched. Refuses a module whose vermagic is not the
running kernel, and verifies the module inside the built UKI is the one given.
The entry is hash-pinned like the others.

## The rules

- **RULE 1 — version gate.** The patch is verified against kernel **7.1.x and 7.2.x source** (same diff applies to both).
  The script refuses to run on any other series, because the amdgpu display
  code changes between kernel versions and a mis-applied patch means a broken
  GPU module. When Arch/Omarchy moves to 7.3+, the patch must be **re-ported
  by a human first** — re-running the script is not enough. (Check
  `uname -r` starts with 7.1 or 7.2 before expecting anything.)

- **RULE 2 — test on the USB clone first.** Never run this for the first time
  on your only install. The project keeps a full bootable clone on a USB
  stick for exactly this. If a build ever produces a bad module you get
  software rendering until `--restore` — recoverable, but not fun to discover
  on your daily machine.

- **RULE 3 — the vermagic must match.** The script verifies the built
  kernelrelease equals `uname -r` and refuses otherwise. If it ever refuses,
  that's it working as designed — don't force it.

- **RULE 4 — this is a bridge, not the destination.** The endgame is
  upstreaming (tracked in drm/amd#4455, where the iMac18,3 result and the
  genlock fix have been posted). Once merged into mainline, stock kernels
  will do all of this and these patches retire.

## Known good configuration (verified 2026-09-02, iMac18,3)

- Kernel 7.2.2 + this patch, `amdgpu.tiled_stitch=1`, Omarchy/Hyprland
- Result: genuine 5120×2880, both tiles HBR2×4, 10-bpc, `sync_enabled=1`,
  seamless under motion, zero GPU faults
- Expected quirks: GNOME-keyring popup on a cloned system (benign), YouTube
  4K is CPU-decoded (Polaris has no VP9/AV1 hardware — a silicon limit,
  unrelated to this patch)
