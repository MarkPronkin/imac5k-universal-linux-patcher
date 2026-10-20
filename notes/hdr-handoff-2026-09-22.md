# HDR / EDR handoff — 2026-09-22

Updated at approximately **04:10 CEST**. The owner asked: **“can you build it
for me so i can test it”**. That is done. The first physical run (03:31)
trapped the owner in stacked fullscreen patterns and ended with a power-off.
After the escape fixes, the **second run (03:49–03:53) passed**: the owner
reported “everything happens as you described, no issues noticed”. Its exit
exposed a **stock aquamarine 0.15.0 crash on every Hyprland exit** on this iMac
(see “Second physical run”). The desktop is still stock Hyprland. The work is
committed on `test` and pushed (2026-10-06); the `hdr` branch was merged into
`test` and deleted.

## Request and branch

The owner first asked whether the 5K panel could support HDR and whether a
colorimeter was required, then requested a separate HDR branch based on `test`
and implementation work.

- Repository: `/home/markpronkin/imac5k-universal-linux-patcher`.
- Branch `hdr` (merged into `test` and deleted on 2026-10-06), based on `test` at `52dd6e8cc23168086d030c4dbc1c19aeebd6f1d5`.
- Prototype commit: `5dfe72b` — `hdr: prototype gamma-output EDR in Hyprland`.
- On 2026-10-06 the HDR work was pushed to `origin/test`; nothing is released and `main` is unchanged.
- Design, commands and limits: [the experiment guide](../experiments/hdr/README.md).

**Committed on `hdr`, since moved to `test`** (the owner asked for the commit):
`experiments/hdr/session.py` and `verify-session.py` (new), the
`verify-nested.py` socket-path fix, `pattern.c` closing on a key, README
updates, this note and its `AGENTS.md` pointer. Still uncommitted and
**unrelated**, not the agent's to commit: the external-display checkpoint in `AGENTS.md` plus untracked
`notes/atomdis.py`, `notes/dce112-display-state.sh` and
`notes/external-display-dp-2026-09-22.md`. Preserve them.

## The build

| Item | Path / state |
|---|---|
| Build root | `~/.cache/imac5k-edr/5dfe72b` (`source.json` records commit and patch) |
| Executable | `~/.cache/imac5k-edr/5dfe72b/build/Hyprland` |
| Log | `~/.cache/imac5k-edr/build-5dfe72b.log`: ends `Built: …`, finished 02:44 |
| Download cache | `~/.cache/imac5k-edr/downloads` (checksum-verified archives) |

Upstream Hyprland **0.56.2**, commit `efb50993780079460b0cbed1363e2166a2de1d9f`;
patch SHA-256 `e4840368e391a9b448f89c6c35ad142b45b6e1c198022e09b0936b86eaed040b`
(matches `5dfe72b`). `--version` reports branch `imac-edr`, tag
`v0.56.2-imac-edr` and the full commit; library ABI matches the installed
Aquamarine 0.15.0, Hyprutils 0.14.2, Hyprgraphics 0.5.1, Hyprcursor 0.1.13 and
Hyprlang 0.6.8. It links both Lua 5.5 and libinput's Lua 5.4, exactly like
`/usr/bin/Hyprland`. It was built with a CMake extracted into
`/tmp/imac-hdr-build-tools` (not on PATH); the build no longer needs it.

`cm = "edr"` describes P3 / gamma 2.2 output with an estimated 500-nit peak and
200-nit reference white, rendering PQ/scRGB into that output with 2.5×
headroom. It does not make the panel accept PQ, send HDR metadata, or claim
DisplayHDR. The estimates assume full backlight; a colorimeter is needed for
calibration only. EDR attaches `NO_HDR_METADATA` only to clear an earlier PQ
state (`inHDR()`, EOTF 2), so a fresh EDR session commits no metadata blob.

## Validation

Earlier, on the `/tmp` scratch build of the same patch: full build, 15 shader
assertions plus a 101-point tone-map sweep, the nested SDR/PQ/1,000-nit/blur
test and `--verify-config` of `edr.lua`.

This session, on the persistent build:

- `verify-nested.py` **passed** (reference white 229/255 in captures, PQ bars
  243/251/255 above it, SDR clipped at 229, blur preserved uniform patches).
  It first failed: `Socket2 path is too long … IPC will not work`. The full
  commit hash makes the instance signature up to 62 bytes (the scratch build's
  was `unknown_…`), and the harness's runtime directory under the work
  directory made the socket path 119 bytes, over the 107-byte limit. **Fixed in
  the harness** with a short `/tmp/edr-*` runtime directory, symlinked from the
  work directory. The real session's `/run/user/1000` path is 96 bytes, as
  with stock Hyprland.
- The staged session config passes `--verify-config`, and was driven in a
  nested compositor with **real key events** (`wtype`): all ten bindings
  registered; the guide opened and recorded `monitors.json`; Super+4 floated
  PQ over the top half and SDR over the bottom; Super+1 went fullscreen;
  Super+W, Super+Return, Super+D (off, then on after three seconds) and
  Ctrl+Alt+Backspace (exit 0) worked. That scratch harness was lost with `/tmp`
  and is now `experiments/hdr/verify-session.py`: `verify-nested.py`'s
  isolation plus `wtype -M logo -k 4 -m logo` style presses and
  `hyprctl -j clients` checks. It needs
  `hyprctl eval 'hl.config({ input = { resolve_binds_by_sym = true } })'` in the
  nested instance, because `wtype` uploads its own keymap; physical keyboards
  use the configured layout.
- The `run` supervisor was exercised with a stand-in compiled compositor:
  normal exit, the time limit (SIGTERM), `--stop` from another process, SIGTERM
  ignored (SIGKILL after 15 s) and a crash report. The pidfile was removed and
  the `systemd-inhibit` sleep lock was held during, released after, every run.
- `describe()` was checked against live `hyprctl` output: on the stock desktop
  it flags EDR, 10-bit, hardware cursor and direct scanout as missing.
- All **543 repository tests** pass (`./scripts/check.sh`).

## Physical test session

`python3 experiments/hdr/session.py stage ~/.cache/imac5k-edr/5dfe72b` wrote
`~/.cache/imac5k-edr/5dfe72b/session/` (config, `edr.lua`, prebuilt pattern,
a copy of `session.py`) and the `~/.cache/imac5k-edr/5dfe72b/start` wrapper.
Restaging is idempotent; it refuses a build from another patch. For the owner,
**`~/edr-test`** is a symlink to that wrapper. They reported “no such file or
directory” for the long path, twice, then ran it; the cause was not
established.

Owner's steps (the wrapper prints the keys and waits for Enter first):

1. Ctrl+Alt+F3 (MX Keys: add Fn if F3 is a media key); log in. Do not leave
   `claude` running there: the launcher needs the console's shell.
2. Run `~/edr-test` (`--minutes N`, default 20, max 120) and press Enter.
3. Super+1..4 show patterns, one at a time; **Esc closes a pattern**; the guide
   terminal lists all keys and the recorded state.
4. **Super+Escape** or Ctrl+Alt+Backspace ends it; the console prints a summary.
5. `exit`, then Ctrl+Alt+F1. The desktop will probably be locked.

## First physical run (03:31–03:33, ended by power-off)

