# Deep S3 sleep on the iMac18,3 — pinned (2026-09-15)

Status: **not working, parked on purpose.** Suspend ships as s2idle. This note
collects everything learned about deep S3 (`mem_sleep=deep`), so the work can
resume without re-deriving it. Main record of the sleep investigation:
`notes/wifi-suspend-handoff-2026-09-11.md` (newest first).

## Where S3 stands

| Date | Setup | Result |
|---|---|---|
| 2026-09-10 | deep, Thunderbolt NHI bound | `systemctl suspend` hung at `PM: suspend entry (deep)`; pm_test ladder: freezer PASS, devices PASS, **platform HANG** (the Thunderbolt NHI noirq callback, fixed since by `imac-tb-sleep-hook`) |
| 2026-09-10 | deep, NHI unbound, pm_test | processors PASS; **core HANG once, PASS on a fresh boot** (flaky, unresolved; delta over processors is `arch_suspend_disable_irqs()` + `syscore_suspend()`) |
| 2026-09-10 | real deep, NHI unbound, no `acpi_sleep=nonvs` | **S3 entered** (screen and fans off); keypress → **reset on wake**; no pstore record |
| 2026-09-12 12:24 | real deep, `acpi_sleep=nonvs`, hooks | **first S3 of the boot slept 2 min 54 s and woke** ("Low-level resume complete", desktop back), but Thunderbolt broke: bridges 05:00.0, 06:00.0/01.0/02.0/04.0 inaccessible, xHCI 08:00.0 removed with a `pci_disable_device` warning in pciehp removal, NHI rebind `timeout resetting host router` (-22). Boot 0dd66c29 |
| 2026-09-12 12:27 | same boot, second deep | **reset** (started 12:27:38.9, next kernel 12:28:49) |
| 2026-09-15 17:15 | real deep, `nonvs`, hooks, **XHC1 fix loaded**, after 7 good s2idle sleeps in the same boot (2601811c) | **reset**. Journal ends at `Performing sleep operation 'suspend'` 17:15:21.37; next kernel read the RTC at 17:16:31. Run dir `/var/tmp/imac-xhci-d0-pachgoy6` (context only, no cycle result) |

The 70 s from the last journal line to the next kernel matches the s2idle
crashes that died within seconds of suspend entry (73–80 s each; a crash reset's
POST is far longer than the ~20 s of a normal reboot). So the 2026-09-15 S3 most
likely died **during S3 entry**, not on wake. Not confirmed: the owner reported
only "reboots", not whether the screen and fans went off first or whether a key
was pressed.

## What is known to differ between S3 and the (now working) s2idle

s2idle never runs `suspend_ops` (`_TTS`/`_PTS`/`_WAK`), keeps CPUs online and
the platform powered. S3 adds, in order:

- **`acpi_suspend_begin`**: `_TTS(3)` sets `SLTP=3` (used by `XHC1._PS3/_PS0`,
  now skipped by the fix).
- **`acpi_pm_prepare` → `_PTS(3)`** (DSDT): `P8XH(0, 3)` port 80,
  `\_SB.SGOV(0x0105000E, 0)` (GPP_F14, the BCM57766 Ethernet/SD power line
  that `RP02.C4PD/C4PU` also drive), `\_SB.PCI0.LPCB.EC.ECSS = 3` (tells the
  SMC/EC the system is entering S3); non-Darwin branches not taken
  (`OSDW` true).
