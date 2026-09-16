# Wi-Fi (brcmfmac) suspend abort — handoff 2026-09-11

User request (2026-09-11, after the 0.2.0-alpha release): find out what can be
done about suspend aborting in brcmfmac; then "remember where you stopped
exactly". Investigation only: no code, boot, driver or power settings were
changed, and no suspend or pm_test was run.

## Integrated fix verified on hardware; leftovers removed (2026-09-16 15:52)

- Owner ran the cleanup and `--apply suspend`. Boot 854ffb1d (fix loaded by apply at
  21:13:34, same DKMS build): s2idle 21:35:05 → 21:35:23, then the **second sleep of the boot
  overnight 21:35:31 → 08:50:26 (~11 h 15 min), resumed**.
- Reboot → boot 2ff62c8d: cmdline has no `acpi_sleep=nonvs`, `memmap=` or `trace_instance=`;
  `/etc/limine-entry-tool.d` holds only imac5k-stitch, omarchy-defaults, omarchy-uki;
  `/etc/systemd/sleep.conf.d/imac5k-s2idle.conf` restored. `imac5k_xhci_d0` loaded at boot
  (15:50:05, modules-load.d), `acpi_pm_skipped=Y`, `dkms status`: `imac5k-xhci-d0/1,
  7.2.3-arch1-3, x86_64: installed`, module in `updates/dkms`. `imac-patcher --status`:
  suspend **applied**. One s2idle so far (15:51:07 → 15:51:41); owner reports sleep works.
- `notes/xhci-d0-sleep-test.py --require-boot-loaded` was not run; a second sleep in a
  boot where modules-load (not apply) loaded the module is still to be logged.
