# TODO

Open items for the iMac18,3 patch. Root causes are recorded here so nobody has
to re-derive them.

## Resume checkpoint — 2026-09-10 (suspend: the freeze is a stitch-layer BUG)

**A staged suspend test ended in a kernel BUG in the stitch layer, not a
firmware hang.** At 10:58 Codex ran `notes/imac-pm-stage.py freezer` (deep,
all four sleep targets still masked). Tasks froze and thawed normally: the 5 s
test delay is in dmesg (1873.12 to 1878.25) and `suspend_stats` counted a
success. 200 ms after `PM: suspend exit`, a Hyprland commit hit:

```
TILED_STITCH: accept logical root modeset without reprogramming connector=eDP-1 crtc=71 ...
kernel BUG at ../display/amdgpu_dm/amdgpu_dm.c:13678!   BUG_ON(dm_new_crtc_state->stream == NULL)
RIP: dm_update_crtc_state+0x3c1/0xa60 [amdgpu]   Comm: Hyprland
```

The oops left the display locks held and the screen froze until a
power-cycle. Evidence is in `hardware-private/modeset-guard/`: the kernel and
full logs, and the pm_test run directory.

**Cause.** `amdgpu_dm_tiled_stitch_has_live_root_stream()` checks the *old*
state's stream. Everything that sets `mode_changed` runs before the disable
pass (`drm_atomic_helper_check_modeset()` and
`amdgpu_dm_connector_atomic_check()`), and that pass removes such a CRTC's
stream from the new state. So the shortcut crashes every time it fires. Here
the trigger was HDR output metadata going from none to an SDR-EOTF blob
(`HDR SB:01 1a 00...` right before the BUG), which amdgpu treats as entering
HDR. It fired nowhere else in the retained journal (three boots).

**What this changes in the suspend record.** The 2026-08-28 "Apple firmware
S3" conclusion is unsupported: hibernate was recorded hanging the same way,
and hibernation never enters S3. Those hangs also stopped at `PM: suspend
entry`, before any thaw, so they are a separate failure that is still
unlocated; the remaining pm_test stages can find it. README still states the
firmware cause. Correct it once those stages have run.

### Candidate fix, booted and passing the freezer trigger (test entry only)

`patches/5k-logical-modeset-guard.patch` keeps only a stream the new state
still holds, so these commits take mainline's full modeset. Applies at
`--fuzz=0` on top of either full stack (verified on pristine 7.2.3). Not wired
into either installer.

Built for `7.2.3-arch1-3`, srcversion **`AECDF2CBEC6CD3806C8CE05`** (installed
default: `ABF2FCDC5A956FB87F81368`). Module:
`hardware-private/modeset-guard/amdgpu.ko.zst` (stripped, zstd -19). Build
tree: `~/.cache/kernel-5k-build-guard/linux-7.2.3`, a reflink copy of the
installer's tree; its unstripped `amdgpu.ko` decodes any later oops.

### Next steps

1. **Done 11:38.** Booted `/Test - 5K-modeset-guard` (`LoaderImageIdentifier`
   `omarchy_linux-5K-modeset-guard.efi`); srcversion `AECDF2CBEC6CD3806C8CE05`.
   Clean boot: tiled modeset, link-health PASS 8/8 with 0 recoveries, no BUG.
   The first `add` attempt stopped at "embedded cmdline mismatch" with nothing
   installed. mkinitcpio 41.1 (installed 2026-09-10) squeezes runs of spaces
   in the cmdline it embeds, and this machine's cmdline has a double space
   (`rootfstype=btrfs  resume=`). `imac-alt-entry` now compares cmdlines with
   whitespace runs collapsed, which is how the kernel splits them.
2. **Done, PASS.** `freezer` (deep) rerun at boottime 161.8 s, run dir
   `/var/tmp/imac-pm-freezer-p5luvuj5`: `reached_test_delay: true`, success 1,
   no restoration errors. The same trigger recurred: `HDR SB:01 1a` 200 ms
   after `PM: suspend exit`. This time it produced `added peer slave-tile
   stream` (a full tiled modeset), then link-health PASS with 0 recoveries.
   No BUG, oops or `accept logical root modeset` anywhere in the boot. The
   masks and `pm_test=none` were restored afterwards.
   Still to do: wire the patch into both installers so the default entry
   gets it. **Done 2026-09-10: all three suspend patches (guard,
   drop-cached-peer, arm-link-health) are wired into the lean and verbose
   stacks of `patch-imac5k-amdgpu.sh` and the lean stack of
   `fedora-imac5k`, verified applying over pristine 7.2.3 and at --fuzz=0
   over pristine 7.1.13, and shipped in release 9.9.11-test. The audio
   chain-restart fix shipped in the same release.**