Run directory `~/.cache/imac5k-edr/5dfe72b/session/runs/20260922-033104/`
(`hyprland.log`, `monitors.json`; `kernel.log` added afterwards from the
previous boot's journal). `monitors.json`: eDP-1 5120×2880 at 59.98 Hz, scale
2, **`XRGB2101010`**, `edr`, `sdrMaxLuminance` 200, no hardware cursor,
direct scanout blocked by `CM`; DP-1 disabled. Kernel at 03:31:04: stitched
mode kept, DP-1 marked non-desktop; at 03:31:09 `APPLE5K: link-health PASS:
both tiles healthy after 0 recovery attempts` (both links `77 77 01 01`). No
amdgpu errors, no `HDR SB`. The owner said the pattern “seemed to work”; no
detail on highlights, ramp or halves yet.

The log shows **only** Super+1/2/3/4 bindings firing, repeatedly (each opened
another fullscreen pattern on top), plus mouse clicks. There were no Super+W,
Ctrl+Alt+Backspace or VT-switch events, so the compositor was responsive. The
exit keys were listed only in the guide the patterns covered, and patterns
ignored Esc and clicks. The owner powered off: the previous boot's journal ends
at 03:32:59 with no shutdown sequence, and the new boot began at 03:34:25.
`/tmp` was cleared, taking this session's scratch harnesses and the
`/tmp/imac-hdr-*` tools with it (the build does not need them).

Fixes, all tested: `pattern.c` closes on any key but a modifier (evdev
modifier codes are ignored, so Super+W still reaches the compositor without
closing the pattern first). The pattern bindings close open patterns before
opening a new one. Super+Escape exits, as Ctrl+Alt+Backspace does. The guide
starts with the way out. The launcher prints the keys and waits for Enter; a
cancel leaves no run directory. New `experiments/hdr/verify-session.py` (17
checks with `wtype`, both exit keys) passes; `verify-nested.py` still passes
with identical values. Pointer clicks deliberately do **not** close patterns,
so the pattern never takes the pointer and the cursor behaves as in the first
run.

`start --stop` ends it from any terminal, including this agent's. The session
refuses to run inside a desktop, over SSH or as root. It runs the patched binary
directly: the `start-hyprland` watchdog would restart a crash in `--safe-mode`
with another configuration. It sets `HYPRLAND_NO_SD_VARS=1` and
`HYPRLAND_NO_SD_NOTIFY=1`, pins `AQ_DRM_DEVICES=/dev/dri/amd-card` when present,
and holds a `systemd-inhibit --what=sleep` block lock. The config mirrors the
desktop's monitor rules: a catch-all plus `edr.lua`. DP-1, the second tile's
connector, stays disabled under the catch-all on the desktop; **`TODO.md` says
never disable it from the compositor**, and the session does not.

## Second physical run (03:49:39–03:53:03): passed

`runs/20260922-034939/`: clean launcher exit (summary ran, pidfile removed).
`monitors.json` identical to the first run and without warnings. Bindings:
Super+1 ×7, Super+2 ×2, Super+3 ×4, Super+4 ×1, Super+Escape ×1; 16 pattern
windows closed. Kernel: stitched mode, one CRTC for both tiles, `link-health
PASS … 0 recovery attempts` at 03:49:44, and again at 03:53:20 when the desktop
took the display back (desktop: eDP-1 `dp3`/`XRGB8888`, DP-1 disabled). Log
noise only: two `Cannot commit when a page-flip is awaiting` during the first
frames, `wl_surface destroyed before its xdg_surface role object` for each
pattern exit, `Cannot enter surface … hasn't bound the output` (the pattern
binds no `wl_output`), and Hyprcursor falling back to Xcursor (no theme set).

**Exit crash, stock aquamarine.** PID 7687 segfaulted after `Hyprland has
reached the end.`. Core dump present (`coredumpctl info 7687`). Stack:
`__cxa_finalize` → a libaquamarine static `SP<CBackend>` destructor →
`~CBackend` → `~CDRMBackend` → `SDRMConnector::disconnect` →
`cancelAsyncOutput` → `flushAsyncCommitEvents` (+177, a compiler null trap
`mov 0x0,%rax; ud2` on `connectors[0].impl_ == nullptr`). Source (v0.15.0 and
upstream `main`, identical): `~CDRMBackend` does `conn->disconnect();
conn.reset();` per connector, and `flushAsyncCommitEvents()` iterates all of
`connectors` without a null check. Every `CDRMOutput` gets a nonzero
`asyncOwnerID` at construction, so any later connector that owns an output
trips it; here that is the stitch's phantom DP-1. The global
`Hyprutils::Memory::CSharedPointer<CBackend> backendInUse` (`Session.cpp:27`,
set in `CSession::attempt`, never cleared) keeps the backend alive past
Hyprland's `m_aqBackend.reset()`, so the destructor runs in `exit()`.
**The stock desktop does the same at every clean shutdown**: one
`Hyprland[…]: segfault at 0 … libaquamarine.so.0.15.0[bbfe1]` per boot since
2026-09-21 00:24 (boots −5…−2; −1 ended by the power-off), each followed by
`start-hyprland: Couldn't waitpid for hyprland: No child processes`. None on
the Sep 16 boots, although aquamarine 0.15.0-2 was installed then. No data
loss; the shutdown completes. Upstream already has it as
hyprwm/aquamarine#383 (open, no maintainer reply); the null-check fix in
PR #413 was auto-closed because the hypr* projects only take PRs from vouched
contributors. **On hold at the owner's request** (“in practice it's harmless
it's not a priority”): recorded as a known rough edge in the main README and
in `TODO.md` with the analysis, the one-line fix and the prepared (unbuilt)
source, patch and CMake venv under `~/.cache/imac5k-edr/`. Nothing was built,
installed or posted. (`journalctl -k` only covers the current boot; use
`-b N -k` to search older boots.)

## HDR video (mpv), after the second run

New `experiments/hdr/video.py` writes a six-second HDR10 clip: HEVC Main 10,
PQ, BT.2020, mastering metadata L(1000), MaxCLL 1000, MaxFALL 400. It carries
`pattern.c`'s seven bars (0…507.5 nits), a 0–1,000-nit ramp and a moving
1,000-nit square. Frames are written as exact 10-bit PQ codes; raw frames carry
no colour tags, so `setparams` stamps them (without it ffprobe showed
transfer/primaries `unknown`). mpv 0.41 / libplacebo 7.360 speaks
`wp_color_manager_v1` natively. It reads EDR's preferred description (gamma
2.2, P3, target max 500 = max_cll = max_fall; its log shows no reference
luminance) and in target mode switches its own swapchain to PQ, tone-mapping
to 500 nits. Captures in the nested compositor (desktop white = 229):

