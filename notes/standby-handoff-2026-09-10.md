# Sleep / desktop standby handoff — 2026-09-10

The user asked for some way to make sleep work, accepting a substitute or
disabled CPU C-states, while keeping hibernation disabled. They then directed
attention to the project. The optional question about accepting apps/networking
remaining active received no answer; work proceeded with an explicitly stated
assumption that an additive desktop standby command would be useful.

## Starting state and findings

- Checkout: `main`, HEAD `e64a526`, initially clean. The older audio/GRUB
  handoffs' uncommitted-change lists no longer describe the current checkout.
- Host: Omarchy, iMac18,3, `7.2.3-arch1-3`, Limine. All four kernel sleep
  targets were masked and remain masked. No `idle=poll` in `/proc/cmdline`.
- Commit `901d66f` recorded deep/s2idle hangs and failed display-override and
  `amdgpu.runpm=0` experiments. `456df26` claimed `idle=poll` success, but
  `3f07ab5` explicitly corrected it: brcmfmac had rejected the apparent
  successes, and completed entry attempts still hung.
- The README's definitive firmware diagnosis was unsupported. In particular,
  s2idle does not enter S3 firmware sleep. The failing stage/device remains
  unresolved; do not assert that no true suspend fix can exist.

## Added implementation

`scripts/imac-patcher standby [--check] [--no-power-profile]` dispatches to
`scripts/imac-standby`, a Python standard-library helper. It checks persistent
masks on suspend/hibernate/hybrid/suspend-then-hibernate, confirms a secure
desktop lock, requests DPMS off, checks reported off state, and waits for
unlock. It requests DPMS on when exiting or handling a failure/cancellation.

Omarchy uses its shell lock status plus Hyprland DPMS; KDE Plasma Wayland
uses KScreenLocker's confirmed locked state plus KScreen DPMS. Unsupported
sessions fail before a lock/power change. Hyprland input wake must be enabled.

By default `powerprofilesctl launch` holds `power-saver` around the worker,
then releases it. `--no-power-profile` is display-only. No process freezing,
CPU C-state changes, boot edits, systemd sleep-service overrides, menu
replacement, or true kernel suspend. Apps and networking continue running.
The existing suspend module and its mask/unmask semantics are retained.
Do not run `--remove suspend`: that would unmask hibernation too.

Docs: `docs/standby.md`, README, dependencies and platform guides. Module
descriptions now point to standby without claiming a confirmed firmware cause.

## Validation and current limits

- Final `./scripts/check.sh`: **240 passed, no skips**, including release
  contents and isolated launcher dispatch. `git diff HEAD --check` clean.
- New tests use fake desktop IPC and cover refusal, confirmed locking,
  profile failure/release, DPMS failure, duplicates and cancellation cleanup.
- Real `./scripts/imac-patcher standby --check`: passes.
- Real profile hold switched the CPU preference from `performance` to
  `power`. First release returned to `balanced`; explicitly restored
  `performance` with `powerprofilesctl set performance`. A subsequent hold
  returned to `performance`. This daemon behavior is documented: release
  returns to its last selected profile, not necessarily its prior active
  profile. The final machine profile is `performance`, with no remaining holds.
- **No real lock or DPMS off/on cycle was attempted.** That is the remaining
  hardware check, along with power consumption. Never describe it as a
  hardware-verified sleep fix. The kernel sleep masks are unchanged; no
  hibernation, suspend, reboot, GRUB/mkinitcpio, or driver changes were run.

No commits or pushes. New runtime/doc/test files are staged for the existing
release test snapshot mechanism; tracked edits remain unstaged. Tests produced
their usual ignored `dist/` artifacts. The changes all belong to this task.
