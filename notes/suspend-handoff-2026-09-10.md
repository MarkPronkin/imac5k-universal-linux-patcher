# Handoff: suspend root-caused to Thunderbolt NHI; sleep hook shipped, s2idle validated. 2026-09-10

## Owner's request and where it ended

Owner: "suspend doesn't work". By end of session the hang is root-caused to
the **Thunderbolt NHI noirq suspend** (Alpine Ridge, `0000:07:00.0`, device
`0x15d2`), a sleep hook that unbinds/rebinds it around sleep is written,
wired into the patcher and installed, and a real s2idle suspend through
systemd resumes cleanly. Owner also said: hibernate is NOT wanted — do not
pursue it; its targets stay masked.

**Stopped at (evening):** suspend works in s2idle, and the patcher's suspend
module owns both the hook and the s2idle default (see "Validation" below).
The "Changes made", "Machine state" and "Next steps" sections record the
~17:15 state, before the hook was installed.

## Findings chain (each step evidenced; kernel 7.2.3-arch1-3, linkarm module)

1. Real `systemctl suspend` hung: kernel log ends at `PM: suspend entry
   (deep)`, no exit, power-cycled. suspend_stats 0/0.
2. pm_test ladder (`notes/imac-pm-stage.py <stage> [--mode deep|s2idle]`,
   requires root + all four sleep targets masked, restores state after):
   `freezer` PASS, `devices` PASS, **`platform` HANG** (deep) — reproduced
   (run dirs `/var/tmp/imac-pm-platform-whe4mksi` = hang,
   `/var/tmp/imac-pm-platform-msnj2ef1` = pass with TB unbound).
3. **pm_trace is useless on this Mac:** Apple's POST wipes the RTC on a hard
   power cycle. Proof: decoded `Magic number: 8:1:0` has user=8, impossible
   from any `generate_pm_trace` call site (all pass user=0); the RTC read
   back `2024-01-01 00:00:16` (a POST-reset clock ~16 s old at init). The
   `memory48: hash matches` line was a coincidence — sdbm("memory48")%1009==0
   matching the wiped zero field. Do not retry pm_trace across power cuts.
4. `platform --mode s2idle` also HANG → ACPI exonerated: verified in the
   7.2.3 source (`kernel/power/suspend.c`) that for PM_SUSPEND_TO_IDLE every
   `platform_suspend_*` hook routes to the s2idle ops and `suspend_ops`
   (with `_PTS`/`_GTS`) is never called. Hang is in `dpm_suspend_late()` or
   `dpm_suspend_noirq()`.
5. Driver survey: of this machine's drivers only **thunderbolt**
   (`nhi_suspend_noirq` → `tb_domain_suspend_noirq`) and **amdgpu**
   (`amdgpu_pmops_suspend_noirq`, gated by `amdgpu_acpi_should_gpu_reset`)
   carry noirq callbacks. Unbind bisect: **TB unbound → platform s2idle
   PASS; rebound → HANG. Both directions reproduced.** Culprit confirmed.
6. With TB unbound: `processors` PASS (`/var/tmp/imac-pm-processors-z4c03oym`).
   **`core` HANG once, then PASS on a fresh boot**
   (`/var/tmp/imac-pm-core-xusmaa06`) — flaky, unresolved; the delta over
   processors is only `arch_suspend_disable_irqs()` + `syscore_suspend()`.
7. **Real deep suspend with TB unbound: S3 ENTERS, WAKE RESETS THE MACHINE.**
   Slept for real (screen/fans off); keypress → spontaneous reboot. No
   pstore capture despite efi-pstore being registered (see machine state) —
   so probably not a kernel panic: S3 wake is firmware territory on this box.
   This revives the old "Apple firmware S3" suspicion, now with direct
   evidence. Journal tail was lost in the hard reset.

## Changes made (uncommitted, in the working tree)

- `scripts/imac-tb-sleep-hook` (NEW) — system-sleep hook: `pre` unbinds all
  bound Thunderbolt PCI functions (records them in `/run`), `post` rebinds.
  Paths overridable via `IMAC_TB_DRV_DIR`/`IMAC_TB_STATE_FILE` for tests.
