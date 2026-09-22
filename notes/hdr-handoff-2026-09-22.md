# HDR / EDR handoff — 2026-09-22

Updated at approximately **04:10 CEST**. The owner asked: **“can you build it
for me so i can test it”**. That is done. The first physical run (03:31)
trapped the owner in stacked fullscreen patterns and ended with a power-off.
After the escape fixes, the **second run (03:49–03:53) passed**: the owner
reported “everything happens as you described, no issues noticed”. Its exit
exposed a **stock aquamarine 0.15.0 crash on every Hyprland exit** on this iMac
(see “Second physical run”). The desktop is still stock Hyprland. The work is
committed on `hdr`, not pushed.

## Request and branch

The owner first asked whether the 5K panel could support HDR and whether a
colorimeter was required, then requested a separate HDR branch based on `test`
and implementation work.

- Repository: `/home/markpronkin/imac5k-universal-linux-patcher`.
- Branch `hdr`, based on `test` at `52dd6e8cc23168086d030c4dbc1c19aeebd6f1d5`.
- Prototype commit: `5dfe72b` — `hdr: prototype gamma-output EDR in Hyprland`.
- Nothing from HDR has been pushed or released. `test` and `main` are unchanged.
- Design, commands and limits: [the experiment guide](../experiments/hdr/README.md).

**Committed on `hdr`, not pushed** (the owner asked for the commit):
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
loss; the shutdown completes. Fix candidates (upstream, owner's call): in
`~CDRMBackend`, disconnect every connector before clearing the vector, and/or
skip null entries in `flushAsyncCommitEvents()`; make `backendInUse` weak.
Not yet reported or patched. (`journalctl -k` only covers the current boot;
use `-b N -k` to search older boots.)

**After any further run, inspect** `~/.cache/imac5k-edr/5dfe72b/session/runs/<timestamp>/`:
`monitors.json` (expect `colorManagementPreset: edr`, a `…2101010` format,
`sdrMaxLuminance: 200`, `hardwareCursorsInUse: false`, `CM` in
`directScanoutBlockedBy`, DP-1 disabled), `hyprland.log`, `kernel.log`
(amdgpu/DC errors, `APPLE5K`/stitch lines, `HDR SB`) and any
`crash-report.txt`. Then ask what the owner saw: bars 5–7 brighter than bar 4
in PQ only, a smooth ramp, matching halves, a normal pointer.

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
suspend; patcher integration (apply/detect/remove).