- README status cells set: iMac18,3 and Omarchy suspend ✅ verified (repeated s2idle), fixes
  table ⚠️ experimental with S3/hibernate blocked. 444 offline tests pass. Still uncommitted
  and unpushed (owner's instruction); the five new runtime files are staged.

## XHC1 fix integrated into the suspend module (2026-09-15, uncommitted, not pushed)

Owner: do the integration, the cleanup and a fresh-boot check, on this branch, nothing pushed.

- `scripts/imac-patcher` suspend module: on iMac18,3 (`imac_xhci_fix_supported` in
  `scripts/lib/platform.sh`) apply builds DKMS package `imac5k-xhci-d0/1` from
  `modules/imac5k-xhci-d0` (only the .c, Makefile and dkms.conf are staged) for every kernel
  with headers, installs `/etc/modules-load.d/imac5k-xhci-d0.conf` (`configs/imac5k-xhci-d0.conf`)
  and loads it at once, **before** `suspend.target` is unmasked. Detect needs it built for the
  kernels, the boot entry present and the live `acpi_pm_skipped=Y` with matching srcversion;
  on other models any leftover counts as partial and apply removes it. Remove unloads it,
  deletes the entry and every DKMS version. Startup audit lists dkms gcc make modinfo depmod
  modprobe (+ mokutil on Fedora) and headers on iMac18,3.
- Fedora (`scripts/lib/fedora.sh`): running kernel only, `fedora_deps` preflight, refuses to
  load under Secure Boot until `/var/lib/dkms/mok.pub` is enrolled; same apply order/remove.
- `scripts/make-release.sh` ships `modules/`; the new runtime files are `git add`ed (index
  only, for the release tests' stash). Tests: `test_suspend.py` XhciFixTests on both backends
  with fake DKMS/modinfo/modprobe/sysfs, `test_arch_grub.py` harness, `test_xhci_fix.py`,
  `test_release.py`; 357 pass, `scripts/check.sh` clean. README (fifth failure mode, status
  paragraph), DEPENDENCIES, docs/arch-grub.md, docs/fedora-kde.md, docs/development.md updated;
  the README status cells wait for the fresh-boot check.
- `notes/xhci-d0-sleep-test.py` gained `--require-boot-loaded` and `--long-seconds N`.

Next (owner): `sudo bash notes/s3-nonvs-test.sh disarm`, `sudo python3 notes/second-sleep-trace.py
disarm`, `./scripts/imac-patcher --apply suspend`, reboot, then `sudo python3
notes/xhci-d0-sleep-test.py --require-boot-loaded --cycles 4 --long-seconds 600`.

## Deep S3 still resets with the fix; pinned in notes/s3-sleep.md (2026-09-15 17:15)

`xhci-d0-sleep-test.py --mode deep` on boot 2601811c (after its seven good s2idle
sleeps, fix loaded): the first S3 attempt reset the machine. Journal ends at
`Performing sleep operation 'suspend'` 17:15:21; next kernel read the RTC at 17:16:31
(same ~70 s as the early-entry s2idle crashes). Owner asked to pin S3 for now with a
separate note: **`notes/s3-sleep.md`** (history, S3-only code paths, tools, suggested order,
machine state to undo). Current boot 854ffb1d has the S3 experiment still armed (menu
suspend = deep = reset) and no fix loaded.

## Deep S3 with the fix: test prepared (2026-09-15)

Owner chose to test deep S3 before integration, still on this branch, nothing pushed.
`notes/xhci-d0-sleep-test.py --mode deep` (requires `acpi_sleep=nonvs`, which the S3
experiment still has on the cmdline): selects deep via /run, requires an actual S3 resume in
the kernel log ("Low-level resume complete" / "Waking up from system sleep state S3"),
times sleep from "Timekeeping suspended" as well, and reports missing keyboard wake or a
Thunderbolt NHI/bridges not coming back (seen on the 2026-09-12 S3 wake) as warnings rather
than failures. Before the fix the second S3 of a boot reset at the same point as s2idle.

## Fix validated: three real sleeps in a row with USB-keyboard wake (2026-09-15)

`sudo python3 notes/xhci-d0-sleep-test.py` on boot 2601811c (`/var/tmp/imac-xhci-d0-kf_7cyl9`):
unloaded the D0-holding build, loaded the `acpi_pm_skipped` build, then three real s2idle
sleeps through `systemctl suspend` with the installed Thunderbolt and Wi-Fi hooks: 68.3 s,
104.4 s, 72.9 s asleep, all PASS, owner confirmed keyboard wake each time. Objectively:
`gpe6D` (XHC1's `_PRW` wake GPE) rose by 2 per cycle while `ff_pwr_btn` stayed at 2, no xHCI
errors, same USB devices after resume. Boot total success=7 fail=0 (it had already done one
AML D3 entry of the xHCI earlier, so without the fix its next sleep would have reset).

**Suspend on the iMac18,3 works repeatedly with this module.** Still to do before shipping:
wire it into the suspend module (DKMS + modules-load.d, base and Fedora backends, detect,
tests, README/DEPENDENCIES/docs; `scripts/imac-patcher` holds the unrelated uncommitted audit
diff on this branch), a fresh-boot run with the module loaded at boot, a longer sleep, and
removal of the investigation leftovers (`notes/s3-nonvs-test.sh disarm`,
`notes/second-sleep-trace.py disarm`, restore the parked s2idle drop-in, rebuild, reboot).
Deep S3 with the fix (second S3 used to reset too) and other Retina 5K models are untested.

## First fix lost USB wake; module reworked to native D3hot without Apple AML (2026-09-15)

Owner ran the D0-holding build: the validation script stopped after cycle 1 on its own bug
(`s2idle_seconds` needs pm_debug_messages, which it did not enable; the sleep 16:54:11 →
16:56:31 was real), then used the menu. Kernel counters: success=4 fail=0 on boot 2601811c,
i.e. both sleeps with the module (the test's and one menu sleep, 16:56:50 → 16:57:51)
returned without a reset, but **the USB keyboard no longer woke the machine; only the power
button did**. The xHCI raises PME from D3, not D0.

Reworked `modules/imac5k-xhci-d0`: instead of `PCI_DEV_FLAGS_NO_D3` it clears the ACPI
companion's `power_manageable` (in D0, runtime PM held). Verified in 7.2.3 source: the PCI
core then picks D3hot from PME support (`pci_target_state`), writes PMCSR natively, and
`acpi_pci_set_power_state` fails with -EINVAL so neither `_PS3` nor `_PS0` runs (D3HE never
set); `acpi_pci_wakeup`/`acpi_pm_set_device_wakeup` do not check `power_manageable`, so the
`_PRW` GPE 0x6D is still armed. Parameter `acpi_pm_skipped`. Validation script now unloads
the old build, enables pm_debug_messages, also times sleep from CLOCK_BOOTTIME, asks after
each cycle whether the keyboard woke it, and fails on xHCI error lines. Not yet hardware-run.

## Fix module built, hardware validation pending (2026-09-15)

`modules/imac5k-xhci-d0/` (C module + Makefile + dkms.conf, W=1 clean on 7.2.3-arch1-3):
on iMac18,3 (or `force=1` on another Apple model) it takes 00:14.0 to D0 and sets
`PCI_DEV_FLAGS_NO_D3` until unloaded, so neither system sleep nor runtime PM ever runs
`XHC1._PS3`; `active` parameter reports it. Not yet wired into imac-patcher (that file has
the unrelated uncommitted audit diff on this branch); integrate after validation.
Validation: `sudo python3 notes/xhci-d0-sleep-test.py [--cycles N]` loads the module and
runs N real s2idle sleeps through `systemctl suspend` with the installed hooks (Wi-Fi
bound, Thunderbolt present), USB-keyboard wake, checking sleep time, counters, failures and
USB devices; forces s2idle via /run because the S3 experiment (nonvs, parked drop-in) and
the trace reservation are still armed. Test: tests/test_xhci_d0_sleep_test.py (33 total).
Boot 2601811c already had one xHCI D3 entry, so its next unprotected sleep would reset.

## Cause confirmed: keeping the PCH xHCI in D0 lets the second attempt pass (2026-09-14)

`run --tb-removed --xhci-d0-from 2` on boot 2601811c: `/var/tmp/imac-crumb-yntn0you`,
`/var/tmp/imac-second-sleep-7gmdeipa`. First real s2idle PASS (69.3 s asleep, `XHC1._PS3/_PS0`
ran as usual). Second attempt, the platform test that reset the machine every time before,
**PASS** (waited 5 s, suspend exit 74534.5, success=2 fail=0, no restoration errors). Its
breadcrumb log runs the same power methods as cycle 1 (SATA PRT0 _PS3/_PS0, GIGE _PSW, RP01
_PS3/APPD/_PS0/APPU, RP05 _PS0/PCEU/_PS3) with only `XHC1._PS3/_PS0` absent. With the
earlier crumb location (reset at the first config access after `D3HE=1`), this establishes
the cause as Apple's `\_SB.PCI0.XHC1._PS3` on the second D3hot entry of the PCH xHCI.

Limits: one passing run; platform stage, not a second real sleep or a third attempt; s2idle
only; iMac18,3 only. Why the second `_PS3` differs from the first is still open. Next: a fix
that keeps 00:14.0 out of D3 across system sleep (or an SSDT override of `XHC1._PS3`), then
several real sleeps in a row with USB-keyboard wake before anything ships.

## Located: the second attempt dies inside Apple's XHC1._PS3 (2026-09-14 19:34 reset)

**Update after `collect` (`/var/tmp/imac-crumb-collect-i5h2ct85`):** raw alarm bytes 03,17,1a,
so 26 ACPI events. With first-use `_BBN` removed (confirmed by hash 23 = OSDW) the last started
access is **#26, the read of STGE (xHCI config 0x50)**, immediately after #25 wrote `D3HE=1`
(config 0xA2 bit 2) while the controller was already in D3hot from Linux's native transition.
#27 (the STGE write) never started. The D3hot→D0 bounce and the decode-enable write come
later and are not reached. `collect`/`decode` now pick that numbering automatically (30 tests).

`run --after-first --tb-removed` on boot ef639517 (`/var/tmp/imac-crumb-n7t0a_at`, selftest PASS;
`/var/tmp/imac-second-sleep-piqpvytt`, platform test started 19:34:02) reset the machine.
Next boot 2601811c read the RTC as **2005-01-05 13:01:09** = `CB_START` of a device callback
in `dpm_suspend_noirq`, device hash 610 (`0000:00:14.0`, the PCH xHCI; the only other hash
match is a USB interface, which has no noirq callback), second attempt; 69 s from that step to
the next kernel. `/proc/driver/rtc` alarm (BCD-decoded, raw read still to do via `collect`):
heartbeat 3 (1.5-2.0 s after the attempt began: no long hang), last method hash 23 = `OSDW`,
ACPI events after the step 32 (or 26 if the raw byte is 0x1A).

Mapped onto the first cycle's log with the one-time `_BBN`/`BN00` region setup removed (it
runs only on a region's first use; with it, the last method at #32 would be `BN00`, hash 211,
not 23): event 26 = read of STGE (config 0x50) right after `D3HE=1` (config 0xA2 bit 2,
D3-hot power gating enable); event 32 = write 0x02 to the xHCI command register (memory
decode on) immediately after `_PS3` bounced the controller D3hot (0x0b) → D0 (0x08) with a
30 µs Stall. Either way the fatal access is in `\_SB.PCI0.XHC1._PS3` (SSDT8, Darwin branch),
not in the project's patches. The same accesses succeed on the first attempt; why the second
differs is not established (hypothesis: D3HE lets the PMC really power-gate the controller the
second time, so the D0 bounce/decode-enable hits a gated or resetting device).

Causality test prepared: module `xhci_d0_from=N` sets `PCI_DEV_FLAGS_NO_D3` on 00:14.0 at the
start of attempt N (no native D3hot, no `_PS3`; `_PS0` is skipped on resume because the ACPI
state stays D0 and there is no `_PSC`), cleared on unload. Wrapper `--xhci-d0-from N`.
Next, on fresh boot 2601811c (0/0): first `sudo python3 notes/second-sleep-crumb.py collect`
(raw alarm bytes), then `sudo python3 notes/second-sleep-crumb.py run --tb-removed --xhci-d0-from 2`
(wake the first sleep; the second attempt is the formerly fatal platform test).

## First breadcrumb run: real sleep recorded, second attempt not reached (2026-09-14 19:40)

`run --tb-removed` (boot ef639517): selftest PASS (`/var/tmp/imac-crumb-e1posm2u`), then
`/var/tmp/imac-second-sleep-ouzwih8y`. The first s2idle **did** sleep: printk shows
`suspend-to-idle` 4818.22 → wake from IRQ 9 at 4890.07 (71.8 s), success=1/fail=0. But
there is no "Timekeeping suspended" line and CLOCK_BOOTTIME did not advance: this Mac times
s2idle with the RTC, which the module marks unusable (`pm_trace_rtc_abused`). The helper
saw 0 s, called it INCONCLUSIVE and stopped before the second attempt; wall time fell
~72 s behind. Fixed: the helper now also times s2idle from the printk lines. The module now
waits on `rtc_lock` instead of skipping (the run had 37 skips), logs read values through
a kretprobe, and takes `cycle_base`. `run --after-first` reuses this boot's recorded first
cycle. 36 diagnostic tests pass.

First complete record of Apple AML in a good cycle (`1-none-crumb.txt`, 5415 events,
0 dropped, 0 bad objects). Besides OSDW: dpm_suspend `SATA.PRT0._PS3` (HDD power GPIO);
noirq suspend `RP02.GIGE._PSW(1)` (in tg3's callback), `RP01._PS3`→`APPD` (returns early,
so no bridge/link/AirPort writes), `XHC1._PS3` (D3/clock-gating writes; **`UWAB` reads 0,
so the MPMC PMC handshake does not run**); noirq resume `XHC1._PS0`, `RP01._PS0`→`APPU`,
`RP05._PS0`→`PCEU`; early resume `_GPE._L6D`; resume `GIGE._PSW(0)`, `SATA.PRT0._PS0`;
complete `RP05._PS3`→`POFF/PCDA`; thaw: backlight restore `GFX0.LCD._BCM`→`ABCM`→
`BLC0.BSET`→`SBUS.SWRW`, i.e. **AML drives the SMBus controller**, after which i801
logs "BIOS is accessing SMBus registers" and pins 00:1f.4 runtime-active for the rest of
the boot (so a second suspend takes it D0→D3hot, the first found it runtime-suspended).
Firmware bug seen: `XHC1._PS0` reuses `Local1` in its port loop and ends by writing a
PORTSC value (0x02A0) to the PCI command register (memory decode and bus master off);
Linux's `pci_restore_state` overwrites it right away, so probably masked.

Next, same boot (module left loaded by the aborted run, RTC holding breadcrumbs):

    sudo python3 notes/second-sleep-crumb.py run --after-first --tb-removed

It unloads the stale module (RTC restored), reloads with cycle_base=1, selftests, and runs
only the platform test. After a reset: `sudo python3 notes/second-sleep-crumb.py collect`.

## EFI capture wrote nothing; RTC breadcrumb recorder prepared (2026-09-14 18:50)

Owner asked to find out for sure what differs between the first and second sleep.

- **The prepared EFI run did execute** (never collected): `/var/tmp/imac-efi-sleep-kg1962zi`
  (selftest PASS) and `/var/tmp/imac-second-sleep-qqhyv_q7`, boot 438e5fbc. First real
  s2idle 17:55:17 → 17:56:05, 45.1 s asleep, PASS. Second (platform, 5 s, `--wifi-unbound
  --serial --persistent-trace --tb-removed`) started 17:56:05.82; next kernel read the RTC
  at 17:57:26. After that reboot efivarfs holds **no** ImacSleepCapture variable, so the
  20 s non-freezable worker never wrote: every CPU was dead within 20 s of the second
  PM_SUSPEND_PREPARE, or the attempt finished and the reset followed within about a second.
- **The "~50 s" timing is withdrawn.** Platform holds of 70 s and 5 s both gave 73-80 s from
  the attempt's start to the next kernel. The hold length does not move it, so the machine
  dies before the platform-test delay (late/noirq suspend or `acpi_s2idle_prepare`), and a
  crash reset's POST is far longer than the 20 s of a normal reboot. RAM loss (the trace
  buffer's magic mismatch) fits a full cold reset. No watchdog/C-state timer is implied.
- NVRAM `HW_BOOT_DATA` keeps the last 10 boots' `GR_CAUSE` bytes (`02 04 00 00 01 00 01 00`),
  identical for normal restarts and crash resets: uninformative.
- Decompiled AML (ACPICA master, `iasl -e`) that runs in the failing phase and keeps state
  (candidates, not findings): SSDT8 `XHC1._PS3/_PS0` send PMC messages (`\MPMC` at PWRMBASE
  0xFE000020, wait on `\PMFS`, gated by `\UWAB`), save the BAR in `SBAR`, gate clocks by MMIO;
  `RP01._PS3` → `APPD` saves bridge config into `BMIS/SNBS/BNIS`, writes `BNIR=0x00FEFF00`,
  disables the link and, when `TAPD==1`, cuts AirPort power via `EC.APWC`; `GIGE._PSW`
  (run by `acpi_s2idle_prepare`) drives GPIO GPP_F13; `SATA.PRT0._PS3` cuts HDD power (GPP_F8).
- **RTC alarm bytes survive resets:** `/proc/driver/rtc` still shows the 09:09:51 UTC alarm of
  the 2026-09-12 11:09 rtcwake test through every reset since.

New recorder (not yet hardware-run): `notes/pm-crumb/imac_pm_crumb.c` (W=1 clean against
7.2.3-arch1-3; needs the ACPICA internal headers from `~/.cache/kernel-5k-build/linux-7.2.3`,
checks struct offsets against `\_SB.PCI0.XHC1`, `\PMST`, `\MPMC` or refuses to load). On
every PM callback start/end, phase begin/end, PM notifier and helper marker it writes the
RTC date/time as `v = devhash + 1021*(phase + 16*(cycle + 3*kind))` (dates 2000-2024,
minutes:seconds zeroed, so the next boot's `PM: RTC time` line gives the step and the time
until that boot). Kprobes on `acpi_ds_begin_method_execution`, `acpi_ds_terminate_control_method`
and `acpi_ev_address_space_dispatch` put the last method's hash in alarm byte 0x03 and
the count of ACPI events since the step in 0x05; a 500 ms hrtimer puts half-seconds since the
cycle began in 0x01. A debugfs log keeps every step, method and region access (field name,
address, written value). Unload writes system time back. `notes/second-sleep-crumb.py`
(run/collect/decode), `--crumb` in `second-sleep-pm-test.py`, 11 new offline tests
(33 diagnostic tests pass). The installer stick (sdb, read-only ISO mount) was unmounted
with udisksctl at 18:45 so the owner can pull it before `--tb-removed`.

Next, on this still-unslept boot ef639517 (0/0), stick physically unplugged:

    sudo python3 notes/second-sleep-crumb.py run --tb-removed

Wake the first sleep after ~30 s, leave the second alone. **After the reset, before anything
else:** `sudo python3 notes/second-sleep-crumb.py collect` (reads the kernel's RTC line and the
alarm bytes, maps them onto `1-none-crumb.txt`), then `hwclock --systohc` once time is synced.

## EFI storage validated while awake; recorded repeat ready (2026-09-14 17:54)

The first awake EFI selftest loaded/unloaded the module successfully, but
returned EIO, `/var/tmp/imac-efi-sleep-4nv01lv4`. Added error-stage reporting;
the next attempt `/var/tmp/imac-efi-sleep-byd32q_3` identified read-back
attributes 0x80000007 where the strict checker expected 7. The 62-byte
variable was written/read/deleted; the updated check additionally confirmed
deletion through EFI_NOT_FOUND. That extra bit is Apple's VSS data-checksum
flag, documented by [UEFITool's format definitions](https://github.com/LongSoft/UEFITool/blob/new_engine/common/nvram.h).

The verifier now accepts exactly 7 or 0x80000007, still requires exact length
and payload, and the recovery decoder retains the raw attribute value. It
still rejects other flags, absent nonvolatile/runtime bits, foreign GUIDs,
wrong part/header ownership and oversized records. Regression coverage added
for Apple's flag and nearby invalid combinations. Also replaced buffered
Path.write_text on the action parameter: the failed buffered flush/close had
retried the selftest (two log entries 17 ms apart). The action now uses one
unbuffered write. Twenty-three offline tests pass; module W=1 build is clean.

Corrected awake selftest PASS: `/var/tmp/imac-efi-sleep-jha88qad`, run ID
`c85602487d2c43f085f8f91adc84115e`, test_attrs=2147483655 (0x80000007),
storage_ready=Y, seen_cycles=0, armed=N, capture writes=0, module unloaded.
This verifies immediate EFI storage round-trip and deletion, **not** timer
execution during suspend or survival through the reset. No sleeps occurred;
boot 438e5fbc remains 0/0. No snapshot records have been created.

Added --tb-removed forwarding through both recorder wrappers to retain the
latest failed experiment's device conditions. The installer reappeared as
mounted /dev/sdb1 after reboot. Reconfirmed 24a9:205a on Alpine Ridge USB 4-1,
then safely unmounted and powered it off again using udisksctl.

Next command, prepared for immediate launch:

    sudo python3 notes/second-sleep-efi-capture.py run --tb-removed

It loads/selftests the module, enables PM tracing, and runs the existing
platform --prime --mode s2idle --delay 5 --wifi-unbound --serial test with
the full Thunderbolt subtree removed. The module observes PM notifiers and
callback/phase tracepoints; only the second PM transition arms its 20-second
non-freezable worker. Metadata is saved before a best-effort task stack in
at most four 1 KiB EFI records. It does not force a panic or reset.

Wake the first real sleep after ~30 s; leave the second staged attempt alone.
After any reset, collect both recorders before another test or clearing:

    sudo python3 notes/second-sleep-efi-capture.py collect
    sudo python3 notes/second-sleep-trace.py capture

EFI collect archives raw variables and decoded text under /var/tmp/imac-efi-sleep-*.
Direct kernel-created EFI keys may not appear in the mounted efivarfs until
a reboot; do not mistake an empty live directory for proof of no write if the
loaded module reports writes>0. All records remain until explicit `clear`,
which archives and validates ownership before deletion. If the test returns
with an error without reboot, inspect its PM job and module status first;
the helper deliberately retains the module when job completion is unknown.

## Whole-Thunderbolt removal also resets (2026-09-14 17:44)

Owner completed authentication and reports the same first-success/second-reset
sequence. Run `/var/tmp/imac-second-sleep-ybtw83d_`, boot b118d60b:

- `platform --prime --mode s2idle --delay 5 --wifi-unbound --serial --tb-removed`.
  Context confirms untouched starting counters and all requested flags.
- `thunderbolt.json` lists 05:00.0, 06:00.0, 06:01.0, 06:02.0, 06:04.0,
  07:00.0 and 08:00.0. The journal records xHCI removal, deregistration of
  USB buses 3 and 4, and release of PCI buses 07, 08 and 06 at 17:36:26.
  The helper checks the empty PCI subtree before starting each attempt.
- First real s2idle 17:36:27.073367 to 17:37:43.815876, PASS, 73.0947 s
  actual sleep (77.4594 s whole attempt). Its PM callback log has no devices
  in the removed subtree. Noirq suspend took 147.5 ms; noirq resume 123.7 ms.
- Second starts 17:37:44.560596, with the kernel's suspend entry at
  17:37:44.561071. No second result/summary/restoration file survived. Next
  kernel set RTC time to 17:39:01; its first journal timestamp is 17:39:20.
  Owner explicitly confirms a reset. Old pkexec session 18988 no longer exists.

Removing the entire Alpine Ridge PCI subtree did not prevent this failure.
That excludes those removed functions' Linux suspend callbacks in this run;
00:1c.4, firmware methods and the physical hardware remain. The installer
stick was absent from Linux for both attempts, but was software-ejected,
not physically unplugged. Do not claim that every Thunderbolt firmware path
or physical interaction is excluded.

Current boot `438e5fbc-e398-4aae-ba13-e5ccc7012a8f` is untouched (0/0), with
pm_test=none, pm_async=1, mem_sleep=deep and the trace/nonvs boot arguments.
Ran capture before any further recorder/sleep changes:
`/var/tmp/imac-sleep-trace-capture-mcx8xmbe`, empty 0/0 and last_boot_info
`0 [kernel]`. This attempt did not enable tracing, so emptiness alone is not
a new retention experiment. Boot dmesg again reports a magic mismatch.

Next is awake validation of the prepared EFI helper's write/read/delete path.
Reviewed the module against matching local kernel source: raw PM tracepoint
signatures match, the recorder and EFI runtime queues are not freezable, and
the bounded task-stack capture uses the exported stack API. The regular EFI
wrapper retains its normal checks; on this Mac Linux limits runtime services
to EFI 1.10, so QueryVariableInfo is unsupported and its size fallback does
not establish free NVRAM capacity. The diagnostic is limited to four 1 KiB
records under its own GUID, refuses existing records, and has not yet been
loaded or hardware-validated at this checkpoint.

## Whole-Thunderbolt test ready after safely ejecting installer (2026-09-14 16:09)

The afternoon continuation found boot `b118d60b-7117-4d38-ac19-a83fa1cfe784`
still unslept (0/0), pm_test=none, pm_async=1, mem_sleep=deep. The newer
midday handoff below records the owner's request for whole-chip removal;
its --tb-removed implementation and four tests are present and were preserved.

The Omarchy installer remained mounted as /dev/sdb1 at
`/run/media/markpronkin/OMARCHY_202609`. Verified its USB identity 24a9:205a,
product USB3.2 Flash Drive, and ancestry through Alpine Ridge xHCI 08:00.0
at USB 4-1. Safely unmounted with udisksctl, then used `udisksctl power-off
--block-device /dev/sdb --no-user-interaction`. Both succeeded. Read-only
verification then found /sys/class/block/sdb absent and tb_in_use() empty,
while the seven Thunderbolt PCI functions were present and the NHI bound.
The stick was **software-ejected, not physically unplugged**. It may return
after a PCI rescan or reboot; check its state before interpreting later tests.

Command launched via pkexec at 16:10:

    sudo python3 notes/second-sleep-pm-test.py platform --prime --mode s2idle --delay 5 --wifi-unbound --serial --tb-removed

At 16:17, host PID 34174 is still pkexec, with a Polkit authentication helper
waiting; the Python diagnostic has not started. Exec session 18988 remains
open with no output. Boot and counters are unchanged and no new run directory
exists. The owner must complete the system password prompt. Do not start a
second copy while this one is pending; inspect the session/process and current
boot before resuming. This is operating-system authentication, not an
automatic approval-review rejection.

Owner instructed to wake the first real sleep after ~30 s and leave the
second five-second platform test alone. This compares the known failure
with the complete Alpine Ridge PCI subtree absent during both cycles.
The helper records the removed devices and checks they remain absent before
each cycle, then rescans on normal completion. The PCH root port and ACPI
namespace remain, so a repeat failure would not rule out all firmware paths.

Additional detail from the failed recorder: boot b118d60b's dmesg at 0.131652
reports `Ring buffer boot meta mismatch of magic`. It discarded the previous
buffer before trace capture. A successful normal-reboot marker is therefore
insufficient evidence for retaining data through this failure.

Prepared a fallback `notes/pm-capture/imac_pm_capture.c` and
`notes/second-sleep-efi-capture.py` during this continuation. They build against
7.2.3-arch1-3 with W=1 and are **not loaded or hardware-tested**. The proposed
non-freezable worker observes the second PM transition and, after 20 s, would
save the last PM phase/callback and a best-effort task stack into at most four
1 KiB variables under diagnostic GUID 173f51a7-82a5-4e0a-92c4-38a4b849c5e1.
It has an awake EFI write/read/delete selftest and refuses existing records.
No kernel module was loaded and no EFI variables were written. This remains
a fallback; first perform the owner's prepared Thunderbolt test. Twenty-two
offline Python checks pass across the helpers, including the preserved
Thunderbolt tests and two new EFI-record recognition guards.

## Recorder lost the reset; whole-Thunderbolt removal prepared (2026-09-14 12:00)

The recorded run did execute (it was never written up): boot `720291d7`,
`/var/tmp/imac-second-sleep-8lscfw_9`, `platform --prime --mode s2idle
--delay 5 --wifi-unbound --serial --persistent-trace`. First real sleep PASS
(69.2 s asleep, full trace saved as `1-none-trace.txt`); the second attempt
(`started.json` 10:03:24) reset the machine as always. The post-reset capture
`/var/tmp/imac-sleep-trace-capture-qvgi5j9m` found an empty buffer (0/0
entries, last_boot_info `0 [kernel]`, survived=false): **the ring buffer
survives a normal restart but not this reset**, so the recorder cannot locate
the failing callback. The boot drop-in is still armed (`disarm` removes it).

Owner asked whether the second sleep really takes Thunderbolt away. The
journal confirms the hook's `unbound 0000:07:00.0` on both failed second
attempts, but that only unbinds the NHI driver; bridges 05:00.0/06:0x.0 and
the Alpine Ridge xHCI 08:00.0 stay present and go through suspend. The owner
asked to remove the whole chip instead.

**New variable found:** the Omarchy install stick (SSK USB3.2 Flash Drive,
`usb 4-1`, `sdb`, mounted) sits on the Alpine Ridge xHCI and has been attached
during every boot and every sleep test since 2026-09-10. It was never ruled out.

Added `--tb-removed` to the PM helper: after the existing checks it writes
`remove` on 05:00.0 (whole Alpine Ridge subtree, 7 functions, recorded in
`thunderbolt.json`), refuses to start another cycle if the chip reappears,
and at the end rescans root port 00:1c.4 (which has no hotplug slot of its
own) and waits for 05:00.0 and the NHI to be bound again. It refuses while
any USB/net/block device is below the port. Four offline tests added.

Next, on a fresh boot with the stick unplugged:

    sudo python3 notes/second-sleep-pm-test.py platform --prime --mode s2idle --delay 5 --wifi-unbound --serial --tb-removed

This is the last failing reproducer with Thunderbolt absent (and, necessarily,
the stick). Wake the first sleep after ~30 s. If the second attempt survives,
bisect: same command without `--tb-removed`, stick still unplugged.

## Retention passed; recorded repeat test prepared (2026-09-14 10:01)

Normal restart reached boot `720291d7-38d9-44a0-bc3f-cec648746109`, same
kernel and trace reservation, counters 0/0, pm_test=none, pm_async=1,
mem_sleep=deep. `second-sleep-trace.py capture` saved
`/var/tmp/imac-sleep-trace-capture-v2jpeiun`. Its trace contains exactly the
marker written on boot `5352621b` (one event, timestamp 98.349034);
marker-check.json reports survived=true and last_boot_info preserved the
previous kernel/module addresses. Verification was saved to
`/var/tmp/imac-sleep-trace-verified.json`. This establishes normal-reboot
retention; retention through the unexplained reset is still untested.

Added `--persistent-trace` to the PM helper. It checks that the imac_sleep
instance contains current-boot data, is recording, and has all three PM
events enabled before each attempt. Each attempt gets a trace marker and
each completed cycle gets trace.txt plus per-CPU buffer statistics in its
existing run directory. This saves the successful first wake's trace even
if the second reset invalidates the RAM buffer. Sixteen offline checks pass.

Prepared a small sequential wrapper `notes/recorded-second-sleep.py`:
start the recorder, run `platform --prime --mode s2idle --delay 5
--wifi-unbound --serial --persistent-trace`, then stop/capture only after
the PM helper reports successful cycles and cleanup. Owner instructed to
wake the first real sleep after ~30 s and leave the second platform test
alone. Launch pending at this checkpoint. **After a reset, capture the
recorder before mark/start or any further suspend.** Its power callback
start/end events should distinguish a suspend callback from a resume
callback, if the buffer survives this fault.

## Recorder active; retention marker ready for normal restart (2026-09-14 09:55)

Owner restarted normally after arming the recorder. Current boot
`5352621b-703b-49c2-932c-444ae95ae261`, kernel 7.2.3-arch1-3, contains
the exact memmap and trace_instance arguments. Kernel journal confirms
`imac_sleep` mapped at physical 0x800000000, size 0x1000000 (16 MiB).
The helper verified that the entire region is reserved in /proc/iomem and
that the dedicated instance exposes last_boot_info.

Ran `pkexec /usr/bin/python3 notes/second-sleep-trace.py mark`. It saved
the initial buffer under `/var/tmp/imac-sleep-trace-capture-k0jg399f`, wrote
and read back this unique marker, and paused tracing again:

    imac-sleep-trace:5352621b-703b-49c2-932c-444ae95ae261:imac-sleep-trace-capture-k0jg399f

Expected marker metadata is `/var/tmp/imac-sleep-trace-marker.json`.
No sleeps occurred: counters 0/0, pm_test=none, pm_async=1, mem_sleep=deep.
The initial capture's last_boot_info was `0 [kernel]`, consistent with the
new buffer before the marker; its trace_clock.txt also precedes mark's
selection of the global clock.

**Next: restart normally once more, then run capture before mark/start or
any sleep.** `sudo python3 notes/second-sleep-trace.py capture` must recover
the marker from boot `5352621b`. A PASS writes a verification record and
allows `start`. If retention succeeds, enable the recorder and run the same
fresh-boot sequential platform test described below. If the marker is lost,
diagnose recorder retention first; do not treat absence of a crash trace
as evidence that no kernel callback failed. Sleep remains unresolved.

## Sequential callbacks also fail; prepare persistent tracing (2026-09-14)

**Stopping point 09:50: recorder armed, restart pending.**
`pkexec /usr/bin/python3 notes/second-sleep-trace.py arm` completed successfully.
Setup log and boot backup: `/var/tmp/imac-sleep-trace-setup-7vu55vlk`.
The installed drop-in is `/etc/limine-entry-tool.d/zz-imac-sleep-trace.conf`.
Verified the actual UKI's embedded command line contains exactly the two
additional recorder arguments and the same 7.2.3-arch1-3 kernel; the generated
boot menu also contains them. Rebuild succeeded (generic missing-firmware
warnings for xhci_pci_renesas and qat_6xxx, not this machine's controllers).
Current boot remains `17f13188`, counters 0/0, pm_test=none, pm_async=1,
mem_sleep=deep. No tracing instance is expected until restarting.
Next: restart normally, run `mark` before any sleep, restart normally again,
then `capture` to check retention. See the detailed workflow below. Hardware
retention and the eventual failing callback are not yet established.

Run `/var/tmp/imac-second-sleep-aiqewubm` on boot `68b17b26` used
`platform --prime --mode s2idle --delay 5 --wifi-unbound --serial`.
The helper verifies pm_async=0 when selecting it; context.json records
serial=true and saved-settings.json records the original value 1.

- First real sleep 09:30:55.8 → 09:32:13.7 returned, success=1/fail=0,
  measured actual sleep 67.25 s.
- Second invocation at 09:32:15.1 completed Thunderbolt detach and logged
  `Performing sleep operation`. The owner reports an automatic reboot.
  Next kernel RTC time 09:33:30, first journal entry 09:33:50.
- Wi-Fi remained detached throughout. Neither that isolation nor sequential
  PM callbacks prevented the reset. The failing phase is still unresolved:
  no saved trace establishes whether late/noirq suspend or resume stopped.

Current boot `17f13188-fecf-4307-8f00-adfda2ebec21` has no sleeps (0/0),
pm_test=none, pm_async=1, mem_sleep=deep. Temporary settings cleared at reset;
the existing nonvs boot experiment remains installed.

Investigating boot-mapped ftrace buffers in the matching 7.2.3 source,
`Documentation/trace/debugging.rst` and `kernel/trace/trace.c`. These can
preserve device callback events across a warm reboot if firmware retains
the reserved RAM. Use traceoff with **no boot events** so recovered data
is not cleared by enable_instances(); capture before enabling events.
The actual memory map includes System RAM 0x100000000–0x86effffff; an
aligned 16 MiB region at 0x800000000 was selected for reservation at the next
boot. No memory is reserved or accessed by the current boot yet. Normal-reboot
retention must be checked before relying on this to diagnose another reset.
Kernel CONFIG_RESET_ATTACK_MITIGATION is off. EFI pstore can be enabled at
runtime, but only catches oops/panic and does not itself record an unexplained
hardware reset; it remains disabled. No new kernel module was loaded.

Prepared `notes/second-sleep-trace.py`, scoped to this iMac18,3 and the
existing 7.2.3-arch1-3 Omarchy UKI. The arm operation backs up boot files,
adds only `memmap=16M$0x800000000` and
`trace_instance=imac_sleep^traceoff@0x800000000:16M` through a dedicated
Limine drop-in, rebuilds with `limine-mkinitcpio linux`, and verifies both
the embedded command line and kernel version. It restores backed-up boot
files if rebuilding or verification fails. No sleep or reboot is automatic.
Four additional offline guard tests cover memory boundaries/overlaps,
preserving all other boot arguments (including a literal `$`), and requiring
a marker from a different boot with the same kernel/mapping; 15 focused
tests pass in total.

Workflow after successful arm:

1. Restart normally to activate the reservation. Do not test sleep yet.
2. `sudo python3 notes/second-sleep-trace.py mark` captures the initial
   buffer, writes a unique marker, and leaves tracing paused.
3. Restart normally again; `sudo python3 notes/second-sleep-trace.py capture`
   must find that marker from the previous boot. Logs are under
   `/var/tmp/imac-sleep-trace-capture-*`. A normal restart proves only normal
   restart retention, not retention through the unexplained reset.
4. Once verified, `sudo python3 notes/second-sleep-trace.py start` captures
   old data before clearing it and enables the three power trace events
   (device callback start/end and suspend_resume). Run the same sequential
   platform experiment on a fresh boot, then **capture before starting any
   new recording**, whether the test returned or reset.
5. `sudo python3 notes/second-sleep-trace.py stop` pauses and captures;
   `sudo python3 notes/second-sleep-trace.py disarm` removes the dedicated
   boot drop-in and rebuilds. Restart to release the 16 MiB reservation.

The successful serial first sleep's slowest noirq resume callbacks were
Thunderbolt upstream bridge 05:00.0 (5.01 s) and its USB controller 08:00.0
(1.17 s). These returned successfully; timing alone is not proof that either
causes the next attempt's reset.

## Resume: short platform test also fails with Wi-Fi held detached (2026-09-14 09:30)

The 2026-09-12 run after the section below did execute:
`platform --prime --mode s2idle --delay 5 --wifi-unbound`, logs
`/var/tmp/imac-second-sleep-q2btp_79`, boot `3f29be64`.

- Wi-Fi was detached before both cycles (`wifi.json`); neither sleep hook
  rebound it between them, so the immediate re-probe/removal crash was avoided.
- First real sleep 13:20:31.2 → 13:21:54.9 returned, measured actual sleep
  74.63 s, success=1/fail=0.
- Second invocation began 13:21:55.6, Thunderbolt unbound and systemd logged
  `Performing sleep operation`. It never returned. Owner reported that the
  second attempt rebooted the machine. Next kernel RTC time was 13:23:11;
  the first journal entry was later, at 13:23:35.
- Thus the platform-stage failure persists with a five-second hold and no
  Wi-Fi rebind between cycles. It is not specific to the 70-second delay;
  the remaining uncertainty is where in late/noirq suspend or resume it fails.
  There is still no saved marker proving the platform delay itself was reached.

At the 2026-09-14 continuation, the machine is still on the resulting boot
`68b17b26`, kernel 7.2.3-arch1-3, counters 0/0, pm_test=none, pm_async=1,
mem_sleep=deep, no temporary /run sleep.conf. The nonvs boot parameter and
parked /etc s2idle drop-in remain. No further hardware test occurred between
the September 12 failure and this continuation.

Decoded the saved DSDT and Thunderbolt SSDT (SSDT7, TbtOnPCH) using ACPICA
built under `/tmp/imac-acpi-analysis`. The initial all-tables disassembly had
duplicate namespace objects and guessed argument counts; do not rely on it.
`iasl -e DSDT -d SSDT7` resolves external methods/fields correctly and
produces the usable Thunderbolt disassembly. Its Darwin `_PS0`/`_PS3` paths
carry stateful PCI-link and GPIO sequencing (`PCDA`, `PCEU`, `PCED`, `UGIO`),
which remains relevant even with the NHI driver unbound. This is a candidate
path, not a root-cause finding. The CWDT field there is PCIe link width, not
a watchdog timer.

Next prepared test on this unslept boot:

    sudo python3 notes/second-sleep-pm-test.py platform --prime --mode s2idle --delay 5 --wifi-unbound --serial

`--serial` temporarily sets pm_async=0 for both cycles and restores its
original value. This is the only additional change from the failed short run.
Wake the first real sleep after about 30 s; the five-second platform stage
returns automatically if it succeeds. Eleven offline helper tests pass.

## Short platform test was blocked by a Wi-Fi rebind/removal crash (2026-09-12 13:19)

Owner saw the login screen after the first wake, but it did not accept keyboard
input and appeared frozen. Machine is now on boot `3f29be64`; whether the
owner forced the restart or it restarted itself has been asked, not yet answered.

Saved run `/var/tmp/imac-second-sleep-yexih9qd` on `b6a8dc5d`:

- First real s2idle sleep 13:07:28.7 → 13:11:23.9 returned, success=1/fail=0,
  measured real sleep 226.1 s; both hooks rebound. The updated helper correctly
  handled the completed service's timestamp reverting to 0.
- The second systemd invocation started at 13:11:24.7, **less than a second
  after the rebind**. It froze user.slice (including the login screen), then
  the Wi-Fi unbind hit `WARNING: !work->func` in `__flush_work` through
  `cancel_work_sync → brcmf_bus_cancel_reset_work → brcmf_pcie_remove →
  unbind_store`. A kernel NULL-pointer BUG followed at 13:11:24.737; its
  remaining trace did not reach the journal. The Thunderbolt unbind completed.
- **No Wi-Fi-unbound success, no "Performing sleep operation", and no second
  kernel "PM: suspend entry" occurred. The five-second platform test never
  started.** It is inconclusive for the original platform-stage failure.
- Preserved kernel evidence in `notes/wifi-rebind-oops-2026-09-12.log`.

Matching source explains the initialization window: PCI bind starts asynchronous
firmware setup. `brcmf_alloc()` publishes drvr first; `INIT_WORK(bus_reset)` is
much later in `brcmf_bus_started()`, after firmware setup and netdev registration.
`brcmf_bus_cancel_reset_work()` checks drvr, but not whether bus_reset was
initialized. The first-wake dmesg captured only `brcmf_fw_alloc_request`, not
the later firmware version message. This is strong evidence for immediate
re-unbind racing the asynchronous probe; guarding only the work item would
not establish that the remaining partially initialized teardown is safe.

Diagnostic changes only, no installed hook or driver changes:

- `--wifi-unbound` detaches the unused BCM43602 before the entire experiment,
  leaving the Wi-Fi hook no card to cycle between the two attempts; rebinds at
  the end. Refuses a Wi-Fi default route or an active connection. Default route
  verified over Ethernet enp4s0f0; Wi-Fi operstate down.
- The helper checks the current phy's debugfs `reset` file before allowing
  removal: that file is created after INIT_WORK. Mere netdev registration is
  too early. This also guards the original helper sequence when Wi-Fi remains
  in use by the diagnostic. Eleven offline tests pass, including stale phy
  and premature netdev readiness.

Next prepared run on the current fresh boot:

    sudo python3 notes/second-sleep-pm-test.py platform --prime --mode s2idle --delay 5 --wifi-unbound

One real first sleep, manually woken; then one five-second platform test,
automatic return. Keeping Wi-Fi detached is an isolation step for this newly
observed crash, not a claimed fix for the original second-sleep reset.

## 70-second platform test reset before actual s2idle (2026-09-12 13:06)

Owner: "this time it went to sleep and then rebooted". Saved run
`/var/tmp/imac-second-sleep-lwmth335` confirms `pm_test=platform`, mode
s2idle, delay=70, initial counters success=2/fail=0 on boot `830cfc6e`.
Both hooks unbound successfully; last log is suspend entry at 13:02:01.9.
New boot `b6a8dc5d` has kernel RTC time 13:03:15 local; subtracting the
previously estimated 20-second firmware/loader time gives roughly 53 s
until reset. First journal time was later (13:04:13), so use the kernel RTC
line rather than journal arrival time for this estimate.

This reproduces the reset **without entering actual sleep**: in the matching
kernel's `kernel/power/suspend.c`, TEST_PLATFORM returns before s2idle_loop.
The difference from the successful 70-second devices test includes device
late/noirq callbacks and ACPI s2idle preparation. We still do not know whether
the reset occurred inside a callback or during the 70-second wait after it.
It was the third attempt of the boot, after one real sleep and one devices
test, which must be retained when interpreting the comparison.

All temporary settings cleared at reboot: pm_test=none, mem_sleep=deep;
acpi_sleep=nonvs remains on the boot command line. Current counters are 0/0.
Next prepared test:

    sudo python3 notes/second-sleep-pm-test.py platform --prime --mode s2idle --delay 5

One real first sleep (wake manually after about 30 s), then the same platform
test with a five-second hold and automatic return. A return would show these
callbacks can complete after the first wake, directing attention to the long
hold rather than assuming a callback hang. No more boot options changed.

## Real first sleep + 70-second devices test passed (2026-09-12 13:01)

Run `devices --prime --mode s2idle` completed on boot `830cfc6e`:

- Real sleep: 12:51:30.4 → 12:52:53.3; helper measured 74.4 s of actual
  sleep. Returned with success=1/fail=0 and both hooks rebound.
- Second attempt, **pm_test=devices, not a second real sleep**:
  12:52:54.4 → 12:54:14.2; kernel entry-to-exit 79.7455 s, success=2/fail=0.
  Raw dmesg shows the test-delay marker at 1452.933601 and the first resume
  callback at 1524.593630: **71.66 seconds at the device test stage**, so
  the owner's keyboard use did not truncate the intended 70-second interval.
- Logs and raw ACPI tables: `/var/tmp/imac-second-sleep-g7942jah`.
  This clears the ordinary device-stage path for this attempt, including
  the normal amdgpu suspend/resume callbacks; late/noirq is not tested yet.

The helper's first version missed completion of the second service because
systemd unloaded the finished unit before it observed its execution timestamp
(the field reverted to 0). At 13:01 recovered the result from persistent
kernel counters/dmesg, stopped only the completed diagnostic waiter, and
restored pm_test=none, mem_sleep=deep, pm_print_times=0, pm_debug_messages=0,
initcall_debug=N, pm_test_delay=5; removed its /run sleep.conf override.
Recovery helper `/tmp/imac-second-sleep-recover.py`; summary.json records it.
The actual suspend job had already completed at 12:54:14.

Fixed the helper to accept advancing kernel counters plus an inactive
service, even if the unit has been unloaded; it still waits through post hooks.
Added two regression cases (10 offline tests now pass), and saved-settings.json
is persisted for future recovery. Next prepared run in this same boot:

    sudo python3 notes/second-sleep-pm-test.py platform --after-first --mode s2idle

70 seconds with late/noirq callbacks included, returns automatically. Do not
wake it early. This will be the third kernel suspend attempt of this boot,
following one real sleep and one staged device test; retain that ordering
when interpreting the result. No shipping suspend change is validated yet.

## Locate the second attempt's failing phase before more boot changes (2026-09-12 12:49)

Owner: "continue work on sleep. first sleep works, second doesn't".
Current boot `830cfc6e292f4807a28b5da23f6d4865`, kernel 7.2.3-arch1-3,
`acpi_sleep=nonvs` still live, `mem_sleep=s2idle [deep]`, the s2idle drop-in
still parked. At 12:49 both suspend counters were 0; no test run this session
yet. Repo remains `review/full-audit-2026-09-11` with the unrelated audit
changes present. The Wi-Fi hook stays unpushed.

Corrections from re-reading the actual logs and the matching kernel source:

- **The second attempt is not proved to have reached sleep.** The last journal
  line is `PM: suspend entry`, printed by `pm_suspend()` *before*
  `enter_state()` freezes userspace or suspends devices. Later kernel messages
  remain in RAM while journald is frozen, and disappear on reset. Shared
  device callbacks are therefore still candidates; failure in both modes
  does not establish that firmware is the cause.
- **The first S3 wake restored the desktop, but was not clean.** Boot
  `0dd66c293dc647969fa93f18589c0fe5`, 12:27:12: Thunderbolt bridges
  05:00.0 and 06:00.0/01.0/02.0/04.0 became inaccessible. xhci_hcd 08:00.0
  was removed, its USB buses disconnected, and `pci_disable_device` warned
  in the pciehp removal path. At 12:27:13 the NHI rebind failed (`timeout
  resetting host router`, -22). One returning S3 cycle supports testing
  nonvs further; it does not validate S3 for shipping or remove the need
  for the Thunderbolt workaround. The saved/restored-NVS log messages
  are unconditional in `drivers/acpi/nvs.c`, even when no buffers were
  allocated under nonvs; those lines do not show the option was ignored.
- **`acpi_osi=Darwin` is already the default here.** Current boot explicitly
  logs `ACPI: BIOS _OSI(Darwin) query honored via DMI`. Adding it would be
  a no-op. See [kernel OSI documentation](https://docs.kernel.org/firmware-guide/acpi/osi.html#apple-mac-and-osi-darwin).

Prepared `notes/second-sleep-pm-test.py`, a diagnostic separate from the
patcher. First experiment on the current fresh boot:

    sudo python3 notes/second-sleep-pm-test.py devices --prime --mode s2idle

One real first sleep (wake manually after about 30 seconds), then
`pm_test=devices` with a 70-second delay. Both use `systemctl suspend` and
the installed hooks. s2idle is selected only for this run through a /run
sleep.conf drop-in, avoiding the observed S3 Thunderbolt loss while testing
the original failure mode. The delay crosses the observed ~50-second reset
time without entering the real second sleep. This is a diagnostic, not a
mitigation: the device stage can still hang/reset.

The script saves a fsynced `started.json`, kernel logs, service logs,
counter deltas, elapsed and actual sleep time, and raw ACPI tables in a
unique `/var/tmp/imac-second-sleep-*` directory. It requires a fresh boot
for `--prime`; a pm_test success cannot validate the first real sleep.
It waits for a *new* systemd-suspend.service invocation to finish before
restoring pm_test (systemctl suspend itself returns asynchronously).
pm_async and console_suspend stay at their original values. Temporary
debug/sysfs and /run configuration is restored after a completed test;
reboot clears it if the machine resets. If the sleep job's completion cannot
be established, it deliberately leaves pm_test selected rather than risk
turning a queued test into real sleep.

Offline validation: eight focused tests cover aborted/retried cycles,
failure to reach the test delay, early return, wrong mode, false primer
success, and the async service-completion race. CLI help and diff whitespace
checks passed. Hardware test pending at this checkpoint.

If devices passes, next is
`... platform --after-first --mode s2idle` in the same boot, again 70 s.
The kernel's platform test reaches the point immediately before the s2idle
loop (including device late/noirq callbacks). A reset at devices points to
an earlier path; devices pass + platform fail narrows the next investigation
to the added late/noirq work. Passing staged tests still does not validate
real repeat sleep, and later tests in one boot are not independent second
attempts. See [kernel PM debugging documentation](https://docs.kernel.org/power/basic-pm-debugging.html).

## acpi_sleep=nonvs permits one S3 return; second attempt still resets (2026-09-12 12:27)

`notes/s3-nonvs-test.sh arm` put `acpi_sleep=nonvs` on the cmdline and parked
the MemorySleepMode=s2idle drop-in, so sleeps land in real S3. Result:

- **Sleep 1 was genuine deep S3 and restored the desktop.** "PM: suspend entry
  (deep)" 12:24:18.3, 2 min 54 s asleep, then "ACPI: PM: Low-level resume
  complete", "Waking up from system sleep state S3", "PM: suspend exit"
  12:27:13.2. Every earlier S3 attempt on this machine reset on wake
  (901d66f, the 2026-09-10 ladder), so nonvs is promising for that half.
  The 12:49 review above records the Thunderbolt/USB failures on this wake.
- **Sleep 2 reset at ~50 s as always** (started 12:27:38.9, next kernel start
  12:28:49 minus ~20 s firmware).

The repeated-attempt failure has occurred in both s2idle and S3. The prior
inference that this locates the cause below the OS is withdrawn: the second
attempt's last log line does not establish how far suspend progressed.
S3 + nonvs remains experimental, including its Thunderbolt/USB recovery.

## Four-driver shotgun cleared them all (2026-09-12 12:20)

`notes/s2idle-one-sleep.sh 180` with thunderbolt, brcmfmac(+wcc), mei(+me,
hdcp, pxp) and i2c_i801(+ee1004) all unloaded before the fatal second sleep:
reset anyway. So the interrupt churn from our hooks, the ME interface and the
SMBus controller are cleared as a group, on top of applesmc, the idle states
and the device binding earlier.

What is left is expensive: amdgpu is the one large device never taken out of
the picture (unloading it kills the display, and testing a stock driver means
removing the 5K module and rebooting), and everything else points at
firmware/SMM state that the OS cannot reach. The remaining cheap-ish
experiments are boot parameters, one boot each: `acpi_sleep=nonvs` with real
S3 (S3 already sleeps properly here and only fails on wake, and nonvs is the
documented fix for exactly that), and `acpi_osi=Darwin`.

Recommendation at this point is to stop chasing it and make the project safe:
0.2.0-alpha unmasks suspend on every Retina 5K iMac, and only brcmfmac's
refusal kept this machine from resetting. That needs reverting or gating in
0.2.1-alpha with the findings written up, regardless.

## State diff across the first sleep (2026-09-12 12:13)

`notes/s2idle-state-diff.sh` snapshots system state, takes only the safe first
sleep, snapshots again and diffs. What the first cycle actually changes:

- **Interrupts are renumbered.** Thunderbolt's MSI-X moved 41/42 -> 42/43,
  Wi-Fi's MSI 64 -> 67, and mei_me took the freed 41. That is our own hooks
  unbinding and rebinding those two devices; mei_me re-requests its IRQ on
  resume as well.
- **i2c_i801 (SMBus) stays awake.** runtime=suspended before the sleep,
  runtime=active and D0 after, still active 95 s later. The resume log also
  shows the firmware itself taking the bus ("BIOS is accessing SMBus
  registers", driver access inhibited), so SMM touches this controller.
- Two ACPI events fired during the cycle: gpe55 (enabled) once and gpe6D once
  **while disabled**, i.e. spurious. Counters were stable afterwards, so
  there is no GPE storm.
- Noise: fan 1196 -> 1204 rpm, package temp 60 -> 58 C, C8 s2idle usage 0 -> 1,
  audio 1f.3 D3->D0 (it settled back to D3 on its own), mem_sleep default
  flipping deep -> s2idle because systemd writes it before each suspend.

A boot that has already had its safe sleep is a free experiment slot: the next
sleep is the one that resets, so a mitigation can be tried there without
spending a reboot. `notes/s2idle-one-sleep.sh` does exactly that - unload a
list of modules, then take that sleep. First shot unloads all four suspects at
once (thunderbolt, brcmfmac, mei, i2c_i801); if it survives, later boots
bisect one at a time.

## applesmc cleared too (2026-09-12 12:05)

`s2idle-second-sleep-test.sh 180 rebound - applesmc` unloaded applesmc between
the sleeps: sleep 1 fine as always, sleep 2 reset again. So the SMC driver is
not the trigger either. Twelve sleeps over six boots now.

Remaining ideas, none of which need more reset cycles to start with: a state
diff across a single (safe) first sleep - ACPI GPE counters
(/sys/firmware/acpi/interrupts/*), /proc/acpi/wakeup, PCI power_state and
runtime_status, USB wakeup flags - to see what the first resume leaves
changed; and boot-parameter experiments, `acpi_osi=Darwin` (Mac firmware
gates ACPI behaviour on the OSI string, a classic Mac-on-Linux quirk) and
`acpi_sleep=nonvs`, each costing one reboot to arm plus two sleeps to test.

## One sleep per boot, cause still unknown (2026-09-12 11:58)

The C3 cap does not help either: `s2idle-second-sleep-test.sh 180 rebound 456`
gave sleep 1 = 11:57:44.3 -> 11:58:04.2 (20 s, woken) and sleep 2 started
11:58:07.6, reset at ~50 s (next kernel start 11:59:21 minus ~20 s firmware).

Ten sleeps over five boots. The pattern holds against every variable tried:

    idle states      full / C7s+C8 off / C6+C7s+C8 off (C3 cap)   no effect
    device binding   Thunderbolt + Wi-Fi bound or left unbound    no effect
    first sleep      20 s to 264 s                                no effect
    wake method      keypress, and an RTC alarm that never fired  no effect

So this machine takes exactly one s2idle sleep per boot; the second resets it
at ~50 s with no trace. Untested suspects, in order of interest: Apple's SMC
driver (applesmc is loaded, and the SMC is the component that can reset a Mac
- try unloading it between the sleeps), ACPI GPE state left behind by the
first resume (diff /sys/firmware/acpi/interrupts/* and /proc/acpi/wakeup
across the first cycle), other Mac-specific drivers (mei, apple_mfi_fastcharge,
the Thunderbolt controller's hardware state rather than its driver binding),
and finally deep S3 with `acpi_sleep=nonvs`, which fails differently (S3
sleeps, wake resets).

Project consequence: 0.2.0-alpha unmasks suspend on every Retina 5K iMac. On
this machine brcmfmac refused every suspend, which hid the reset; a user whose
Wi-Fi does answer the D3 handshake would get a machine that resets on its
second sleep. Re-masking suspend by default, or at least a loud README
warning, belongs in the next release regardless of how this investigation
ends.

## Hooks cleared, C3 cap is the open question (2026-09-12 11:50)

`s2idle-second-sleep-test.sh 180 unbound` on a fresh boot: sleep 1 ran
11:47:58.5 -> 11:50:33.2 (154.8 s) and woke cleanly; both devices were then
left unbound, and sleep 2 (started 11:50:36.2) still reset at ~50 s (next
kernel start 11:51:50, minus ~20 s firmware). So rebinding the Thunderbolt NHI
and the Wi-Fi card on resume is NOT what breaks the second sleep, and neither
is their bound state during it.

What has never been tested is a *second* sleep with the idle states capped:
every C3-capped run so far was a first sleep. The owner has said they do not
need idle states deeper than C3, so a permanent cap is acceptable to them.
Next: `sudo bash notes/s2idle-second-sleep-test.sh 180 rebound 456`, which
holds C6/C7s/C8 disabled across both sleeps and the gap between them. If
sleep 2 survives, the fix is a C3 cap; the natural shape is the kernel
parameter `intel_idle.max_cstate=3` on the boot cmdline, which is the same
machinery the retired `idle=poll` drop-in already used in the suspend module
(boot tier, boot-image rebuild), or a sleep hook if a sleep-only cap proves
enough. If sleep 2 still resets, C-states are irrelevant and the remaining
avenue is deep S3 with `acpi_sleep=nonvs`.

## The real pattern: every second sleep of a boot resets (2026-09-12 11:45)

The C-state reading in the next section is wrong; it was an artefact of test
ordering. All eight real sleeps line up by position within the boot, not by
idle state:

    boot 2026-09-10 19:49    15:49 survived 50 s     15:56 reset ~50 s
    boot 2026-09-11 15:57    16:09 survived 46 s     11:09 reset ~50 s
    boot 2026-09-12 11:10    11:22 survived 264 s    11:30 reset ~50 s
    boot 2026-09-12 11:31    11:34 survived 190 s    11:40 reset ~50 s

The first sleep after a boot always survives, whatever the idle states allow;
the two long ones (264 s and 190 s) merely happened to be the runs with
C-states restricted, which is what produced the false lead. The second sleep
of a boot always resets at about 50 s, restricted or not: the 10-minute
attempt at 11:40 with C7s and C8 disabled reset at ~50 s just like the
unrestricted ones (sleep 11:40:20.5 -> next kernel start 11:41:30, minus ~20 s
of firmware).

So something the first resume leaves behind breaks the next sleep. The obvious
suspects are this project's own hooks: the Thunderbolt NHI and the Wi-Fi card
are unbound before sleep and rebound on resume, and a rebound device may not
be in the state the firmware expects. Next test:
`notes/s2idle-second-sleep-test.sh`, which runs both sleeps in one boot and
has an `unbound` mode that leaves the two devices unbound between them. If the
second sleep then survives, the rebinds are implicated and the hooks must
defer or change how they rebind; if it still resets, the platform cannot sleep
twice per boot and suspend stays unshippable.

## Root cause: the deepest CPU idle states (2026-09-12 11:22)

With C6, C7s and C8 (cpuidle state4/5/6) disabled on all cores, the machine
slept 11:22:14.826 -> 11:26:39.307, 4 min 24 s, and woke on a keypress with
both hooks rebinding normally (suspend_stats: success 1, fail 0). The s2idle
counters show that sleep ran in C3 (state3, 4 entries, ~256 s of the 264 s).
So with the deepest states available the platform resets itself at ~50 s, and
capped at C3 it sleeps indefinitely. This also rehabilitates the retracted
456df26 idle=poll observation: disabling C-states really did matter, even
though brcmfmac was refusing those particular suspends.

Narrowing, 11:30: with only C8 disabled (state6) it reset again at about 50 s
(sleep began 11:30:11.7, next kernel start 11:31:22, minus ~20 s of firmware).
So C8 alone is not the trigger: C7s or C6 is. Next `... 150 56`, which leaves
C6 as the deepest; surviving means the fix disables C7s and C8, resetting
means C6 goes too, which is the combination already proven at 4 min 24 s.
Then a ~10 minute confirmation. The fix mirrors the existing hooks: a
system-sleep hook that disables the offending states in pre and restores them
in post, wired into the suspend module with tests and docs, matching states by
name (C6/C7s/C8) rather than by index, since indices vary by CPU. A shallower
sleep state costs power on an idle desktop, so disable as little as possible.

Result, 11:34: with C7s and C8 disabled (deepest C6) it slept 11:34:42.5 ->
11:37:52.3, 3 min 10 s, and woke cleanly; the counters show C6 usage 2 with
182 s of the 190 s spent there. So C6 is safe and C7s or deeper is fatal,
which fits Apple firmware that never supported the S0ix path those states
open. Minimal fix: keep the CPU out of C7s and C8 while asleep. Remaining: a
~10 min sleep at C6 (`notes/s2idle-cstate-test.sh 600 56`) as confirmation,
then the hook itself. Note the repo is on branch review/full-audit-2026-09-11
with an unrelated audit uncommitted in the working tree, including changes to
scripts/imac-patcher, so the wiring should not be mixed in there blindly.

## The reset is time-based: about 50 s into s2idle (2026-09-12 11:09)

Two more cycles and some arithmetic pin it down. Firmware plus loader takes
about 20 s on this machine (clean reboot 2026-09-10: last entry 19:48:29.7,
next kernel start 19:48:52 by the RTC). Subtracting that from each reset:

    15:56:30 entry -> next kernel start 15:57:41  =>  reset ~50 s into sleep
    11:09:12 entry -> next kernel start 11:10:22  =>  reset ~50 s into sleep

The survivors were woken before that: 15:49:30->15:50:20 (50.1 s) and
16:09:03->16:09:49 (46.0 s, a third cycle the owner ran unprompted). So every
sleep left alone dies at about 50 s, and both that came back were woken at
46-50 s, just under the cliff.

The rtcwake alarm is a red herring: the menu suspend had no alarm and died the
same way. rtc_cmos does run with use_acpi_alarm=Y here and the alarm was armed
for +40 s, but nothing woke.

Wake sources enabled at the time: ACPI PEG0, RP01, ARPT, RP02, GIGE, RP05,
RP17, XHC1, XHC2; USB wakeup on a "USB Receiver", a DualSense controller, a
Rapoo 2.4G receiver and the Bluetooth controller; tg3 Ethernet power/wakeup
enabled. So one hypothesis is a spurious wake at ~50 s whose resume crashes,
the other a platform or firmware reset once the package reaches its deepest
idle state.

Next test (owner): disable C6, C7s and C8 (cpuidle state4/5/6) on all cores,
sleep two minutes, and watch whether the screen lights up before any reboot.
Surviving implicates the deep idle states; a reset with the screen lighting
first implicates a wake with a broken resume, and then wake sources get
disabled one at a time (/proc/acpi/wakeup, USB power/wakeup).

## Second real suspend reset the machine (2026-09-11 15:56)

The owner suspended from the Omarchy menu (its action is `systemctl
suspend`) after the first good cycle. Both hooks ran, the kernel entered
s2idle at 15:56:30.145, and the journal ends there. The machine rebooted by
itself about a minute later (the next boot's kernel starts at 15:57:57); in
the owner's words, "for roughly one minute everything was fine, then it
suddenly rebooted". Whether the owner had tried to wake it is not yet known.

Ruled out: the Intel TCO watchdog (the firmware locks NO_REBOOT, "unable to
reset NO_REBOOT flag, device disabled by hardware/BIOS", and no watchdog
device exists); systemd's runtime watchdog (RuntimeWatchdogUSec=0); a kernel
panic with auto-reboot (kernel.panic, panic_on_oops, hardlockup_panic and
softlockup_panic are all 0, so a panic would freeze, not reboot); a logged
machine check (none at the next boot). No pstore backend is active
(efi_pstore is off by default on Arch), and nothing abnormal was logged
between the first resume and the second suspend. So it is a hardware or
firmware reset during s2idle, a triple fault or a platform reset, with no
trace left.

The first cycle slept 50 s and survived; this one reset after roughly
60-75 s. Before the Wi-Fi hook, brcmfmac refused every suspend, so the
machine stayed up; now it sleeps and dies. **The Wi-Fi hook (65c2d88,
unpushed) must not be released until this is understood.** Suspend should
not be used meanwhile; nothing suspends automatically (hypridle has no
suspend listener).

Candidate causes, none tested: something that fires about 60 s into s2idle;
the deepest CPU state s2idle enters (intel_idle on this i5-7600K offers C1
to C8; the retracted 456df26 once blamed C-states, before brcmfmac was found
to be refusing those suspends); being the second suspend after a resume; or
Apple's ACPI powering down (D3cold) the unbound Wi-Fi or Thunderbolt
functions during sleep.

Next (owner, sudo; each failure is a hard reset): on a fresh boot, two
RTC-woken 40 s suspends in a row (`sudo rtcwake -m no -s 40 && systemctl
suspend`), then one of 120 s, noting whether the reset comes before the
alarm. After each good cycle read the s2idle C-state counters (`grep .
/sys/devices/system/cpu/cpu0/cpuidle/state*/s2idle/usage`). If duration
matters, repeat 120 s with C7s and C8 disabled.

## Real suspend with both hooks (2026-09-11 15:49): first confirmed s2idle cycle

The owner applied suspend from the checkout (both hooks installed 15:49:03)
and ran `systemctl suspend`: entry 15:49:30, systemd's "System returned from
sleep operation 'suspend'" at 15:50:20 (50 s asleep, woken by the owner). No
brcmfmac timeout. The Thunderbolt and Wi-Fi hooks unbound 07:00.0 and 03:00.0
before sleep and rebound them after; the card re-probed (same 2015 firmware)
and NetworkManager managed wlp3s0 again. After resume: 5K link-health armed on
the resume modeset and passed 8/8 with 0 recoveries; tg3 link back in 4 s; the
known SATA "slow to respond" recovery; `--status` from the checkout shows
suspend applied. `/sys/power/suspend_stats` for this boot: success 2 (staged
test 3 and this cycle), fail 6 (all 0000:03:00.0, -5). This machine exposes no
hardware-sleep residency counters, so how deep s2idle gets here is unmeasured.

One kernel WARNING, not from the hook. At 15:49:29.256, 170 ms before systemd
started the suspend service, `brcmf_remove_interface` hit
`WARN_ON(ifp->drvr->iflist[ifp->bsscfgidx] != ifp)` (core.c:968) in
`brcmf_fweh_event_worker`, right after wpa_supplicant deleted p2p-dev-wlp3s0
during NetworkManager's sleep teardown. It returns early; nothing broke.
Yesterday's attempts had the same teardown without it; the difference is that
the driver had been rebound (staged test 3) before this suspend, so it may
recur on every suspend after a hook rebind. If it does, it is a brcmfmac
bookkeeping bug on P2P deletion after a re-probe: upstream material, cosmetic
apart from the W taint.

**Stopping point now:** one cycle confirmed. Next: a few more cycles (one
longer, one through the desktop's sleep action or idle timer), watching for the
warning; then the README status (its cells and "no complete cycle" paragraph
predate this test), the 0.2.0-alpha release notes, and push plus 0.2.1-alpha.
The owner decides on the push and the release.

## Update (2026-09-11, evening): staged test run, fix implemented

The owner ran `sudo bash notes/wifi-d3-test.sh`:

    1-wifi-up        FAIL   brcmf_pcie_pm_enter_D3 timeout, -5
    2-wifi-down      FAIL   same
    3-wifi-unbound   PASS   no brcmfmac errors; wlp3s0 back after the rebind

The handshake fails whatever the interface state, so the NetworkManager
explanation under "Findings", "Trigger" below is refuted. The firmware
leaves D3_INFORM unanswered most of the time; the one earlier pass (the
devices run in TODO.md) and the real deep suspend that slept show it
sometimes answers. The cause inside the firmware is unknown (deep sleep with
no host wake is a guess); brcmfmac's trace event (CONFIG_BRCM_TRACING) would
show the mailbox traffic if it is ever chased upstream.

Detaching the card is what makes the device stage pass, so option 1 is
implemented and committed with this update:

- `scripts/imac-wifi-sleep-hook` unbinds brcmfmac devices with ID
  `14e4:43ba` before sleep and rebinds them after. It is a second hook next
  to the Thunderbolt one, which is unchanged. Tests:
  `tests/test_wifi_sleep_hook.py`.
- The suspend module (base and Fedora) installs and removes it and requires
  it for "applied", so existing installs read partial until suspend is
  applied again.
- README: the two ✅ "Verified workaround" suspend cells are now ⚪ Untested,
  the Wi-Fi card is the fourth listed failure, and the paragraph that called
  s2idle hardware-verified now says no complete cycle is confirmed.
- 286 offline tests pass.

**Stopping point now:** waiting for the owner to install it from the
checkout and try one real suspend. That needs sudo and a go-ahead; it is
probably the first real s2idle sleep here and can still hang (power-cycle):

    ./scripts/imac-patcher --apply suspend      # --status shows partial first
    systemctl suspend                           # wake with a key after ~20 s
    journalctl -b --since "10 min ago" | grep -E 'sleep-hook|sleep operation|returned from sleep|Failed to put|brcmf|PM: suspend'

Success is systemd's "System returned from sleep" with no brcmf errors. Then
correct the 0.2.0-alpha release notes (their "clean s2idle resume recorded
earlier" line), push `main`, and release 0.2.1-alpha. Still unanswered:
guard suspend against a pre-0.1.91 5K driver? Fast-forward `test`?

## Earlier stopping point (2026-09-11 15:27 CEST)

- Diagnosis done (below) and options presented to the owner. Waiting for the
  owner to run the staged test, which needs root (the agent has no
  passwordless sudo):

      sudo bash notes/wifi-d3-test.sh

  Three `pm_test=devices` runs in s2idle mode (Wi-Fi up, Wi-Fi down as
  NetworkManager leaves it, card unbound), about 30 s, self-restoring.
  Expected: up PASS, down FAIL, unbound PASS. Ask for its output first.
- Not done yet: the hook change, the real suspend test, and correcting the
  README and 0.2.0-alpha notes (see "Record to correct").
- Also unanswered from the 0.2.0-alpha summary: guard suspend against a
  pre-0.1.91 5K driver? Fast-forward `test` (`b4b0a61`) to `main`?

## Machine and repo state at the stop

- iMac18,3, Omarchy, 7.2.3-arch1-3, same boot since 2026-09-10 19:48:53,
  running the 0.1.92-alpha 5K driver build. Installed patcher: 0.1.92-alpha.
- suspend.target static (unmasked), hibernate family masked, Thunderbolt hook
  and `/etc/systemd/sleep.conf.d/imac5k-s2idle.conf` installed, mem_sleep
  `[s2idle] deep`, no `mem_sleep_default` on the cmdline.
- Wi-Fi unused: `wlp3s0` down and disconnected; NetworkManager and
  wpa_supplicant active (not iwd); default route over Ethernet `enp4s0f0`
  (tg3), plus USB Ethernet `enp0s20f0u4u2i4`. WoWLAN disabled. Unbinding the
  card cannot cut the network here.
- Repo: `main` = `origin/main` = `da90c1b` (v0.2.0-alpha) before this
  checkpoint; `origin/test` = `b4b0a61`.

## Findings

- Chip: BCM43602 `14e4:43ba` rev 01, Apple subsystem `106b:016f`, at
  `0000:03:00.0`. Firmware `brcm/brcmfmac43602-pcie` 7.35.177.61 of
  2015-11-10 (linux-firmware-broadcom 20260810-2), the only one Linux has; no
  clm_blob. The kernel has CONFIG_BRCMDBG=y and CONFIG_BRCM_TRACING=y.
- The only suspend attempts in the retained journal (2026-09-10 19:51 and
  19:52, boot `4f73600e`) all aborted: `brcmf_pcie_pm_enter_D3: Timeout on
  response for entering D3 substate`, `pci_pm_suspend ... returns -5`, "Some
  devices failed to suspend", then systemd's "Failed to put system to sleep.
  System resumed again: Input/output error". Each attempt shows two s2idle
  entries (systemd falling back through its SuspendState list). The
  Thunderbolt hook ran fine; the display recovered with link-health PASS.
- Driver (7.2.3 `brcmfmac/pcie.c` 2636-2663): enter_D3 sends
  `H2D_HOST_D3_INFORM` through the shared-memory mailbox and waits 2 s
  (`BRCMF_PCIE_MBDATA_TIMEOUT`) for `D2H_DEV_D3_ACK`; a timeout returns -EIO,
  which aborts the system suspend. leave_D3 (2666-2705) already re-probes a
  card that lost its state. brcmfmac acks the device's deep-sleep request
  (`DS_ENTER_REQ`) but has no step that wakes it before sending D3_INFORM.
- Kernel timestamps: attempt 1 took 3.0 s from console suspend to the
  timeout, attempt 2 took 3.9 s. The extra second matches
  `brcmf_pcie_send_mb_data` waiting on a mailbox word still pending: the
  firmware never consumed the first D3_INFORM. No other brcmfmac error all
  boot while NetworkManager kept the radio on, so the normal command path
  works; only the mailbox handshake goes unanswered.
- Trigger: within 0.5 s of logind's "The system will suspend now!",
  NetworkManager ("sleep requested") moves `wlp3s0` from disconnected to
  unmanaged, resets its MAC and has wpa_supplicant deinit it; only then does
  systemd-sleep run. With the interface down, `brcmf_cfg80211_suspend`
  (cfg80211.c 4268) returns at `!check_vif_up`, skipping the scan abort, the
  link-down with its 500 ms settle, and MPC, before the PCI handshake. The
  earlier passing `pm_test=devices` run (TODO.md: "wiphy suspend 504 ms", "no
  brcmfmac errors") bypassed NetworkManager, so that handler ran in full; the
  direct `echo mem > /sys/power/state` deep test also slept for real.
  Hypothesis: firmware left down stops servicing the mailbox. Test 2 checks
  it.
- Community practice: unload brcmfmac around sleep (Arch forum, BCM43602 on
  a Dell XPS: `modprobe -r brcmfmac_wcc brcmfmac` pre, `modprobe brcmfmac`
  post). Omarchy's Mac guidance (discussion #4695): unload the Broadcom chips
  that abort in enter_D3 (BCM4377b), keep BCM4364 bound.

## Record to correct once test 2 fails as expected

The 2026-09-10 17:13 "validated" s2idle cycle (TODO.md around line 275; the
suspend handoff's Validation, item 2) went through `systemctl suspend`, so
through NetworkManager's sleep, and was judged on signs the aborted attempts
share (entry/exit lines, hook unbind/rebind, SATA recovery). Its journal is
gone. `3f07ab5` (2026-09-08) had already found brcmfmac rejections posing as
successes. So a real s2idle sleep has probably never completed here. The
README suspend section ("hardware-verified ... resumed cleanly") and the
0.2.0-alpha release notes ("The clean s2idle resume recorded earlier ...")
need correcting. A real success shows systemd's "System returned from sleep"
and no brcmf errors.

## Options given to the owner

1. Recommended: detach the card around sleep, as the Thunderbolt hook does:
   unbind/rebind brcmfmac devices with ID `14e4:43ba` only, leaving the iMac
   Pro's BCM4364 bound. Cost: Wi-Fi reconnects after wake.
2. Driver fix (wake the firmware before D3_INFORM, or don't fail suspend on
   the timeout): proper and upstreamable, but a second patched module.
3. Newer firmware: none for Linux.
4. This machine only, today: `blacklist brcmfmac` (Wi-Fi unused).

Warned: once Wi-Fi no longer aborts it, the next real suspend is probably the
first real s2idle sleep on this machine and can still hang (power-cycle).

## Next steps (in order)

1. Get the output of `sudo bash notes/wifi-d3-test.sh`.
2. If up PASS, down FAIL, unbound PASS: add the `14e4:43ba` unbind to the
   suspend module's sleep hook (base and Fedora backends; detect, apply and
   remove; tests next to `tests/test_tb_sleep_hook.py`; README, DEPENDENCIES,
   docs). If "down" also passes, the NetworkManager explanation is wrong, but
   an "unbound" PASS still supports the fix.
3. With the owner's go-ahead: one real `systemctl suspend`, wake by key, then
   check `journalctl -b -u systemd-suspend.service` and the kernel log.
4. Correct the records above; release 0.2.1-alpha from `main`.