- `scripts/imac-patcher` — suspend module: `TB_SLEEP_HOOK` constant, apply
  installs the hook, detect requires it for "applied", remove deletes it;
  desc rewritten (two hard-hangs, s2idle expectation, experimental status).
- `scripts/lib/fedora.sh` — same treatment for the Fedora suspend override.
- `tests/test_tb_sleep_hook.py` (NEW, 6 tests); harness updates in
  `tests/test_suspend.py` and `tests/test_arch_grub.py` (TB_SLEEP_HOOK /
  SCRIPT_DIR stubs, "applied" tests pre-install the hook).
- `TODO.md` — 2026-09-10 resume checkpoint extended with the whole chain.
- Full suite: **248/248 OK** (`python3 -m unittest discover -s tests`).

Not committed, per the running-session convention (TODO.md / AGENTS.md /
notes/ stay uncommitted; the code changes are also still uncommitted — the
owner may want them in a release after validation).

## Validation (evening — supersedes the "not yet" state below)

1. Hook installed (`install -m755` 17:10, in sync with the repo copy).
2. `echo s2idle > /sys/power/mem_sleep`, suspend.target unmasked,
   `systemctl suspend` → entry 17:13:35, exit 17:13:54, hook unbound and
   rebound `0000:07:00.0`. PASS. Only cost: ~6 s SATA link recovery
   (`ata1: link is slow to respond` → up at 6 Gbps), known from staging.
3. Made permanent: `mem_sleep_default=s2idle` in `/etc/default/limine` +
   `limine-mkinitcpio`; verified after reboot (`[s2idle]`, cmdline).
4. The patcher now manages the default itself (suspend module on all three
   backends), so the manual limine edit is the last of its kind.

## Machine state right now (boot since 16:43:47)

- `/etc/default/limine` gained `efi_pstore.pstore_disable=0` (via `sed
  -i.bak`; backup at `/etc/default/limine.bak`), UKI rebuilt, param live on
  the current cmdline. Harmless; keep or remove later.
- All four sleep targets **masked** (diagnosis state; suspend.target
  deliberately NOT unmasked — with `deep` as default an idle suspend would
  enter S3 and reset on wake).
- Thunderbolt **bound** again (fresh boot rebinds it).
- `mem_sleep`: `s2idle [deep]` — deep is still the default.
- Runtime sysctls from the trap attempt (hardlockup_panic=1, panic=5) were
  one-boot only and are gone.
- Hook NOT installed: `/usr/lib/systemd/system-sleep/` has only
  `keyboard-backlight` and `unmount-fuse`.

## Next steps (in order)

1. Install the hook: `sudo install -m755 scripts/imac-tb-sleep-hook
   /usr/lib/systemd/system-sleep/`
2. Validate s2idle through systemd (exercises the hook end-to-end):
   `echo s2idle | sudo tee /sys/power/mem_sleep`,
   `sudo systemctl unmask suspend.target`, `systemctl suspend`, wake by
   keypress after ~15 s. Afterward: `journalctl -b | grep imac-tb-sleep-hook`
   should show unbind/rebind lines. NOTE: a raw `echo mem >
   /sys/power/state` bypasses system-sleep hooks — manual tests still need a
   manual unbind.
3. If it wakes cleanly: make it permanent — add `mem_sleep_default=s2idle`
   to `KERNEL_CMDLINE[default]` in `/etc/default/limine`, `sudo
   limine-mkinitcpio`, reboot, verify `cat /sys/power/mem_sleep` shows
   `[s2idle]`. Then `imac-patcher --apply suspend` can be run for the record
   (it also unmasks suspend.target). The first real resume also exercises
   the 9.9.11-test audio chain-restart fix — check sound after wake.
4. If s2idle hangs: power-cycle; that's new information (every s2idle kernel
   phase passed). Suspects then: the flaky `core`/`syscore_suspend` path.
5. Open research threads (not blocking a working suspend): root-cause the
   NHI noirq hang upstream (Alpine Ridge suspend); the S3 wake reset
   (firmware); the one-off `core` hang.