- **Device callbacks take S3 paths**, never exercised by s2idle:
  - `amdgpu_pmops_suspend_noirq` calls **`amdgpu_asic_reset`** for S3
    (`amdgpu_acpi_should_gpu_reset` is false only for s2idle). This is the
    patched 5K amdgpu. It survived the 2026-09-12 first S3.
  - **NVMe** does a full shutdown (`pm_suspend_via_firmware`), so the PCI core
    puts 02:00.0 and root port 00:1b.0 into D3 → **`RP17._PS3`**: if
    `NVME != 1` (GNVS, value unread) `PSTA=3` then **`LDIS=1` (link disable)**
    on the boot SSD's root port; `_PS0` re-trains and waits up to 10 s for
    `LACT` and `SSD0.CLAS`. In s2idle NVMe stays D0 and this never runs.
  - PCI target states come from `_S3D`/`_S3W` (none in Apple's tables) and
    power resources (none).
- **`pm_sleep_disable_secondary_cpus`, `syscore_suspend`, then
  `acpi_suspend_enter`** → firmware S3 (SLP_TYP 5 from Apple's dedicated
  SSDT "SsdtS3", which contains only `_S3_ = {5, 5, 0}`; `_S4 = {6,6}`,
  `_S5 = {7,7}` in the DSDT). Resume vector and wake are firmware territory.
- **`acpi_sleep=nonvs`** is required for any S3 wake here (without it every wake
  reset). Its "saved/restored NVS" log lines are unconditional and do not show
  that it was ignored.
- **`_WAK(3)`**: `P8XH(0,0)`, `EC.ECSS = 0`, `SBUS.BUS0.BLC0.BCAL()` (backlight
  controller over SMBus), `PWRS = EC.EACP`, `PNOT()`.

## Not the cause (carried over from s2idle work, still valid for S3)

`XHC1._PS3` (reset on its second D3 entry) is kept off by
`modules/imac5k-xhci-d0` and was loaded for the 2026-09-15 S3 attempt, so S3
has at least one further problem. Earlier eliminations for the *second-sleep*
reset (C-states, Wi-Fi/Thunderbolt binding, applesmc, mei, i2c_i801, timing)
were all s2idle-side and say nothing new about S3.

## Tools ready for S3 work

- **Fix module:** `make -C modules/imac5k-xhci-d0`, `sudo insmod
  modules/imac5k-xhci-d0/imac5k_xhci_d0.ko` (every boot; `acpi_pm_skipped=Y`).
- **Repeat-sleep validation:** `sudo python3 notes/xhci-d0-sleep-test.py --mode deep
  [--cycles N]` (needs `acpi_sleep=nonvs`; requires an S3 resume line; keyboard
  wake and Thunderbolt return are warnings in deep mode). It loads the fix.
- **Staged tests:** `sudo python3 notes/second-sleep-pm-test.py <stage> --prime|--after-first
  --mode deep [--delay N] [--wifi-unbound] [--serial] [--tb-removed]`, stages
  freezer/devices/platform/processors/core (processors/core hold at most 5 s).
- **RTC breadcrumbs:** `notes/pm-crumb/imac_pm_crumb.c` +
  `notes/second-sleep-crumb.py run/collect`. Records the last PM callback/phase
  in the RTC date, the last ACPI method hash and ACPI event count in alarm
  bytes 0x03/0x05, and a heartbeat in 0x01, and logs every ACPI method and
  operation-region access of completed cycles. It already knows the S3-only
  phases (`acpi_suspend`, `CPU_OFF`/`CPU_ON`), but **`run` hardcodes s2idle and
  the platform stage**: add `--mode deep` and a stage option before using it
  for S3. While loaded the kernel cannot time sleep from the RTC (expect the
  clock to fall behind).
- **Caveats for RTC evidence:** a spontaneous reset keeps the RTC (proven), but
  Apple's POST **wipes the RTC after a manual power cycle** (2026-09-10: it read
  2024-01-01 00:00:16). Let the machine reset on its own; do not hold the power
  button, or the breadcrumb is gone. The persistent ftrace buffer does not
  survive these resets; EFI variables do, but a 20 s worker never got to write.
- **ACPI tables:** raw copies in every `/var/tmp/imac-second-sleep-*/acpi-tables`.
  Decompile with ACPICA (`make iasl` from github.com/acpica/acpica), using
  `iasl -e SSDT*.dat -d DSDT.dat` and `iasl -e DSDT.dat -d SSDTn.dat` (without
  `-e` the externals resolve wrongly). Do not commit Apple's tables.

## Suggested order when resuming

1. **Entry or wake?** On a fresh boot with the fix loaded, run one deep sleep as
   the first sleep of the boot (the 2026-09-12 first S3 woke; the 2026-09-15 one
   followed seven s2idle sleeps). Watch whether the screen and fans go off and
   stay off until a key, and note the time of the reset.
2. **Stage it** with the fix loaded and Thunderbolt removed
   (`second-sleep-pm-test.py ... --mode deep --tb-removed --wifi-unbound --serial`):
   devices → platform → processors → core. Platform adds `_TTS`, `_PTS`, the S3
   late/noirq callbacks (amdgpu ASIC reset, NVMe/`RP17._PS3`); processors adds
   CPU offlining; core adds syscore. A reset before `core` keeps it in Linux.
3. **Breadcrumbs in deep mode** on the first failing stage, to name the callback
   or AML access, the same way `XHC1._PS3` was found for s2idle.
4. **Isolate the S3-only device paths** if a callback is named: NVMe/`RP17`
   (e.g. keep the SSD out of D3, like the xHCI fix), amdgpu's S3 ASIC reset,
   `_PTS` GPIO/EC writes, the Thunderbolt power sequencing that broke on the
   first S3 wake.
5. **If Linux reaches `acpi_suspend_enter`** and it still resets, the failure is
   in firmware S3 entry or wake; compare against macOS (the NVRAM still holds
   OpenCore Legacy Patcher boot-args, so macOS sleep behavior on this machine may
   also be informative).

## Machine state to undo later

- `acpi_sleep=nonvs` is still on the command line
  (`/etc/limine-entry-tool.d/zz-imac-s3-test.conf`) and the suspend module's
  `/etc/systemd/sleep.conf.d/imac5k-s2idle.conf` is parked as
  `…parked-by-s3-test`. **While this is armed, a normal menu suspend uses deep
  S3 and resets the machine.** `sudo bash notes/s3-nonvs-test.sh disarm`
  restores both and rebuilds; then reboot. Re-arm with `arm` for S3 work.
- The persistent-trace reservation (`zz-imac-sleep-trace.conf`: `memmap=16M$…`,
  `trace_instance=…`) is still armed; `sudo python3 notes/second-sleep-trace.py disarm`.
- The XHC1 fix is not loaded at boot yet (not integrated into the patcher), so
  even in s2idle the second sleep of a boot resets until it is loaded.
