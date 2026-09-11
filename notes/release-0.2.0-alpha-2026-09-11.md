# Release 0.2.0-alpha: test merged into main — 2026-09-11

User request (2026-09-10): merge `test` into `main`, review the changes, check
everything, and publish release 0.2.0 alpha from `main`.

## What was merged

- `main` was at `e64a526` (`v0.1.9-alpha`), `test` at `b4b0a61`
  (`v0.1.92-alpha`): 17 commits ahead with `main` fully contained, so `main`
  was fast-forwarded and stays linear. PR #2's head `ea6acf1` is part of it.
- Content: everything published as 0.1.91-alpha (Thunderbolt sleep hook,
  s2idle systemd drop-in, the three 5K suspend/resume patches, the tuning
  chain restart after resume, `--apply all`, Omarchy hibernation removal) and
  0.1.92-alpha (PR #2, iMac Pro native 5K, with the integration fixes in
  [the PR review](imacpro-pr2-review-2026-09-10.md)).

## Review

The whole range was read: scripts, kernel patches, tests and docs. A
multi-agent `/code-review` run stopped at the account's session rate limit
before it verified anything; the two finder reports that finished and the
candidates named in its verification prompts were salvaged and re-checked by
hand. Fixed on `main`, each with a test that fails on the unfixed code:

1. `imac-audio-jack-switch`: the new sink-removal filter `'remove' on sink`
   also matched `'remove' on sink-input #N`, so every stream that ended cost a
   0.4 s settle and three pactl calls, queued ahead of real jack events. Now
   `'remove' on sink #`.
2. `suspend_remove_hibernation`: with only the leftover `resume=` drop-in (the
   state Omarchy's own remover leaves), apply announced it would delete
   `/swap/swapfile` and ran the remover for nothing; without the remover on
   PATH it never removed the drop-in, so suspend stayed partial and in the
   boot tier. Omarchy's tool now runs only while the resume hook exists.
3. Startup audit: it listed `omarchy-hibernation-remove` as a missing tool
   when hibernation was set up and Omarchy's bin dir was not on PATH. The
   remover is a file in the `omarchy` package, so the one-shot `pacman -S`
   failed on "target not found" and installed none of the other
   prerequisites. Left out; apply already warns when it is missing.
4. `patches/README.md` said the iMac Pro follow-up applies after the suspend
   fixes "in `test`"; AGENTS.md called PR #2 a test-only integration.

## Validation

- `./scripts/check.sh`: 276 tests (273 before the fixes), no skips.
- Kernel sources matched kernel.org's `sha256sums.asc`: 7.2.3 `8ba259e8…`,
  7.1.13 `614d95fa…`. Lean stack (12 patches) with `--fuzz=0`: applies to
  both. Arch verbose (13): 7.2.3 at fuzz 0, 7.1.13 needs the installer's
  default fuzz. Fedora verbose (6, fuzz 0): 7.2.3 applies; 7.1.13 fails in the
  base verbose patch (hunks 3, 4, 32, 33). That patch is unchanged in this
  range, so both 7.1.13 verbose results are existing limits of the fallback.
- iMac18,3 / Omarchy / 7.2.3-arch1-3, read-only: the installer's build tree
  (`~/.cache/kernel-5k-build/linux-7.2.3`) carries stamps for all 12 lean
  patches at their current hashes; the installed `amdgpu.ko.zst` decompresses
  byte-identical to that build and matches the running srcversion; eDP-1
  offers 5120x2880; boot link-health PASS with 0 recoveries.
  `./scripts/imac-patcher --status` from the merged checkout: audio, eq,
  color, suspend and 5k applied, boot n/a.
- Release archive: two builds of the same commit gave the same checksum; no
  TODO.md, AGENTS.md, notes/ or tests/ inside; `install.sh` installed it from
  a `file://` mirror into a scratch HOME and `imac-patcher --version` printed
  the version.

## Suspend on this machine after the 0.1.92-alpha driver build

Both `systemctl suspend` attempts on the boot after that driver install
(2026-09-10, 19:51 and 19:52 CEST) failed to sleep. The kernel entered
`s2idle`, selected by the systemd drop-in (the cmdline carries no
`mem_sleep_default`); then `brcmfmac 0000:03:00.0` timed out entering D3
(`brcmf_pcie_pm_enter_D3 ... returns -5`), "Some devices failed to suspend",
and the kernel backed out. Each attempt shows two such s2idle entries, and
`systemd-suspend.service` failed with "Input/output error". The Thunderbolt
hook unbound and rebound 07:00.0 both times; the display came back with
link-health PASS and 0 recoveries (one "enabling link 1 failed: 15" in the
backed-out resume); nothing hung. The Wi-Fi driver, not this merge, is the
next obstacle: a sleep hook or a module unload for brcmfmac is the obvious
experiment. The clean 17:13 cycle in the suspend handoff predates the journal
that is left.

## Follow-ups not done

- **Guard suspend on the 5K driver.** An install from 0.1.9-alpha or earlier
  masked all four sleep targets. Detect now calls that partial, so
  `--apply safe`, `--apply all` and their menu entries unmask suspend, while
  an applied 5K module is skipped and never rebuilt; a pre-0.1.91 driver then
  meets its resume BUG_ON. The release notes give the order. A code guard
  (for example `dm_complete` in the installed module, or no batch migration
  out of the all-masked state) needs the owner's decision.
- python3 is not in the 5K preflight or startup audit, though the iMac Pro
  10-bpc edit runs it (Omarchy always has it through `uwsm`).
- `five_k_10bpc_config` treats `desc:` output rules as external; the depth
  step covers Hyprland only (KDE and Fedora on the iMac Pro are untested).
- Older than this range: the ESP hygiene hook falls back to `linux` when the
  running kernel's modules are gone mid-upgrade; `imac-alt-entry` treats other
  kernels' default UKIs (`omarchy_linux-lts.efi`) as orphan test entries, and
  its GRUB path does not reserve `5ktest`.
- Cleanups the review suggested: one lean-series file for both installers,
  Fedora suspend reusing the base module, one UKI-fallback helper, a single
  boot rebuild per suspend apply, and `run_all_modules` as
  `run_modules apply "${MODULES[@]}"`.