- Source mode (`--target-colorspace-hint=yes --target-colorspace-hint-mode=source`):
  0, 136, 186, 228, 243, 248, 251, i.e. the pattern client's values; the top
  bars are lower because the clip's 1,000-nit peak widens the tone curve.
- mpv defaults = target mode (GL and Vulkan alike): 0, 110, 152, 204, 225,
  235, 241. Peak detection off: 209 for white. `bt.2390` + detection off: 229.
  `clip`: 229. So the darkening is libplacebo's default `spline` curve, not
  EDR. The owner has no mpv config, so plain `mpv file` gets the darker look.

The staged session now generates `session/hdr-test.mkv` (stage requires `mpv`
and `ffmpeg`) and binds **Super+5** to `mpv --no-config --fs --loop-file=inf
--osd-level=0` in source mode. Patterns and the video replace one another; `q`
closes mpv. `verify-nested.py` now also checks mpv in source mode against the
PQ pattern (bars 1–4 within 3, highlights rising), and `verify-session.py`
checks Super+5 (12 bindings). Both pass. **Physical video test pending.**

## Video on the panel (run 20260922-043200) and frame timing

The owner played Super+5 (the first, 30 fps clip): “cube looks allright and
seems to be the brightest thing on the screen, nothing happenes when he
crosses the middle of the screen” (so no tile-seam artefact), but “appears to
be jittery and to not move very smoothly”. Nothing in the logs measured frame
pacing (mpv's output is not captured; Hyprland logs no missed frames). That
clip was 30 fps with a cosine-eased sweep, up to ~42 video / 84 physical px
per frame. Changes: `video.py` is now 60 fps with a constant 8 px/frame (480
px/s) wrap-around motion (`TRACK` 2880 px = 360 frames = the 6 s loop, so the
loop is seamless). The Super+5 command adds `--video-sync=display-resample` and
`--script=session/mpv-stats.lua`, which appends one JSON sample a second to
`$IMAC_EDR_RUN/mpv-stats.jsonl` while playing: estimated video and display
fps, vsync jitter, and dropped, decoder-dropped, delayed and mistimed frames.
Nothing is written at shutdown, when those properties are already gone (the
first version wrote `[]` or display-only lines). `session.py run` prints the
last sample in its summary. Nested baseline: 60.00 fps video, display 59.97 Hz,
jitter 0.009, all counters 0. Both nested tests pass (verify-session checks the
stats file).

**Panel run 20260922-184430 (18:44): smooth.** The owner: “tested it now it's
smooth”. `mpv-stats.jsonl`, 96+ samples: 60.00 fps video; dropped, decoder,
delayed and mistimed all 0; display 59.869 Hz median (59.793–60.329); vsync
jitter 0.073 median, 0.106 max. So 5K FP16 composition with direct scanout
blocked sustains 60 fps video with every frame on time, and the earlier judder
was the 30 fps eased clip. The jitter metric is higher than nested, but no
frame was mistimed. That session was left running on tty3 when the owner
returned to the desktop; its time limit ends it.

## Brightness and headroom (the owner's next choice)

The owner asked whether brightness could be driven dynamically for a truer HDR
presentation: yes, and `experiments/hdr/headroom.py` prototypes it. Mechanism
confirmed in a nested compositor: `hyprctl eval` with a full `hl.monitor` rule
changes `sdr_max_luminance`/`max_luminance` live, takes effect within a frame,
logs **no modeset** and no config errors (one early sample showed a value not
applying; a rerun of 200/100/250/300/350/400/500/200 applied every one, so it
was a race in the harness). Captures are not a luminance measurement: the
screencopy conversion re-normalises to the output's own reference white.

Policy: desktop white W is the user's brightness; the backlight carries
W × headroom (capped at the panel's 500-nit estimate), and the monitor rule
carries `max_luminance` = the peak that backlight reaches and
`sdr_max_luminance` = W. Engaging headroom therefore raises the backlight and
scales the desktop down together, holding white's luminance while highlights
gain room; releasing does the reverse, for deeper blacks and less power. Ramped
over six steps of 40 ms. Open assumptions: the ACPI backlight (`acpi_video0`,
0..96) is taken as proportional to luminance, and 500 nits is Apple's figure;
`headroom.py check` alternates the two states so the owner can see whether
white holds still.

Wiring: the session binds the brightness keys and Super+Up/Down to
`headroom.py step ±25`, Super+B to `toggle` (17 bindings). `mpv-stats.lua`
engages headroom on `file-loaded` and releases it at shutdown, so the video
demonstrates the dynamic case. `headroom.py` refuses unless `eDP-1` reports
`colorManagementPreset: edr`, so a nested test or the desktop cannot move the
backlight (verified: the nested run left it at 96), and `session.py run`
restores the backlight level it found at start.

**Tried on the panel.** The owner on Super+B (release): “three last ones drop in
brightess significantly midle one is not as noticable (i think desktop one)
black start to look better”. So the trade works — highlights collapse onto
white without headroom, blacks improve at the lower backlight — but desktop
white dims slightly instead of holding, which means the ACPI backlight is
sub-linear: level 38/96 gives less than 40% of full brightness. (Panel gamma
would move white the other way, and rounding is ~1%.) `headroom.py match` measures it.

The first attempt drove it from a terminal and failed on the panel: “when i
press - or + image just disappears, brightness didn't change before i pressed
+”. Two faults, both in the tool. The pattern window it launched took keyboard
focus when it mapped, so the keys went to the pattern, which closes on any key
(the window “disappeared”); and the loop alternated once and then blocked on
`read`, so the screen sat in one state. It is now key-driven with no terminal:
**Super+M** forks a detached loop (`measure()`, pidfile
`~/.cache/imac5k-edr/matching.pid`) that alternates the low backlight at full
signal against the full backlight scaled to W, a second each, taking W from the
state file every turn; the brightness keys only move W while it runs; Super+M
again SIGTERMs it, and its `finally` computes
`curve = ln(W/500) / ln(level/top)`, saves it to `headroom.json`, restores the
backlight and re-applies. `session.py run` also kills a surviving measurement
before restoring the backlight, since `setsid` puts it outside the session.
18 bindings; nested test passes and leaves the backlight at 96. **The
measurement itself is still pending.**

**After any further run, inspect** `~/.cache/imac5k-edr/5dfe72b/session/runs/<timestamp>/`:
`monitors.json` (expect `colorManagementPreset: edr`, a `…2101010` format,
`sdrMaxLuminance: 200`, `hardwareCursorsInUse: false`, `CM` in
`directScanoutBlockedBy`, DP-1 disabled), `hyprland.log`, `kernel.log`
(amdgpu/DC errors, `APPLE5K`/stitch lines, `HDR SB`) and any
`crash-report.txt`. Then ask what the owner saw: bars 5–7 brighter than bar 4
in PQ only, a smooth ramp, matching halves, a normal pointer.

## EDR as the real desktop (2026-10-07)

The owner: “let's test hdr in actual envierment”, i.e. the real desktop rather
than the bare test session. New `experiments/hdr/desktop.py`:
`arm BUILD_DIRECTORY` writes `~/.cache/imac5k-edr/5dfe72b/desktop/`
(`hyprland.lua` = `dofile(~/.config/hypr/hyprland.lua)` then `edr.lua`, plus
copies of `desktop.py`, `session.py`, `edr.lua`, and a bash `launch`) and the
one-shot entry `~/.local/share/wayland-sessions/hyprland.desktop`. SDDM's
autologin session `omarchy.desktop` runs `uwsm start -g -1 -e -D Hyprland
hyprland.desktop`; uwsm resolves entries through pyxdg `load_data_paths`, user
directory first, and bakes the resolved Exec into
`/run/user/1000/systemd/user/wayland-wm@hyprland.desktop.service.d/50_custom.conf`
at each start. `launch` removes the entry first (only if it carries
`X-iMac-EDR=`), falls back to `/usr/bin/start-hyprland` if the build is
missing, takes a sleep block inhibitor, runs `start-hyprland --path
build/Hyprland -- --config desktop/hyprland.lua` with stdout to
`desktop/runs/<ts>/hyprland.log` (`enable_stdout_logs`), forwards SIGTERM, then
writes `kernel.log` and copies crash reports. On `hyprland.start` the config
runs `desktop.py record`: `monitors.json`, `state.txt` and a notification.
`desktop.py status` says what runs now and at the next login; `disarm`
removes an unused entry.

Checked: the config passes `--verify-config` with the patched binary and the
owner's full Omarchy config; Hyprland's `CMonitorRuleManager::add` erases an
earlier rule of the same name, so `edr.lua` replaces `monitors.lua`'s `dp3`
rule. uwsm's own `find_entries`/`entry_parser_by_ids`, run with a scratch
`XDG_DATA_HOME`, picks the shadow when present and the system entry otherwise.
The launcher passed five stub-compositor cases (exit status passed through and
crash report copied; SIGTERM to the whole group as the unit's
`KillMode=control-group` does, and to the launcher alone; fallback without
`--path`; a foreign entry left in place); the inhibitor was held during and
gone after each. `record` and `status` on the stock desktop flag all four
warnings. The build has the same flags as `/usr/bin/Hyprland` (XWayland,
`USES_SYSTEMD`; `NO_UWSM` only skips installing a session file). Chromium 152
contains the `wp_color_manager_v1` client (`kWaylandWpColorManagerV1`);
Firefox 155 has `gfx.color_management.hdr`. Neither is tested here yet.

**Armed for the owner's next login** at the end of this step. Logging out ends
this agent's terminal; resume with `claude --continue` from the repository in
the EDR desktop, then `python3 experiments/hdr/desktop.py status` and read the
newest `desktop/runs/` directory.

## Patcher module `hdr` (2026-10-17)

The owner, from the armed EDR desktop (run `20261016-024747`, a full day,
link-health PASS, no errors): “hdr seems to work (tested in chromium with hdr
video), prepare an hdr patcher, it should work through imac-patcher for now
just limited to imac 5k 2017”. Chromium 152 needed no flags beyond Omarchy's
`chromium-flags.conf`.

Design, all in `scripts/hypr-edr.py` (`status|note|apply|remove|check`):

- **Build:** `build.py`'s code, moved unchanged in behaviour; the experiment's
  `build.py` is now a shim with the same CLI and layout. The existing
  `~/.cache/imac5k-edr/5dfe72b` still matches (`--prepare-only` accepted its
  marker after the patch move). The module builds in
  `~/.cache/imac-patcher/hdr/<patch sha12>`, logs to `build.log`, uses
  `min(cpus, RAM/2 GiB)` jobs, and deletes the tree after installing; the
  downloads stay. All build dependencies but `cmake` come with Arch's
  `hyprland` package.
- **Install:** binary, `hyprland.lua` (wrapper), `launch`, a copy of the helper
  and `build.json` (version, patch hash, real paths of the libaquamarine and
  libhypr* libraries) in `~/.local/share/imac-patcher/hdr`, and the entry
  written last. The wrapper is verified with `--verify-config` against the
  user's real config before anything is replaced.
- **Login:** `launch` runs `timeout 20 python3 hypr-edr.py check`. If that
  fails, it schedules `notify-send` with `setsid -f`, so `start-hyprland` never
  sees it as a child, and execs stock `start-hyprland`; otherwise it runs
  `start-hyprland --path …/Hyprland -- --config …/hyprland.lua`.
- **uwsm:** `check_entry_basic` raises on a validation failure or a failed
  `TryExec` (main.py:474) and does not fall back to the system entry, so the
  entry has no `TryExec` and only valid keys. A test runs uwsm's
  `entry_parser_by_ids` on it.
- **Wrapper:** `hl` is a plain table (`LuaBindingsRegistration.cpp`), so
  `hl.monitor` is wrapped before the user config loads. The user config is
  loaded by `require("<absolute path>")`, which Hyprland's searcher hook tracks
  for auto-reload; `dofile` is not tracked. The user's config directory is put
  first on `package.path`. Without an eDP-1 rule, one is derived from the
  catch-all.
- **Status:** `partial` with reasons in the note (upgraded Hyprland, libraries,
  older release or patch, missing entry); `hdr takes effect at your next
  login` when applied but not running.

**End-to-end in scratch dirs** (`XDG_DATA_HOME`/`XDG_CACHE_HOME` under the
session scratchpad, downloads seeded from the verified cache, cmake from
`~/.cache/imac5k-edr/tools/venv`): about 8 minutes, `exit 0`, owner's config
verified, `status` → `applied`, the installed `check` → 0. The real login is
untouched.

**Next:** the owner runs `imac-patcher --apply hdr` (it offers `cmake`), logs
out and in; then check `hyprctl -j monitors` (edr, `XRGB2101010`, the owner's
scale) and `imac-patcher --status`. The module takes no sleep inhibitor, so
one s2idle cycle with EDR on is the next physical test.

## Findings worth keeping

- **`hl.dsp.dpms("off")` toggles.** The dispatcher reads `action` only from a
  table (`tableToggleAction`), so a string is ignored. The `TODO.md` recovery
  (`dpms("off")`, sleep 3, `dpms("on")`) works only as two toggles. Use
  `hl.dsp.dpms({ action = "off" })`.
- **Any key or modifier event wakes DPMS** when `misc:key_press_enables_dpms`
  is set, as Omarchy sets it (`InputManager::setupKeyboard`). A DPMS cycle
  typed and run with Enter can be woken by Enter's own release; the README
  recovery starts with `sleep 1`, and the session's Super+D switches off 500 ms
  after the key press.
- VT round trips are a known operation on this panel (`TODO.md`: they have
  both fixed and failed to fix link loss; DPMS cycle as fallback). On return,
  stock aquamarine `restoreAfterVT()` attaches an all-zero
  `HDR_OUTPUT_METADATA` blob (colour handoff, 2026-09-10; ruled out there as
  the colour cause). That applies to the desktop after any VT switch, not to
  EDR specifically.
- `hl.timer` callbacks are held by `m_luaTimers`, so an unreferenced timer
  still fires.

## Live machine

- iMac18,3; stock Hyprland 0.56.2 on the physical display, started by SDDM
  autologin → `uwsm` → `start-hyprland` on **tty1** (logind session 1). No
  getty on other VTs until switched to; logind defaults (`NAutoVTs=6`).
- `eDP-1` 5120×2880 at 59.982 Hz, scale 2, `cm = "dp3"`, `XRGB8888`,
  hardware cursor. DP-1 listed as disabled (2560×2880).
- `acpi_video0` 96/96. No backlight change was made by this work.
- Idle: Omarchy shell screensaver 150 s, lock 300 s, no idle suspend; logind
  has no `IdleAction`; sleep is s2idle. Login shell bash, no desktop autostart
  in the profile; console layout `us`.
- `foot`, `wtype`, `mpv` and `jq` are installed; alacritty/kitty/ghostty not.
- Omarchy skill read; never edit `/usr/share/omarchy`. Do not run GRUB tools.
  Release 0.2.6 stays a draft; do not push tags broadly.

## Remaining work

Physical run and its evidence; measured luminance/gamma/gamut; backlight-aware
headroom; saturated-colour validation; real HDR apps (e.g. `mpv --vo=gpu-next`
in the session), HLG, ICC and mixed monitors; screenshots; recovery after
suspend; the `hdr` module's first real login (see above).
