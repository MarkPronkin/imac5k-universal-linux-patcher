# iMac 5K patch — how to use, and the rules that keep you safe

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
+ `imac5k-stitch-layer-7.x.patch`), and since 2026-09-08 the default stack also
includes the post-commit link-health recovery
(`5k-going-down-stop-resync.patch` + `5k-post-commit-link-recovery.patch`), the
fix for the stretched-5K boot. The verbose stack (full-stack patch + the
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