3. Then `devices`, `platform`, `processors` and `core`, one per run and only
   with the owner's go-ahead each time: any of them can hang for real.
   Keep all four sleep targets masked throughout.
   - **`devices`: PASS, with one resume bug.** Run dir
     `/var/tmp/imac-pm-devices-5a38x2_m`, boottime 289.7 s: every device
     callback returned 0 (slowest: amdgpu resume 948 ms, wiphy suspend
     504 ms), then link-health PASS with 0 recoveries. No BUG and no
     brcmfmac errors. The SATA link took about 6 s to come back ("slow to
     respond", then up at 6 Gbps).
   - **Resume bug:** during amdgpu resume the log shows
     `dc_state_add_plane: Existing stream not found; failed to attach
     surface!`. `dm_destroy_cached_state()` releases the cached `stream` and
     both plane states but not `stream_peer`. The resume commit's enable pass
     sees the stale peer, skips creating a fresh one, and the peer-plane attach
     fails. `drm_atomic_helper_resume()` returns an error that is ignored, and
     the stale peer's reference leaks. A later hotplug commit restored the
     panel. The guard is not involved: it needs an old-state stream, and
     resume starts from a disabled CRTC. There's no baseline in the retained
     journal, since this was the first devices-level resume there.
   - **Candidate fix, built, not yet booted:** `patches/5k-resume-drop-cached-peer.patch`
     releases `stream_peer` in that loop. It applies at `--fuzz=0` to the
     guard build tree (lean) and to a scratch full stack plus guard (offset -2).
     In that scratch build, `5k-genlock-settle-resync.patch` rejected one
     hunk at `--fuzz=0`; this is unrelated and not investigated.
     Built on top of the guard, in a reflink copy of its tree at
     `~/.cache/kernel-5k-build-peer/linux-7.2.3` (unstripped `amdgpu.ko`
     there). The guard tree is untouched. srcversion
     **`EAD6EF9581BD92D565F826E`**, vermagic `7.2.3-arch1-3`, no build
     warnings. Module: `hardware-private/resume-peer/amdgpu.ko.zst`. Next:
     `sudo scripts/imac-alt-entry add 5K-resume-peer hardware-private/resume-peer/amdgpu.ko.zst`,
     boot `/Test - 5K-resume-peer`, confirm the srcversion, and rerun
     `freezer` and then `devices`.
     Pass criterion: no `Existing stream not found` on a devices-level resume.
     **Booted 12:05** (`LoaderImageIdentifier`
     `omarchy_linux-5K-resume-peer.efi`, srcversion `EAD6EF9581BD92D565F826E`
     confirmed): tiled modeset, link-health PASS twice with 0 recoveries, no
     BUG, oops, `accept logical root` or `Existing stream not found`. All four
     sleep targets masked, `pm_test=none`.
     **`freezer` (deep): PASS**, boottime 207.1 s, run dir
     `/var/tmp/imac-pm-freezer-b5ud2eou`: `reached_test_delay: true`, success
     1, no restoration errors. The HDR trigger recurred (`HDR SB:01 1a` at
     213.23, 0.6 s after `PM: suspend exit`) and again took the full tiled
     modeset (`added peer slave-tile stream`), then link-health PASS with 0
     recoveries at 217.04. No BUG, oops, `accept logical root` or
     `Existing stream not found` in the boot. Masks and `pm_test=none`
     restored.
     **`devices` (deep): PASS, and the pass criterion is met.** Run dir
     `/var/tmp/imac-pm-devices-5sr1jamt`, boottime 332.5 s. Every device
     callback returned 0 (amdgpu suspend 161 ms, resume 573 ms; wiphy suspend
     503 ms). There's no `Existing stream not found`: the resume commit itself
     logged `added peer slave-tile stream` at dmesg 339.73, before
     `resume of devices complete` at 340.95. No BUG or oops. Masks and
     `pm_test=none` restored. The owner confirmed the whole panel looks
     normal afterwards.
   - **New gap: a clean resume is never link-health checked.** The resume
     commit runs from `dm_resume()` inside `amdgpu_device_ip_resume()`,
     while `adev->in_suspend` is still set (it is cleared at the end of
     `amdgpu_device_resume()`). `amdgpu_dm_queue_tiled_resync()` skips
     commits made while it is set, so it doesn't arm link-health or queue
     the tile timing sync, and no later modeset came to arm them. Before the
     fix, the failed resume commit forced a post-exit modeset, and that
     modeset armed the check. Next: arm both once resume completes (owner
     chose this over the `platform` stage, 2026-09-10).
   - **Candidate fix, booted, `devices` PASS (test entry only):**
     `patches/5k-resume-arm-link-health.patch`. When the only reason for the
     skip is `in_suspend`, the queue notes the tiled modeset, and a new DM
     `.complete` hook arms link-health and the timing sync after
     `amdgpu_device_resume()` returns. It applies at `--fuzz=0` to the peer
     tree (exact) and to the guard tree (offset -5). Built in a reflink copy
     of the peer tree at `~/.cache/kernel-5k-build-linkarm/linux-7.2.3`
     (unstripped `amdgpu.ko` there). srcversion
     **`22572AED4C06B4EB3C314CC`**, vermagic `7.2.3-arch1-3`, no build
     warnings. Module: `hardware-private/resume-linkarm/amdgpu.ko.zst`.
     **Booted 12:24** (`LoaderImageIdentifier`
     `omarchy_linux-5K-resume-linkarm.efi`, srcversion
     `22572AED4C06B4EB3C314CC` confirmed): tiled modeset, link-health armed
     three times and PASS twice with 0 recoveries, no BUG, oops,
     `accept logical root` or `Existing stream not found`. All four sleep
     targets masked, `pm_test=none`.
     **`devices` (deep): PASS, the hook arms on its own.** Run dir
     `/var/tmp/imac-pm-devices-1h6yaq_r`, boottime 203.5 s, success 1, every
     device callback 0, no restoration errors. The resume commit added a
     fresh peer at 212.97 (no `Existing stream not found`). `dm_complete()`
     then armed link-health at 213.02, and pass 1/8 was healthy at 213.13,
     both before `PM: suspend exit` at 213.16. At 213.35 Hyprland's
     HDR-metadata commit (`HDR SB:01 1a`) forced the usual full tiled modeset
     and re-armed the check. That run went to PASS 8/8 with 0 recoveries at
     217.17. So the resume-armed run completed only 1 of 8 checks before it was
     superseded. On this desktop a post-exit modeset always follows, so the
     "no intervening modeset" part can't be shown here. The timing sync logs
     nothing visible. No BUG, oops or `accept logical root`. Masks and
     `pm_test=none` restored.
     Pass criterion was: `link-health armed after tiled
     modeset` followed by `link-health PASS` after resume, still with no
     `Existing stream not found`.
   - **Audio after a resume: the speaker tuning was left without its sink.**
     After the 12:27 `devices` run the owner reported no sound, with only
     "Dummy Output" in the picker. The kernel side was fine: both HDA cards
     resumed and returned 0. WirePlumber had re-created every device (serials
     above the login clients'), and `imac-speaker-eq`'s filter-chain module had
     unloaded. Its `pipewire -c` process kept running with no sink and no
     PipeWire socket, so `Restart=on-failure` never fired. The jack watcher
     ignored the card events because the jack state had not changed, and its
     `systemctl start` is a no-op on such an instance. The trigger is not
     understood: a WirePlumber restart also re-creates the card, and the chain
     survives that one and relinks.
     Fix in `scripts/imac-audio-jack-switch` (installed to `~/.local/bin` and
     live): the watcher also wakes on `'remove' on sink`. With the speakers
     in use and the tuned sink gone, it *restarts* the chain. Verified live by
     destroying the tuned sink's node: restarted within 1 s and the default was
     restored. A real resume with the fix is still untested. New tests are in
     `tests/test_audio_jack.py`.
   - Remaining stages: `platform`, `processors`, `core`.

`notes/imac-pm-stage.py` now finds its test window with a `/dev/kmsg` marker.
Its timestamp filter missed the delay line because the printk clock runs
behind `CLOCK_BOOTTIME`, so the 10:58 run reported `reached_test_delay: false`.

Codex's desktop `standby` command (lock plus DPMS off, no kernel suspend) was
discarded with `git restore` at 10:58; `notes/standby-handoff-2026-09-10.md`
still describes it as staged. Its new files survive as unreachable Git blobs
until `git gc` prunes them (two weeks by default): `scripts/imac-standby`
`92909fe`, `e920602`, `ade9d10`; `docs/standby.md` `474f145`, `0931d71`;
`tests/test_standby.py` `c9e98b6`, `a058cf8`. Its edits to tracked files are
gone.

## Resume checkpoint — 2026-09-08

**The post-commit link-health candidate WORKS. First clean boot: 02:09.**
Owner confirmed a normal, unstretched desktop straight out of the
**Test - 5K boot fixes** entry, with no VT cycle and no DPMS cycle. This is the
first boot fix in this line of work — every earlier "success" was session
recovery after the fact.

Evidence for that boot, `hardware-private/post-commit-recovery/pass-boot-0209.log`:

- `srcversion` = `D6E34F13001AF8D6C5A6E90`, so the candidate is what loaded.
- `card1-eDP-1` enabled at `5120x2880`; Hyprland reports one 5120x2880@59.982
  monitor, scale 2.
- Three armed sequences, each ending `PASS`. The first needed one recovery.

**The failure is not slave-only.** On the first tiled modeset the unhealthy
link was **link[0], the root tile**:

```
pass 1/8  link[0] aux=1 lanes=4 status=77 77 81 00 00 00 ready=0
          link[1] aux=1 lanes=4 status=77 77 01 01 00 00 ready=1
recovery 1/2 root=0 slave=1
```

Lanes were fully locked (`77 77`) and align was done, but **sink status 0x205
was `00` — the sink was not receiving** — with bit 7 of 0x204 set, i.e. the
sink flagging LINK_STATUS_UPDATED. That is a different signature from the
CR-only slave failure recorded below, and it is on the other tile. After the
recovery, 0x205 went to `01` and stayed there for passes 2-8.

The third sequence also caught the AUX `EIO` signature from the 01:37 failed
boot, mid-flight rather than at boot: pass 4/8 read `link[1] aux=-1
status=00 00 00 00 00 00`, recovery ran, a fresh tiled modeset armed, and it
passed 8/8 clean. So the transient AUX failure is real and recoverable, not a
measurement artifact.

**What this does and does not establish.** It establishes that reading DPCD
after the complete commit detects the loss, and that DC's link-loss recovery
repairs it before the user sees anything. It does not establish the *cause* of
the post-enable loss, and one boot is not evidence about a race: the failure
did not reproduce at all in the second and third sequences (`0 recovery
attempts`). Gather repeat-boot evidence before promoting.

### Where it stands

- Staged and booted; the default entry still carries the known-good module.
- `sudo scripts/imac-test-entry promote` makes it permanent, `drop` discards it.
- **Promoted into the installers on 2026-09-08** at the owner's request: the
  default (lean) stack of both `patch-imac5k-amdgpu.sh` and `fedora-imac5k`
  now applies `5k-going-down-stop-resync.patch` +
  `5k-post-commit-link-recovery.patch`. The going-down hunk was split into its
  own patch because `amdgpu_dm_apple5k_going_down()` sits at a different file
  position in the lean and verbose stacks and GNU patch locates hunks in file
  order. Verified applying at `--fuzz=0` on the lean pair over pristine 7.1.9,
  and on the full verbose chain.

### Build provenance

Built for `7.1.9-arch1-2`, srcversion **`D6E34F13001AF8D6C5A6E90`** (the old
default is `0580ADB03337B21F464071D`). Module:
`hardware-private/post-commit-recovery/amdgpu.ko.zst` (stripped, zstd -19, the
same packaging the installer uses). `patches/5k-post-commit-link-recovery.patch`
is last in the verbose stack: it moves the deferred work after the *complete*
atomic commit and, for a tiled modeset, re-reads both tiles' DPCD lane status
eight times — 250 ms, then every 500 ms. An AUX error, incomplete lane lock or
absent sink reception counts as failure and runs DC's own link-loss recovery
(blank/disable/enable), at most twice per modeset, slave last; the final
observation is reserved for verification.

Offline fault injection covers healthy scanout, AUX failure, delayed success,
lane/sink validation, active-pair guards, bounded recovery, suspend/reset/
shutdown guards and the modeset budget:

```bash
python3 hardware-private/post-commit-recovery/sync-test.py   # keep the copy honest
gcc -o /tmp/hc hardware-private/post-commit-recovery/health-check-test.c && /tmp/hc
```

`sync-test.py` re-copies the four functions out of the driver, so the test can
never drift into testing a stale copy of the logic.

### Reading a boot

One tag covers the whole sequence:

```bash
journalctl -k -b 0 | grep 'APPLE5K: link-health'
```

Expect, in order: `build=post-commit-recovery ...` (logged at DM init, before
any panel is detected — **if this line is absent the candidate did not load**,
check `/sys/module/amdgpu/srcversion` against the value above), `armed after
tiled modeset`, then numbered `pass N/8` lines each carrying both links'
`aux=`, `lanes=` and raw `status=` bytes, and finally one of:

- `PASS: both tiles healthy after N recovery attempts` — with `N>0` the
  recovery worked; with `N=0` the failure did not reproduce this boot.
- `FAIL: unrecovered after N attempts root=.. slave=..` — recovery ran and the
  tile still would not lock.
- `disarmed: ...` — the checks stopped before reaching a verdict (no DC state,
  no active tiled pair, or a pass skipped for suspend/shutdown). The reason is
  on the line.

On `recovery` and `FAIL` lines, `root=`/`slave=` are per-tile *health* flags,
not attempt counts: `root=0 slave=1` means the root tile was the unhealthy one.

Still capture the owner's visible result alongside the log; a logged PASS alone
is not sufficient, as the 01:37 boot demonstrated for the earlier build.

### Restaging after a kernel update

The staging that produced this boot, for reference — run from the repo root:

```bash
KREL=$(uname -r); M=/usr/lib/modules/$KREL/kernel/drivers/gpu/drm/amd/amdgpu/amdgpu.ko.zst
sudo cp -f "$M" "$M.prev-5k"                                  # today's default = known-good
sudo cp -f hardware-private/post-commit-recovery/amdgpu.ko.zst "$M"
sudo depmod "$KREL"
sudo limine-mkinitcpio                                        # current UKI now carries the candidate
sudo scripts/imac-test-entry stage "$M.prev-5k"               # that UKI becomes the test entry
```

Earlier this session, in order:

**Update after booting the test entry (01:37 boot): FAILED.** The owner
reported a stretched desktop. Running `srcversion` is
`DFC9A1AD3EACA2EEC021236`, confirming the intended test module loaded.
Hyprland reports 5120x2880, scale 2, XRGB8888, with no config errors.
All three initial slave-link checks reported locked, and the panel-latch
HPD guard ran. Suppressing those re-detects is therefore insufficient.

Before any display changes, AUX0 at 0x200 returned
`01 00 77 77 01 01 00 00`; AUX1 returned EIO, including with the previously
working byte-by-byte `dd` method. Sysfs confirms AUX1 belongs to DP-1.
This differs from the earlier CR-only reads: no valid slave lane-status
bytes were obtained, so do not describe this boot as measured CR-only.
EIO alone does not establish whether the sink powered down or another AUX
failure occurred.

A tty1 -> tty3 -> tty1 cycle did **not** recover the picture (owner
confirmed). It also produced no new stream-enable/link-training log,
so this particular VT cycle did not force the required link restart.

An explicit DPMS off/on cycle, with a three-second delay, did run the
stream-enable sequence again (boot time ~324 s). Both AUX devices then
returned `01 00 77 77 01 01 00 00`. The owner confirmed the desktop now
looks normal. This verifies session recovery, not a boot fix.
On installed Hyprland 0.56.2, use the Lua dispatch form:
`hyprctl eval 'hl.dispatch(hl.dsp.dpms("off"))'`, then after three seconds
`hyprctl eval 'hl.dispatch(hl.dsp.dpms("on"))'`. The old
`hyprctl dispatch dpms off` form is rejected without changing state.
Always arrange the `on` call in a finally/trap so the screen returns.

Evidence: `hardware-private/link-recovery/failed-test-boot.log` (captured
before recovery) and `failed-test-after-dpms.log`. No driver/config/boot
artifacts changed during this diagnosis. The test is not ready to promote.
Next driver investigation needs link status after the entire commit and
settled scanout, including AUX failures; another early "locked" message
is not a sufficient success criterion.

Previous checkpoint, retained for build provenance:

Stopped after installing **Test - 5k-link-recovery** in Limine. The owner
confirmed the current desktop was normal after a VT round trip and will
reboot into the test entry next. The new build has NOT been boot-tested or
promoted. Default UKI and installed module hashes were verified unchanged.

On resume, capture evidence BEFORE any reload, VT switch or modeset:

1. Read `uname -r` and `/sys/module/amdgpu/srcversion`. The test build is
   `7.1.9-arch1-2` / `DFC9A1AD3EACA2EEC021236`; the old default is
   `0580ADB03337B21F464071D`. `modinfo` reads the installed default file,
   so it does not identify which module the test entry actually loaded.
2. Read both AUX devices at 0x200 for eight bytes with root privileges.
   Healthy lane bytes (0x202/0x203) are `77 77`, align (0x204) has bit 0
   set (`01` or `81`), and sink status (0x205) is `01`. Record raw bytes.
3. Capture boot kernel logs for `slave tile link`, `re-train result`,
   `ignoring panel-latch HPD`, and `detect connection link[1]`. Check the
   owner's visible result; a logged lock alone already proved insufficient.
4. If stretched again, preserve that evidence, then use the known VT
   recovery and verify both links afterward. If clean, gather repeat-boot
   evidence before treating this as resolved or promoting the build.

Artifacts and logs: `hardware-private/link-recovery/` (gitignored), including
the source/build tree, `amdgpu.ko.zst`, build logs, captured kernel log,
`limine-before.conf`, and `default-before.json`. The follow-up patch is
`patches/5k-slave-link-preserve-lock.patch`, after
`patches/5k-slave-link-verify-retrain.patch` in the verbose installer.
Existing changes in `scripts/imac-patcher` predate this recovery work;
preserve them. Nothing was committed or published.

## Stretched desktop: a tile loses link lock (5K, MITIGATED — cause still open)

**Mitigated 2026-09-08** by `patches/5k-post-commit-link-recovery.patch`, which
detects the loss after the complete commit and repairs it; see the resume
checkpoint at the top for the passing boot and for why the failure is not
slave-only. The cause of the post-enable loss is still unknown, so the analysis
below stands as the record of what was measured.

**Root-caused 2026-09-08 on iMac18,3 / kernel 7.1.9-arch1-2, verbose stack.**
On the measured stretched boots, the second tile's DP link has clock recovery
but no equalisation or symbol lock, so tile B receives no valid symbols and
the panel stretches tile A across the glass. The later 01:19 reboot proves
that initial training can succeed and the lock can be lost afterward; see
the follow-up below.

Read on the slave AUX after a stretched boot, with the root as control:

| DPCD | root eDP-1 (tile A) | slave DP-1 (tile B) | slave after `chvt` cycle |
|---|---|---|---|
| 0x202/0x203 lane status | `77 77` CR+EQ+symbol lock | `11 11` **CR only** | `77 77` |
| 0x204 interlane align | `01` done | `00` | `81` |
| 0x205 sink status | `01` receiving | `00` | `01` |
| 0x100/0x101 | `14 84` | `14 84` | `14 84` |
| 0x206/0x207 adjust req | `00 00` | `00 00` | `00 00` |

Diagnostic shortcut worth remembering: **half-dark panel = dual mode with one
tile unlit; stretched panel = the slave link is dead.** They are different
faults and the section below is only about the first.

A `chvt 3; chvt 1` cycle re-trains the link and fixes it for the session, with
identical parameters and the identical code path — so this is a race, not a
misconfiguration.

**Why five patch iterations missed it:** nothing in either stack reads back
0x202-0x204. `APPLE5K: link-config final ... status=1` is the status of the
*config write*, not of training; boot logs five such "successful" rounds while
the link sits at CR-only. The one guard that exists,
`link_apple_5k_slave_aux_ready()`, polls `DP_DPCD_REV` over **AUX** — which
answers regardless of main-link state (`elapsed_ms=0`, returns on attempt 0) —
so it adds no settling and proves nothing about the link.

Ruled out by measurement; do not re-derive:
- **0x4F1 latch.** Written and `readback=0x01` on both links at every
  stream-enable. The wake works.
- **ASSR / scrambler.** `0x00D = 00` on *both* links — neither sink advertises
  ASSR capability — yet `dp_get_panel_mode()` is patched to return
  `DP_PANEL_MODE_EDP` for the tiled slave, so the slave carries `0x10A = 01`
  and the root `00`. It trains fine with `0x10A` still `01`. Not this bug,
  though forcing ASSR against a sink that does not advertise it is worth
  revisiting on its own.
- **Signal integrity.** The sink never requests more swing or pre-emphasis.

**First recovery patch built and booted 2026-09-08; insufficient:**
`patches/5k-slave-link-verify-retrain.patch`, wired into the **verbose** stack's
`EXTRA_PATCHES`. It adds `dp_tiled_slave_link_locked()` and
`dp_relock_tiled_slave_link()` to `link_dpms.c` and calls the latter from
`enable_stream_features()`, immediately after `dp_write_tiled_stream_enable_latch()`
— i.e. with the stream unblanked and the latch re-asserted. Up to four rounds;
each round settles `20 ms * (attempt + 1)` and then calls
`dp_perform_link_training()` at the current link settings.

It deliberately does **not** re-assert `0x4F1` inside the loop: the latch already
reads back 1, writing it pulses the slave's HPD, that write is itself a suspect
for knocking the freshly trained link down, and on stacks without lean3's
HPD-ignore fix each write costs a full re-detect round. Re-asserting would risk
repeating the fault the loop is recovering from, and could never converge.

Applies cleanly to the 7.1.9 tree. **Verbose only** — the lean core names the
guard `dc_link_is_apple_tiled_slave()` rather than
`dc_link_needs_tiled_stream_enable_latch()`, so it needs a one-line port before
it can go in the installer default. Do that after it is verified on hardware.

**Follow-up after the 01:19 reboot (2026-09-08):** the running module's
`srcversion` matched the installed build (`0580ADB03337B21F464071D`), and all
six stream-enable checks logged `locked after 0 re-train(s)`. Nevertheless,
live AUX reads found root `77 77 / 81 / 01`, slave `11 11 / 80 / 00`
(lanes / align / sink). Thus the link can lose lock **after** the check;
the first patch was installed correctly but checked too early.

The last check was followed by two `DETECT_REASON_HPD` slave detects.
Unlike the lean core, this verbose stack still re-detects on its own latch
pulse. A VT round trip (`tty1 -> tty3 -> tty1`) restored both links to
`77 77 / 01 / 01`; the owner confirmed the desktop looked normal.

`patches/5k-slave-link-preserve-lock.patch` follows the first recovery patch
in the verbose installer. It ports the existing lean HPD guard, waits before
the first lock read and after each re-train, and checks the final re-train
before declaring failure. It also ports the lean stitch layer's 9-byte
tile-group buffer fix, after the compiler caught the verbose stack passing
an 8-byte buffer to DRM functions that read nine bytes. That overread is a
separate defect, not established as the link-loss cause.

The HPD re-detect is the leading explanation for
the post-check loss, not yet a reboot-confirmed cause. The lean default is
unchanged. Reboot validation must check both AUX status and the visible
panel, since immediate log messages alone already gave a false reassurance.

Build validation: complete amdgpu module compiled for `7.1.9-arch1-2`,
`srcversion=DFC9A1AD3EACA2EEC021236`. The full verbose sequence applies to
fresh 7.1.9 source using the installer's normal patch settings (older base
hunks require fuzz); the new follow-up applies at `--fuzz=0`. All three
changed source files match the clean-stack result. The final incremental
build removes the tile-buffer overread warning; the initial build also
reported an existing unused `aconnector` variable in `amdgpu_dm_helpers.c`.
BTF generation was skipped because the source tree has no `vmlinux`.

Installed as the separate Limine entry **Test - 5k-link-recovery**
(`/boot/EFI/Linux/omarchy_linux-5k-link-recovery.efi`). The helper verified
the embedded module byte-for-byte and verified its command line. SHA-256
checks confirmed that the default UKI and installed module were unchanged.
The initial packaging attempt stopped before installation because mkinitcpio
squeezes spaces in the command line; the menu contained a doubled separator.
The successful attempt used the default UKI's embedded command line after
verifying its argument list matched the menu. Reboot into the test entry
and confirm the display plus AUX status before promoting it.


Verify with the DPCD read, which is stack-independent and is the ground truth —
a locked slave reads `77 77` / `81` / `01`:

```
dd if=/dev/drm_dp_aux1 bs=1 skip=512 count=6 status=none | od -An -tx1
journalctl -k -b | grep 'slave tile link'
```

**Fix direction:** after the slave stream-enable sequence completes — i.e.
after the final `0x4F1` write, which pulses the slave's HPD — read 0x202-0x204
and retrain if EQ, symbol lock or interlane align are not all set; retry a few
times with a delay. Replace the AUX-readiness guard with this link-status
check, or keep both. Stopgap until then: force a modeset after boot.

Reproduce the reads with plain `dd` on the AUX chardevs (decimal offsets):

```
dd if=/dev/drm_dp_aux1 bs=1 skip=512 count=6 status=none | od -An -tx1   # 0x200-0x205
dd if=/dev/drm_dp_aux1 bs=1 skip=518 count=2 status=none | od -An -tx1   # 0x206-0x207
```

Enable DC's own training log with dynamic debug (it is all `pr_debug`):

```
echo 'file drivers/gpu/drm/amd/display/dc/link/protocols/link_dp_training*.c +p' \
  > /sys/kernel/debug/dynamic_debug/control
```

## Display — two boot artifacts (5K only)

**Patch layout (2026-09-06):** the boot-artifact work is split by confidence.
`patches/5k-early-modeset.patch` (half-dark password prompt, confirmed on
hardware) is applied by the installer and is what `Omarchy → linux` runs.
`patches/5k-genlock-settle-resync.patch` and `patches/5k-latch-clear.patch`
(skewed Apple logo) were promoted to the default on 2026-09-06 after a captured
teardown and a straight logo. `patches/5k-latch-clear-going-down-only.patch`
(promoted the same evening) restricts the latch clear to the reboot path; the
installer applies all five on top of the main patch. The default's module is
also kept at `~/.cache/kernel-5k-build/amdgpu.ko.zst.latch-going-down`. The `Test - 5K boot fixes` entry is gone; `Test - 5K-lean` belongs
to the lean-patch work and stays. A copy of the
default's module is kept at `~/.cache/kernel-5k-build/amdgpu.ko.zst.early-modeset`
for `imac-test-entry stage`.

Also observed: `limine-mkinitcpio` **preserved** both hand-added test entries,
`default_entry` and `timeout` across a regeneration (installer run, 2026-09-06),
so the "a regeneration drops the test entry" caveat in `imac-test-entry` is
weaker than stated.

Both root-caused. The password-prompt one is fixed and shipped; the Apple-logo one is
still open — see the patch layout note above.

### Skewed Apple logo on warm reboot (cold boot is fine)

**2026-09-07, control with `reboot=pci`:** booted the pre-logo-fix module
(verbose core + stitch, no shutdown handling) with `reboot=pci` on the cmdline;
warm reboot gave a **straight logo**. So a hard PCI reset alone hides the woken
tile — which is why taprobane99 (who runs `reboot=pci`) never sees the skew.
Cost: a visibly longer black gap before the Apple logo (fuller firmware
re-init), and the ramoops region did not survive the reset (pstore empty
afterwards), so crash/shutdown captures are lost. The driver-side handoff in
the lean core gives the straight logo at normal reboot speed and keeps
ramoops; it stays. Not adopting `reboot=pci`.


The patch writes the panel-latch DPCD `0x4F1 = 1` to wake the slave tile in four
code paths, and **never tears it down** — there is no shutdown hook, `.remove`,
or suspend handler anywhere in the diff. The woken state therefore survives a
warm reboot, and Apple's firmware — which assumes the factory single-link state —
draws its boot logo into a panel configuration it doesn't expect. A cold boot
power-cycles the panel, which is why it looks correct then.

**Fix, second attempt (in the test entry now):** mirror the enable path.
`dp_write_tiled_stream_disable_latch()` writes `0x4F1 = 0` on root and slave
from `link_set_dpms_off()`, after `blank_stream()` and before `disable_link()`
— the stream is already dark, so nothing on screen can skew, and AUX is still
up. Every modeset then leaves the panel exactly as a cold boot found it; the
existing wake/train/enable-latch sequence brings it back. On reboot the
suspend-path display teardown runs this naturally.

**Why the mirror alone was not enough (measured, 2026-09-05):** over
`/dev/drm_dp_aux0` the clear takes effect instantly — root and slave both read
back `00` — but the panel raises HPD-RX and the detect path rewrites `01` within
2–10 ms (`detect connection ... reason=2` followed by `root wake 0x4F1`). At
reboot the stream-off runs before IRQs are suspended, so that interrupt wins.
`dc.apple_5k_going_down`, set from `amdgpu_pci_shutdown()` before teardown,
turns both wake paths into no-ops so the clear is the last word. In the test
entry. **Tested once, 2026-09-06: the Apple logo was still skewed** after a
warm reboot out of the test build (build identity confirmed from the
`stream-disable latch` lines that boot logged — not from the early-boot marker,
which that boot's truncated journal had lost).

Two readings remain, and reasoning cannot separate them: the clear did not run
in the final teardown (which happens after journald is gone, so it has never
been observed), or clearing the latch is not enough. To settle it, `ramoops` is
armed on the test entry only: `memmap=1M$0xa6b000000 ramoops.mem_address=…
ramoops.console_size=0x80000 ignore_loglevel` on its cmdline, plus
`/etc/systemd/system/ramoops-test.service` (conditional on that cmdline) to
load the module. After the next warm reboot out of the test entry,
`/sys/fs/pstore/console-ramoops-0` should hold the previous kernel's last
messages, including the teardown. Secure Boot is off, so `systemd-stub` honours
Limine's cmdline.

**Capture attempt 2026-09-06, lost:** the boot after the warm reboot landed on
`Omarchy → linux` (no `memmap` reservation, ramoops never loaded), so the
reserved region was reused and the teardown log with it. The owner also
reported the capture boot as "numbers on black" — that was `ignore_loglevel`
spraying the kernel log over the console — and a sheared desktop after login
(the intermittent genlock loss, not specific to that build). On request the
experimental entry was dropped and the test entry recreated as an exact clone
of `Omarchy → linux`; the harness is removed. The latch-clear work stays in
`patches/5k-latch-clear.patch` for whoever picks it up.

**Control experiment, run 2026-09-06:** warm reboot out of `Snapshots › 2`
(stock amdgpu, 4K fallback): Apple logo **straight but soft** — the firmware
fell back to single-link cleanly. After a 5K session it skews. So the patch is
the cause, and the state left behind is more than `0x4F1`: a shutdown clear of
that latch alone (with the wake paths gated) did not help. Prime remaining
suspect is the vendor source-table write at DPCD 0x310 on the slave link, which
stock never touches. Next step is evidence, not another guess: a silent kmsg
dump into reserved RAM at reboot is now armed on the default cmdline
(`printk.always_kmsg_dump=1` + ramoops; `/etc/default/limine`), readable from
`/sys/fs/pstore/dmesg-ramoops-*` on the following boot.

Gotcha found the hard way (first capture reboot came back empty): `ramoops`
refuses kmsg dumps above its `max_reason`, which defaults to OOPS (2); a
reboot dumps with reason SHUTDOWN (4). It needs `ramoops.max_reason=4` as well
as `printk.always_kmsg_dump=1`. Both are now on the cmdline. This kernel has
no `CONFIG_PSTORE_PMSG`, so there is no marker channel to test RAM survival
separately -- an empty dump on the next boot means the firmware does not
preserve that RAM across a warm reboot.

**Captured, 2026-09-06 20:24 (`evidence/shutdown-kmsg-2026-09-06.log`):** the
ramoops dump of the previous kernel's final messages — and it settles it. At
reboot **the display is never turned off.** The last commits (7 s before
reboot, the shutdown splash) still carry both streams; there is no
stream-disable, no zero-stream commit, nothing from the DM between the final
unmounts and the reboot. The very last thing the driver does — 80 ms before
`reboot: Restarting system` — is an HPD-RX re-detect of the slave that writes
the wake latch again (`root wake 0x4F1 stage=slave-predetect`, then
`stage=source-dpcd`). Apple's firmware therefore inherits a live, latched,
dual-tile panel. Every latch-clear attempt hung off the stream-disable path,
which simply does not run on this reboot path — so none of them ever executed
where it mattered.

**Fix, in the test entry:** `amdgpu_pci_shutdown()` now calls
`drm_atomic_helper_shutdown()` for the tiled panel (what i915 does in its
shutdown hook), with the going-down guard set first. That disables every CRTC
through a normal atomic commit, which runs the stream-disable latch clear, and
the re-detect can no longer re-wake the tile. Folded into
`patches/5k-latch-clear.patch`. The next dump will show whether it ran.

**Captured again, 20:38 (`evidence/shutdown-kmsg-2026-09-06-b.log`), from the
test build with the display shutdown:** it works as designed. `atomic-disable`
runs at 83.00 s, `stream-disable latch 0x4F1=0` at 83.08 s (status OK on both
links), then the HPD-RX re-detect fires as before — but with the wake paths
gated it finds the slave's AUX **dead for 300 ms** and gives up (`slave AUX
poll failed`, then the DP fallback candidates fail too), i.e. the tile stayed
asleep. Reboot at 84.86 s. So the panel is handed to the firmware with the
latch cleared and the second tile down — the state every earlier attempt was
aiming for and never reached. Cost: ~1.7 s of futile AUX polling at shutdown,
trimmable by also gating the pre-detect poll once the logo result is in.

**Captured 21:16 (`evidence/shutdown-kmsg-2026-09-06-f.log`), corrected test
build — and the owner saw a straight Apple logo.** Teardown in order:
`atomic-disable` (116.31 s) → `going-down slave reset 0x310=00 00 00, 0x10A=00`
(116.38, both OK) → `stream-disable latch 0x4F1=0` (116.38, OK on both links)
→ `going-down root eDP power off, holding T12` (116.45) → S5 at 117.16 →
reboot. No re-detect, no wake: the `link_detect()` gate held. One sample so
far; the fix is in the test entry (`patches/5k-latch-clear.patch`), default
untouched, pending the owner's decision to promote.

Two earlier attempts on the same day failed for reasons that had nothing to do
with the panel: capture -d showed the pre-detect poll skip made the shutdown
re-detect drop the slave sink before its stream disable ran, and the test
cycle before that ran the untouched default. The lesson is in the evidence
directory: never judge a shutdown-path change without the capture.

**Resolved 2026-09-06 (evening) — the jump and the black flashes were not
the re-sync.** A build that measured both tiles' scan positions before every
re-sync found them aligned on all 35 checks (0 re-syncs run), so the analysis
below was chasing the wrong thing. The real cause was the latch-clear patch
itself: `dp_write_tiled_stream_disable_latch()` cleared the second tile's wake
latch (0x4F1) on every ordinary stream-off, not only when going down. Each
latch write toggles that tile's HPD line; DM answers an HPD pulse with a full
`dc_link_detect(DETECT_REASON_HPD)`, which drops the sink, sets
`link_state_valid = false` and sends userspace a hotplug event, so the next
commit fails `pipe_need_reprogram()` for the slave pipe, tears the tile down,
re-trains it — and writes the latch again. Per boot: 30–40 slave re-detects,
36 re-trainings, 19 stream-offs (the pre-logo-fix builds had 4, 14 and none).
Fix: the whole disable-latch write is now gated on `apple_5k_going_down`
(`patches/5k-latch-clear-going-down-only.patch`). Verified boot: 4 re-detects,
11 trainings, 0 stream-offs, root link never re-trained, native 5K at 10-bit;
the owner reports the flashes and the pre-reboot skew are gone. The
measured-resync build was dropped as inert. Lesson: `journalctl -k` for older
boots is the cheapest regression test — compare the same counters across
builds before theorising.

Leftover, cosmetic: the warm-reboot Apple logo is straight but slightly soft.
After the teardown the firmware sees a single-tile panel (second tile asleep,
its registers reset) and draws the logo on one tile stretched across the
glass; a cold boot draws it crisp. Making the firmware draw at 5K would mean
handing it a panel with both tiles awake, which is exactly the state that
produced the skew — so any attempt has to find a state the firmware treats as
"fresh dual-tile" rather than "already running". Untested; not worth a
regression in the straight logo.

**Original analysis (superseded, kept for the record):** right after the
disk-encryption password is accepted the whole prompt box visibly shifts,
goes black, then the 5K desktop comes up clean. The boot log shows a burst of fbdev/Plymouth commits at ~14.7 s each
followed by `manual-trigger-sync` — the 250 ms settle-and-resync doing its
one-shot CRTC alignment on a live picture. It is the re-sync working, seen.
Timeline from the boot after the successful capture: the journal's first
15 s are lost (no `Linux version` line), so nothing *before* the prompt is
observable; *after* Enter there are **7 modesets and 4 delayed re-syncs in
90 ms** (14.67–14.76 s) ending exactly at the unlock (`first mount of
filesystem` at 14.76 s) — Plymouth's dialog transition and the fbdev/DRM
master handoff, each modeset blanking and each re-sync visibly realigning the
tiles. Then the compositor's own modesets at 18–21 s bring the clean 5K
desktop. On a single-tile panel this is a blink; here it is a jump.
Refinement if wanted: run the alignment before the first frame is shown
instead of after, or debounce the re-sync across a burst.

The same thing, mirrored, is visible for a moment *before* a reboot. Capture
2026-09-06-g, last 8 s of a session on the promoted build: the compositor's
exit hands the display to the shutdown splash through two modesets
(641.39, 641.61 s); each turns the slave stream off (latch cleared), re-trains
the slave link (three times the second round) and turns it back on, and the
tiles run unaligned until the delayed re-sync lands (642.10, 642.36 s) — that
window is the brief skew. The going-down sequence itself, 6 s later, is
clean: `atomic-disable` → slave registers reset → latch cleared → panel power
off → reboot. Same cause as the post-password jump, same refinement.

**Control experiment (original note):** boot the pre-5K `Snapshots › 2` entry
(stock amdgpu, `video=eDP-1:3840x2160@60e`, overlayfs root) and warm-reboot out
of it. If the Apple logo skews even then, the 5K patch is not the cause, and
the entire latch-clear stack should be removed.

**If the logo is still skewed after that**, the latch theory is wrong — the
panel state the firmware trips over is something other than 0x4F1 — and the
whole latch-clear stack should be removed rather than extended.

**First attempt, removed:** clearing the latch from `amdgpu_pci_shutdown()`.
That ran while the shutdown splash was still being scanned out, so the splash
itself skewed on the way down — and it did not fix the firmware logo either.
It also logged only at `DC_LOG_DC` (debug), so it could never be confirmed
from the journal. The replacement logs at info level; after a warm reboot out
of the test entry, this proves it fired at the previous shutdown:

```
journalctl -k -b -1 | grep 'stream-disable latch'
```

### Blinks during the password prompt and at session start/exit (both builds)

Real kernel timestamps (dmesg, not journalctl -o short-monotonic — the journal
stamps early kernel lines with its own import time, ~14 s, which misled a first
read): amdgpu module load starts at 2.05 s, its init only runs at 6.01 s, fb0 at
6.38 s, the early modeset lands 1 ms later, cryptsetup prompt at 8.3 s. Between
6.4 s and 8.3 s there are **four more modesets**, and the verbose log shows why,
in strict order each time: stream enable → root latch + slave latch write (0x4F1)
→ `detect connection link[1] reason=2` (DETECT_REASON_HPD) on the slave →
connector-update → hotplug uevent → userspace re-modesets → atomic-disable /
atomic-enable → re-train → latch write → HPD… Three rounds until it settles.
Writing the latch pulses the slave's own HPD line; the driver treats its own
side effect as a plug event. Each round is one black blink, at the prompt and
again at session start (18–21 s) and at session exit. Same on the lean pair.

**Fixed 2026-09-07 (lean3, promoted):** `link_detect()` ignores
`DETECT_REASON_HPD` on a tiled slave that already has its sink; HPD-RX is
untouched. Re-detect rounds per boot 3 → 0, "enabling link 1 failed" gone,
modesets before the LUKS prompt 5 → 3. What remains is not the driver's: the
firmware→amdgpu takeover at 5.7 s (one frame), Plymouth's first two paints at
7.6 s (plane updates, not modesets), the 1.4 s black between Plymouth quitting
(15.8 s) and Hyprland's first modeset (17.3 s), and Hyprland's own config pass
at 19.7 s (three commits in 3 ms: aquamarine test commit, real commit, 10-bit
switch). A seamless splash→compositor handoff would be a Plymouth/Omarchy
arrangement.

**Measured, not the patch:** the 4 s between "module verification failed"
(2.1 s) and "unknown parameter" (6.1 s) is the kernel's own module loading for
a 30 MB module. On this machine xfs (8.7 MB) loads in 0.67 s, i915 (10.7 MB) in
0.64 s, nouveau (7.4 MB) in 0.41 s — it scales with size, and the stock amdgpu
is 33 MB (it carries 2.9 MB of BTF that ours lacks), so stock is no faster.
Decompression is not it: an uncompressed xfs insmod takes the same 0.68 s. So
5K cannot appear earlier than ~6.4 s with a modular amdgpu on this kernel; the
firmware framebuffer covers the gap. Nothing to do in the patch.

### Half-dark panel at the disk-encryption password prompt

An earlier note here claimed the 5120 mode goes live ~130 ms before the slave
tile wakes. **That was wrong.** From the boot log, the wake is early and fine —
`root wake 0x4F1 stage=slave-predetect` fires at 5.702 s, *before* the stitched
mode is published at 5.908 s. The real gap is elsewhere:

| t | event |
|---|---|
| 5.702 s | slave tile woken (`stage=slave-predetect`) |
| 5.908 s | `TILED_STITCH: exposed only stitched mode 5120x2880 on eDP-1` |
| 5.911 s | `fbcon: amdgpudrmfb (fb0) is primary` + `Deferring console take-over` |
| 5.93–6.84 s | thunderbolt / nvme / usb-storage / sdhci probing |
| **7.069 s** | `added peer slave-tile stream` — **first atomic modeset** |
| 7.10–7.12 s | slave link trained, `stream-enable latch 0x4F1` |

The slave tile only gets a DC stream during an atomic modeset (the stitch block
in `amdgpu_dm_atomic_check`), and `drm_client_setup()`'s initial fbdev config
deliberately stops short of committing one — `__drm_fb_helper_initial_config_and_unlock()`
probes, sets up the crtcs and calls `register_framebuffer()`, then leaves the
commit to a later hotplug or to fbcon taking over the console. With `quiet splash`
fbcon defers take-over, so that first commit landed **1.16 s** after fb0 went
live. For that whole window the panel presents the full-width stitched mode
while only the root tile scans out — long enough to cover the password prompt,
which Plymouth draws across all 5120 px (the initramfs carries `plymouth` and
`encrypt` hooks via `omarchy_hooks.conf`).

**Fix, implemented:** after `drm_client_setup()`, if this device drives a stitched
tile panel, issue a second `drm_client_dev_hotplug()`. That takes the
`dev->fb_helper` path, which *does* commit, so the peer tile stream is created
during probe instead of whenever something else happens to trigger a modeset.

### DP-1 phantom output (cosmetic, low priority)

`hyprctl` lists DP-1 as a disabled connector. It is functionally correct — the
kernel drives the panel over both links (`master_link[1]`) and the stitch depends
on it. **Do not disable it from the compositor**; that risks the fused output.
Clean fix is patch-level: mark the slave connector `non-desktop` so compositors
ignore it without powering it down.

## GPU video encode (VCE) hang

Hardware encode via VAAPI can hang the GPU: `ring vce0 timeout` → full GPU reset →
`VRAM is lost` → the Wayland session dies. Seen from both an ffmpeg transcode
(file-manager preview pipeline) and `gpu-screen-recorder`.

Ruled out: macroblock alignment, sandboxing/app version, file corruption. Hardware
*decode* of the same file is fine. RADV exposes no `VK_KHR_video_encode*` on
Polaris, so VCE is the only encode silicon — there is no alternate API.

Leads, in order:
1. **Mesa radeonsi encode path** — Mesa builds the VCE command stream, so this may
   be a driver bug rather than firmware. Bisect encode parameters (rate control,
   GOP/IDR, reference frames, slice config, dimensions) against the reproducer.
2. **Kernel `VCE VM mode`** — boot log says VCE runs in VM mode, which has a
   history of hang bugs on Polaris. Check `vce_v3_0.c` for the gating.
3. **Blast-radius reduction** — per-ring recovery instead of full-chip reset; and
   GL robustness in Hyprland/aquamarine so a reset doesn't kill the session.

Blunt fallback that works by construction: `amdgpu.ip_block_mask=0xfffffeff`
masks out VCE entirely — no hardware encode, hang impossible.

**Test safely:** reproduce from `multi-user.target` over SSH, not from a desktop
session, so a GPU reset costs nothing. Capture the devcoredump at
`/sys/class/drm/card*/device/devcoredump/data` on the first controlled repro.

## Hardware not yet covered

| Item | State |
|---|---|
| Wi-Fi `clm_blob` | Confirmed missing (`no clm_blob available`) → limited channels |
| Backlight | `acpi_video0` exists, pinned at max — needs a functional test |
| Ambient light sensor | Exposed by applesmc (`light`) — unused; could drive auto-brightness |
| SD card reader | `sdhci-pci` bound — untested (needs a card) |
| HDMI audio | 7 devices present — untested |
| Built-in Ethernet | Driver up, `NO-CARRIER` — untested (needs a cable) |
| Bluetooth | Controller powered — pairing untested |

## Housekeeping

- Upload `.github/social-preview.png` in GitHub Settings → Social preview
  (no API for this; must be done in the web UI).
- `\EFI\BOOT\BOOTX64.EFI` on this ESP is a *copy of the UKI*, not the Limine
  binary. It was found 2 days stale after a module rebuild — the firmware taking
  that fallback path would have booted the previous initramfs with the previous
  amdgpu module. `imac-patcher` already synced it; `patch-imac5k-amdgpu.sh` now
  does too. Anything that rebuilds the UKI must refresh it.

## Boot chain on this machine

Three EFI system partitions exist, but only one belongs to Omarchy:

| Partition | Disk | Contents |
|---|---|---|
| `nvme0n1p1` (2 GB, `OMARCHY`) | internal WD Blue SN5000 | Limine — Omarchy's own, stock |
| `sdb1` (200 MB, `EFI`) | USB "My Passport" | OpenCore (`EFI/OC/OpenCore.efi`), for macOS |
| `sdc1` (200 MB, `EFI`) | USB "WDC WD20NMVW" | Empty; same filesystem UUID as sdb1, i.e. a clone |

Firmware `BootOrder` is `0001,0080,0081` — `Boot0001 Omarchy` points at
`\EFI\limine\limine_x64.efi` and is first; the two `Mac OS X` entries follow.

### Non-stock: the Limine fallback bypass

Stock Omarchy sets `ENABLE_LIMINE_FALLBACK=yes` (see
`/etc/limine-entry-tool.d/omarchy-defaults.conf`), and `limine-install` acts on
it by placing **Limine** at `\EFI\BOOT\BOOTX64.EFI`.

On this machine that file is a copy of the UKI instead, with the real Limine
renamed `BOOTX64.LIMINE.EFI.unused`. Timestamps date the change: Limine was
written to both locations on 2026-08-28 12:29 (install), and `BOOTX64.UKI.BACKUP`
— a 75 MB UKI — appeared 2026-08-30 17:01, during the black-screen
troubleshooting. It was done to work around a "no config found" failure.

**Consequence:** booting via the ESP's default path (which the Mac's startup
picker uses when you select the EFI volume) shows *no menu at all* — a UKI has
none — and boots straight into whatever that copy holds. That is why a chosen
boot entry can appear to be ignored.

Confirmed by the owner from the two observed routes:

| Route | Lands on | Menu? |
|---|---|---|
| Alt at startup → "EFI" disk | `\EFI\BOOT\BOOTX64.EFI` (was a UKI copy) | none — boots straight in |
| No Alt → OpenCore → Omarchy | `\EFI\limine\limine_x64.efi` via `OpenLinuxBoot.efi` | Limine menu |

**Fixed 2026-09-05:** `BOOTX64.LIMINE.EFI.unused` restored as `BOOTX64.EFI`, so
both routes now reach Limine. The UKI copy is kept as `BOOTX64.UKI-bypass.backup`
until this is confirmed on hardware. The original "no config found" was most
likely the stale-copy bug below; `/boot/EFI/BOOT/limine.conf` now exists and is
in sync beside the binary.

Note the hook guard: `objcopy --only-section=X` exits 0 even when section X is
absent, so testing its exit status classifies *every* PE binary as a UKI — the
first version of the sync hook cheerfully overwrote Limine with a kernel image.
Extract and check for actual bytes instead.

### Fixed: shadowing limine.conf copies (root cause of the invisible snapshot)

There is exactly **one** limine.conf: `/boot/limine.conf`. An earlier belief in
this repo — that the ESP "carries three copies that must be kept in sync" — was
wrong, and was itself the bug.

Limine >= 10.3.0 loads the **first** config in its search order, so a copy at
`EFI/limine/` or `EFI/BOOT/` silently overrides the canonical one that
`limine-mkinitcpio` and `limine-snapper-sync` maintain. `limine-install` detects
these and says to delete them (see `check_limine_config_conflicts()`).

This project's own scripts created them — `imac-patcher`, the 5K installer and
`imac-test-entry` each copied `/boot/limine.conf` into both locations. The cost
showed up on 2026-09-05: a snapshot created at 18:58 appeared in `snapper list`
and in `/boot/limine.conf`, but the boot menu was reading a shadow copy from the
previous day and never showed it.

**Fixed:** the copies are removed (archived under
`/boot/limine-conf-shadow-backup/`), all three scripts now delete shadows
instead of creating them, and `scripts/95-limine-esp-hygiene` in
`/etc/boot/hooks/post.d/` removes any that reappear. Verified by recreating a
shadow and watching the hook delete it.

### A trap worth remembering

`objcopy -O binary --only-section=X file out` **exits 0 even when section X does
not exist** — it simply writes nothing. Testing its exit status to decide "is
this a UKI?" classifies every PE binary as one. The first version of the hygiene
hook did exactly that and overwrote the freshly restored Limine binary with a
74 MB kernel image on its next run. Extract and test for actual bytes instead.

The same mistake was latent in `imac-patcher`'s `verify_cmdline()`, which read
the embedded cmdline from the EFI fallback; once that path is stock Limine there
is no `.cmdline` there at all. It now reads the UKI directly.

## What a clean install actually needs

None of the boot repairs above. A fresh Omarchy install puts Limine at both
`\EFI\limine\limine_x64.efi` and `\EFI\BOOT\BOOTX64.EFI` (Omarchy sets
`ENABLE_LIMINE_FALLBACK=yes`) with a single `/boot/limine.conf`, so the menu
appears whichever route the firmware takes — with or without macOS or OpenCore
in the picture.

Both faults on this machine were self-inflicted: the UKI-over-fallback bypass
added by hand on 2026-08-30, and the shadow configs added by this repo's own
scripts. That is why the `boot` module *detects and repairs* rather than
assuming: on a healthy machine it reports `applied` and changes nothing.

## Fixed: sheared desktop seam (slave tile loses genlock)

**Seen again 2026-09-07 00:01, default build** (boot 1a2565…-successor, kernel
7.1.9-arch1-2, full stack + all five increments): desktop sheared after login
while the driver reports both tile streams `sync_enabled=1` from the 22.3 s
commit onward and the 250 ms settle re-sync agreed; no later modeset, no
re-detect loop (7 detects, 0 re-trainings). So the driver's bookkeeping and
the panel disagree — the same shape as before the settle-resync. The two
lean-pair boots just before it (23:59, 00:00, same logic minus logging and
DPCD read-backs, plus the 9-byte tile-group fix) were clean; one sample each,
not evidence of a difference yet. Worth running the lean entry for several
boots to see whether the shear ever shows there. Workaround unchanged:
`hyprctl reload` forces a modeset.


The artifact that actually bites in daily use, distinct from the boot-time ones.
The mode is a correct 5120x2880 throughout; what is lost is sync — the slave
stream's `sync_enabled` flips to 0 on some modeset and the two tiles scan out
of phase, which reads as a skewed/sheared seam. Calibrated against the owner's
eyes on 2026-09-05: `sync_enabled=0` in the `commit-after-dc` log line is the
skew.

**What was believed and is wrong:** that 8-bpc loses sync and 10-bpc keeps it.
On a fresh boot with `bitdepth = 10` pinned from the start the slave still came
up at `sync_enabled=0`, and a forced modeset re-locked it at 8-bit just as well.
The earlier "fix" worked because `hyprctl reload` forced a fresh modeset, not
because of the depth. Genlock is a coin-flip per modeset. `bitdepth = 10` stays
in `configs/monitors.lua` because this is a 10-bit panel, not as a fix.

**Workaround for now:** any modeset re-rolls the dice — toggle `bitdepth` in
`~/.config/hypr/monitors.lua` and `hyprctl reload`, check with
`journalctl -k -b 0 | grep commit-after-dc | tail -2`, repeat until both
streams say `sync_enabled=1`. Usually lands within two tries.

**Checked 2026-09-06, not the cause:** master selection. `set_master_stream()`
only considers streams that already have `triggered_crtc_reset.enabled`, and
on a fresh context none do, so the master is always index 0 — here the DP
slave tile (`master_link[1]` in every boot, good or bad). The root then resets
to the slave's VSYNC. That is identical between locked and unlocked boots, so
it does not explain the coin-flip; the `sync_enabled=0` on stream[0] in a bad
boot is that same master (event_source == itself) and is expected. What
differs between boots must be downstream: whether the GSL trigger-reset in
`dce110_enable_per_frame_crtc_position_reset()` actually took, or the panel's
own response to the phase. Making the eDP root the master instead is a cheap
experiment, not a diagnosis.

**Root cause found (2026-09-06)** — and it is exactly the design flaw, not
the panel. `set_master_stream()` only considers streams whose per-frame reset
is *already* enabled and falls back to stream[0]; the stitch adds the slave's
peer stream first, so on a clean commit the slave is picked as its own master
and never gets the reset. The DCE sync group is built from streams that carry
the reset, so the slave tile is left out. Seven modesets in one boot: every
commit with BOTH tiles flagged locked, every one with only the root flagged
sheared; the outcome depended on a stale flag surviving from the previous
commit. **Second finding, 2026-09-06 evening:** with both tiles flagged, login on the
promoted build *still* sheared, and the 10-bit switch (a later modeset) cured
it. `dc_commit_state_no_check()` runs `dc_trigger_sync()` right after
`apply_ctx_to_hw()`; on a full modeset the slave tile is re-woken and
re-trained inside that same commit, so the one-shot alignment
(`enable_timing_synchronization`) fires before both timing generators are
running. Note also that `enable_timing_multisync()` excludes the master, so
with two streams it programs no per-frame reset at all -- the visible lock
comes entirely from the one-shot alignment. Fix in the test entry (`patches/5k-genlock-settle-resync.patch`): a delayed
re-sync 250 ms after every tiled commit via `amdgpu_dm_trigger_timing_sync()`
(the debugfs knob's routine); it logs `manual-trigger-sync`.

**Fix, shipped 2026-09-06:** `patches/5k-genlock-deterministic.patch` flags both
tile streams before the master pick. Proven on hardware: six modesets in one
boot of the fixed build, every one locked at the first stage including the boot
commit. Promoted to the default; `bitdepth` back to 10 on 2026-09-06 — that modeset
locked first time on the promoted build (`XRGB2101010`, both streams
`sync_enabled=1`), and every commit of its first boot locked (6/6).

**Earlier note, kept for the record:** `dm_enable_per_frame_crtc_master_sync()` (see
`patches/genlock-fix.patch`) is where `triggered_crtc_reset.enabled` is set for
the slave; something about which stream `set_master_stream()` picks, or the
order the two tile streams land in the context, differs between the modesets
that lock and the ones that don't. The log's `master_link[N]` field is the lead.

## Considered and rejected

**Fan curve daemon.** Measured 85 °C with the fan at its 1200 RPM minimum and
concluded the SMC never ramps. That was wrong: later sampling under sustained
load showed it holding ~1500–1700 RPM, well above minimum. It does respond — it
just doesn't track temperature closely, and 85–96 °C is uncomfortable but not
dangerous on a chip that throttles at 100 °C. The daemon also caused audible
noise during ordinary work. Removed; the SMC has fan control.

If revisiting: establish the problem first — watch `sensors` and
`/sys/devices/platform/applesmc.768/fan1_input` under sustained load for several
minutes and confirm the fan genuinely stays pinned while temperatures climb.
