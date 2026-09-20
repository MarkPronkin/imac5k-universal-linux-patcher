# Current work checkpoint

**macOS mode ported (2026-09-21):** on `test`, a new `macos` module brings
ahmadtv/omarchy-imac18-3's `set_os` work here — the Intel HD 630 exposed
headless as the default video GPU, and a backlight that actually dims, over
the panel's full range. Gated to iMac18,3 + Omarchy/Limine
(`imac_macos_mode_supported`); `iMacPro1,1` is a permanent N/A, its Xeon W has
no iGPU. Changed from upstream: the kernel parameters go in a
`limine-entry-tool.d` drop-in that appends with `+=` (upstream's in-place edit
of `/etc/default/limine` matches nothing on this machine's `+=` line), the
ACPI brightness table is only installed after `iasl` round-trips every
definition in the firmware's own table, and what is installed must differ from
it by nothing but ABCL and the OEM revision; a missing or unverifiable table
degrades to the firmware's 80 levels instead of failing. 47 offline tests in
`tests/test_macos.py`; 501 pass overall.

**Confirmed on the hardware the same day** (iMac18,3, 7.2.5-3-omarchy): the
HD 630 comes up with i915 bound and no connectors, Quick Sync is `renderD128`
(H.264 incl. low-power, HEVC Main10, encode and decode), the Radeon keeps
`boot_vga` and Hyprland holds only its nodes, audio is unaffected, the panel
**dims by eye for the first time on this machine**, and the NVRAM level is
written at shutdown. Two bugs found by that boot and fixed: the table builder
picked the DSDT because it searched every table for the string `PEG0GFX0`
(it is the OEM table ID, matched in the header now), and its byte-equality
round-trip check could never pass because iasl encodes the disassembler's
External declarations into the AML — it compares definitions now.

**Sleep is the one thing still untested**, and macOS mode has never been
combined with working suspend anywhere: upstream masks sleep and names i915
as a suspect. Full write-up: [docs/macos-mode.md](docs/macos-mode.md).

**Release 0.2.3-alpha (2026-09-17):** from `test`. The suspend module follows
t2linux on T2 iMacs (iMac Pro, 2020 iMacs): it requires linux-t2's `t2bce`,
refuses while anything unloads the T2 driver around sleep, and keeps the
kernel's sleep mode instead of forcing s2idle (`cff8f15`). Not tested on T2
hardware. See [the release record](notes/release-0.2.3-alpha-2026-09-17.md).

**Release 0.2.2-alpha (2026-09-16):** a fix release from `test`. Linux 7.2.4
added an Apple Studio Display quirk where both 5K core patches anchored, so
the 5K build stopped on a fresh Omarchy install with `7.2.5-3-omarchy`. Both
core patches are re-anchored (`42408b4`); nothing else changed since
0.2.1-alpha. See [the release record](notes/release-0.2.2-alpha-2026-09-16.md).
The patched module is compile-tested on 7.2.5 but not yet booted there.

**Release 0.2.1-alpha (2026-09-16):** the work that sat uncommitted on the
local review branch is on `test` as topic commits (XHC1 fix, second-sleep
investigation record, full-audit fixes, `t2speakers`), the review branch is
deleted, and `v0.2.1-alpha` is released from `test`, published from the
owner's GitHub account (MarkPronkin). The release workflow no longer
publishes; it verifies the published archive against a rebuild from the tag.
`main` is unchanged (local `7e379ad`, `origin/main` `da90c1b`). Read
[the release record](notes/release-0.2.1-alpha-2026-09-16.md) first: what
went to `test`, how the release is built and credited, and the open items.
Suspend on the iMac18,3 works repeatedly with the XHC1 fix; the newest
sections of [the Wi-Fi suspend handoff](notes/wifi-suspend-handoff-2026-09-11.md)
have the evidence and [notes/s3-sleep.md](notes/s3-sleep.md) parks deep S3.
The resume checkpoints below (2026-09-12 to 2026-09-14) are superseded.

**Resume checkpoint (2026-09-14, 17:54):** EFI recorder's **awake storage
selftest passed**, logs `/var/tmp/imac-efi-sleep-jha88qad`: exact data
read-back, nonvolatile/runtime attributes, deletion confirmed by EFI_NOT_FOUND,
module unloaded, no sleeps (0/0) on boot 438e5fbc. Earlier checks failed because
Apple adds its data-checksum attribute 0x80000000. Verifier now accepts only
7 or 0x80000007 and still checks exact data; recovery preserves raw attributes.
Also made the sysfs selftest write unbuffered to avoid retry on failed close.
Twenty-three offline helper tests and the W=1 module build pass.

The installer USB reappeared after reboot; it was safely unmounted and
powered off again. Next command, prepared for launch:
`sudo python3 notes/second-sleep-efi-capture.py run --tb-removed`.
This repeats the latest failing test (real first s2idle, then five-second
platform, serial, Wi-Fi detached, whole Thunderbolt subtree removed) with
PM tracing and a 20-second second-transition EFI snapshot timer. Wake first
sleep with keyboard after ~30 s; leave the second staged attempt alone.
Snapshot execution and retention through the fault remain unproven.
**After a reset, run `sudo python3 notes/second-sleep-efi-capture.py collect`
and `sudo python3 notes/second-sleep-trace.py capture` BEFORE clearing,
starting another recorder or any sleep.** Check new `/var/tmp/imac-efi-sleep-*`
and `/var/tmp/imac-second-sleep-*` directories. Do not overwrite EFI records;
the loader refuses existing ones. Trace/nonvs boot drop-ins remain.

**Resume checkpoint (2026-09-14, 17:44):** whole-Thunderbolt removal also
failed. Owner authenticated the pending test; run
`/var/tmp/imac-second-sleep-ybtw83d_` on boot b118d60b removed all seven
Alpine Ridge PCI functions, and the helper checked the subtree was still
absent before each cycle. First real s2idle returned (73.09 s asleep);
second `platform`, delay 5, serial, Wi-Fi detached began 17:37:44 and reset.
No second result or cleanup exists. This rules out the removed functions'
Linux PM callbacks for this reproducer; the root port, hardware and ACPI
namespace were not physically removed. Current boot
`438e5fbc-e398-4aae-ba13-e5ccc7012a8f` has counters 0/0, pm_test=none,
pm_async=1, mem_sleep=deep. Captured before any new recording or sleep:
`/var/tmp/imac-sleep-trace-capture-mcx8xmbe` (empty; this last test did not
enable tracing). The boot again reported a ring-buffer magic mismatch.
The old pkexec process/session 18988 is gone. Next: awake validation of
`notes/second-sleep-efi-capture.py selftest`; the built module has not yet
been loaded. Do not assume EFI snapshot capture works until hardware checks
complete. Trace/nonvs boot drop-ins remain. Sleep is unresolved.

**Resume checkpoint (2026-09-14, 16:09):** continuing the owner's midday
request to remove the **whole Alpine Ridge PCI subtree**, not merely unbind
the NHI driver. Current boot `b118d60b-7117-4d38-ac19-a83fa1cfe784` still has
no sleeps (0/0). The mounted Omarchy installer stick on Alpine Ridge USB 4-1
was safely unmounted (`udisksctl unmount -b /dev/sdb1`) and powered off
(`udisksctl power-off -b /dev/sdb`); verified no attached USB/net/block
devices below Thunderbolt and /sys/class/block/sdb absent. It remains
physically plugged in and may re-enumerate when the controller is rescanned.
Launched via pkexec at 16:10, but **still awaiting Polkit authentication at
16:17**: no new run directory and counters remain 0/0. Pending command is
`sudo python3 notes/second-sleep-pm-test.py platform --prime
--mode s2idle --delay 5 --wifi-unbound --serial --tb-removed` (pkexec session
18988, host PID 34174). Do not launch a duplicate while this is pending.
Wake the first
real sleep after ~30 s; leave the staged second attempt alone. Check the
new `/var/tmp/imac-second-sleep-*` run and thunderbolt.json after return/reset.
The earlier recorded attempt did reset: its capture qvgi5j9m was empty and
the new kernel reported a ring-buffer magic mismatch. The trace/nonvs boot
drop-ins remain. An alternative EFI snapshot helper was built under
notes/pm-capture, but **has never been loaded or hardware-tested**; no EFI
variables were written by it. Twenty-two offline helper checks pass.

**Resume checkpoint (2026-09-14, 10:01):** persistent trace retention
**passed a normal restart**. Capture `/var/tmp/imac-sleep-trace-capture-v2jpeiun`
on boot `720291d7-38d9-44a0-bc3f-cec648746109` recovered the exact marker from
boot `5352621b`; verification `/var/tmp/imac-sleep-trace-verified.json`.
Counters remain 0/0 before the next experiment. Prepared and about to launch
`sudo python3 notes/recorded-second-sleep.py`: starts the validated recorder,
then `platform --prime --mode s2idle --delay 5 --wifi-unbound --serial
--persistent-trace`. Wake the first real sleep after ~30 s; leave the second
platform test alone. The helper now requires active PM trace events, marks
each attempt, and saves the first wake's trace before the second attempt.
Sixteen offline checks pass. **After any reset, run
`sudo python3 notes/second-sleep-trace.py capture` BEFORE mark/start or
another sleep.** Check `/var/tmp/imac-second-sleep-*` for the new run.
Normal-reboot retention does not guarantee retention through the fault.

**Resume checkpoint (2026-09-14, 09:55):** recorder activated successfully
after a normal restart, on boot `5352621b-703b-49c2-932c-444ae95ae261`.
The kernel mapped `imac_sleep` at physical 0x800000000, size 16 MiB.
`notes/second-sleep-trace.py mark` completed: marker written/read back,
tracing paused; metadata `/var/tmp/imac-sleep-trace-marker.json`, initial
capture `/var/tmp/imac-sleep-trace-capture-k0jg399f`. No sleeps (0/0),
pm_test=none, pm_async=1, mem_sleep=deep. **Next: one more normal restart,
then `sudo python3 notes/second-sleep-trace.py capture` BEFORE mark/start
or any sleep.** It must find the marker from boot `5352621b`; otherwise
retention is unproven and another sleep test would not yet have a validated
recorder. The nonvs and trace boot drop-ins remain installed. Read the newest
Wi-Fi suspend handoff section for the follow-up sequence.

**Resume checkpoint (2026-09-14, 09:50):** sequential device
callbacks did not fix the second attempt either. Run
`/var/tmp/imac-second-sleep-aiqewubm` used `platform --prime --mode s2idle
--delay 5 --wifi-unbound --serial`: first real sleep returned (67.25 s
asleep); the second platform test reset. Current boot `17f13188` has
counters 0/0, pm_test=none, pm_async=1, mem_sleep=deep; nonvs remains.
Persistent ftrace recorder **is now armed for the next boot**, through
`/etc/limine-entry-tool.d/zz-imac-sleep-trace.conf`. The boot image was
rebuilt and its embedded arguments/kernel verified. Boot backups and setup
record: `/var/tmp/imac-sleep-trace-setup-7vu55vlk`. No restart or sleep has
occurred since installing it. **Next: normal restart, then run
`sudo python3 notes/second-sleep-trace.py mark` before any sleep.** A second
normal restart and `capture` must prove marker retention before another sleep
experiment. The helper's start/capture/disarm commands and exact workflow
are in the latest Wi-Fi suspend handoff section. Fifteen offline checks pass.

**Resume checkpoint (2026-09-14, 09:30):** the five-second platform test
with Wi-Fi detached throughout also reset on its second attempt, after a
successful real first sleep (`/var/tmp/imac-second-sleep-q2btp_79`). This
avoided the separate Wi-Fi rebind crash. It did not prove whether late/noirq
suspend or resume failed. Current boot `68b17b26` has had no sleeps (0/0),
pm_test=none, pm_async=1, mem_sleep=deep, nonvs still on the boot cmdline.
Next prepared test adds only sequential callbacks:
`sudo python3 notes/second-sleep-pm-test.py platform --prime --mode s2idle
--delay 5 --wifi-unbound --serial`. Wake the real first sleep after ~30 s;
the staged second returns automatically. The helper restores pm_async.
Thunderbolt firmware disassembly is available under `/tmp/imac-acpi-analysis`;
stateful device power methods are candidates, not a confirmed cause. Read the
latest Wi-Fi suspend handoff section for the exact evidence and commands.

**Latest finding (2026-09-12, 13:19):** the short platform run never reached
the kernel test. After a successful first sleep, immediate Wi-Fi re-unbind
raced its asynchronous probe: `!work->func` in
`brcmf_bus_cancel_reset_work → brcmf_pcie_remove`, then a NULL-pointer BUG;
the login screen was frozen by systemd's pre-sleep user.slice freeze.
Evidence: `notes/wifi-rebind-oops-2026-09-12.log` and
`/var/tmp/imac-second-sleep-yexih9qd`. Current boot `3f29be64`, counters 0/0.
Next prepared run adds `--wifi-unbound` to keep the unused card detached
throughout: `sudo python3 notes/second-sleep-pm-test.py platform --prime
--mode s2idle --delay 5 --wifi-unbound`. The helper now also waits for Wi-Fi
initialization before any detach; 11 offline tests pass. The 70-second
platform failure remains a separate unresolved result. Read the latest
Wi-Fi suspend handoff section before proceeding.

**Latest result (2026-09-12, 13:06):** the 70-second `pm_test=platform`
attempt reset the machine too (`/var/tmp/imac-second-sleep-lwmth335`), after
the same boot's successful real first sleep and 70-second devices test.
This reproduces failure before actual s2idle, narrowing the added work to
device late/noirq + ACPI s2idle preparation, or time spent in that state.
Fresh boot is `b6a8dc5d`, counters 0/0, temporary settings cleared; S3/nonvs
boot configuration remains. Next:
`sudo python3 notes/second-sleep-pm-test.py platform --prime --mode s2idle --delay 5`
to distinguish a callback hang from failure during the longer hold. Wake
the real first sleep after ~30 s; the staged second returns automatically.

**Latest test (2026-09-12, 13:01):** one real s2idle sleep followed by
`pm_test=devices` for 70 s both returned on boot `830cfc6e`; the second was
a simulated device test, not real sleep. Raw dmesg confirms a 71.66 s test
interval, so the keyboard did not shorten it. Logs:
`/var/tmp/imac-second-sleep-g7942jah`. Fixed the diagnostic's wait for a
systemd service that has already been unloaded; restored all its temporary
settings. Next: `sudo python3 notes/second-sleep-pm-test.py platform
--after-first --mode s2idle` in the same boot (70 s, automatic return).
Read the newest section of the Wi-Fi suspend handoff below.

**Current investigation (2026-09-12, 12:49):** the failure still occurs on the
second attempt, but its last `PM: suspend entry` log line is emitted *before*
device suspend; it does not prove the machine reached sleep. Shared driver
callbacks remain candidates. Also, the first S3+nonvs wake restored the
desktop but lost Thunderbolt/its USB controller and failed the NHI rebind;
S3 is not yet a shipping choice. `Darwin` OSI is already enabled by Linux on
this Mac, so adding that boot option would do nothing. Prepared and
offline-checked `notes/second-sleep-pm-test.py`: on the current fresh boot,
`sudo python3 notes/second-sleep-pm-test.py devices --prime --mode s2idle`
takes one real first sleep (wake after ~30 s), then a 70-second device-stage
test that returns automatically if it survives. It preserves logs under
`/var/tmp/imac-second-sleep-*` across a reset and restores temporary settings
after completion. Hardware test pending. Read the newest section of
[the Wi-Fi suspend handoff](notes/wifi-suspend-handoff-2026-09-11.md) first.

**Previous stopping point (2026-09-12, 12:30; qualifications above):** on this iMac the first sleep of
a boot always survives and the second always resets the machine at about 50 s —
seven boots, no exceptions. This holds in **both** s2idle and deep S3, so it is
independent of the sleep mode. Ruled out: the watchdogs, panic-reboot, MCE, the
RTC alarm, sleep duration, every CPU idle depth including a C3 cap (an earlier
"deepest C-states" conclusion here was wrong, an artefact of test ordering),
this project's own hooks and the bound state of the Thunderbolt NHI and Wi-Fi
card, applesmc, and a shotgun unload of thunderbolt/brcmfmac/mei/i2c_i801. New
result: **one deep S3+`acpi_sleep=nonvs` sleep returned** (2 min 54 s in S3,
where S3 previously reset on wake), but Thunderbolt/USB recovery failed as
noted above. The machine
may still be armed for that test; `sudo bash notes/s3-nonvs-test.sh disarm` plus
a reboot reverts it. **The Wi-Fi hook (65c2d88) stays unpushed** and nothing
about suspend ships until suspend is dependable; 0.2.0-alpha unmasks suspend for
every Retina 5K iMac and must be re-gated in 0.2.1-alpha. Read
[the Wi-Fi suspend handoff](notes/wifi-suspend-handoff-2026-09-11.md) first;
its newest section is at the top.

**Release 0.2.0-alpha (2026-09-11):** `test` (`b4b0a61`, PR #2 included) was
fast-forwarded into `main`, reviewed and released from `main` as
`v0.2.0-alpha`. Read [the release record](notes/release-0.2.0-alpha-2026-09-11.md)
first: it lists the review fixes, the validation, the open follow-ups, and two
corrections to the stopping point below — suspend now selects s2idle through
the systemd drop-in `configs/imac5k-s2idle.conf` (the kernel-cmdline default
and the immediate sysfs switch are gone, and this machine's cmdline no longer
carries `mem_sleep_default`), and both suspend attempts after the 0.1.92-alpha
driver build were aborted by brcmfmac (Wi-Fi) failing to enter D3.

The iMac Pro PR #2 review is recorded in
[the PR review](notes/imacpro-pr2-review-2026-09-10.md). It includes the reviewed
commit, compatibility fixes, offline/compile validation, and hardware limits.
It reached `main` with the 0.2.0-alpha merge.

When resuming the GRUB-on-Arch work, read
[the GRUB handoff](notes/grub-arch-handoff-2026-09-09.md). It records the user's
request and scope decisions, exact changes, validation, the "don't test GRUB on
this machine" constraint, unrelated working-tree changes, and the stopping
point. Check current Git and machine state against that dated record before
continuing.

When resuming the headphone/audio work, read
[the 2026-09-09 handoff](notes/headphones-handoff-2026-09-09.md). It records the
user's request, exact changes, validation, temporary artifacts, unrelated
working-tree changes, and the stopping point. Check current Git and machine
state against that dated record before continuing.

When resuming the sleep/suspend work, read
[the suspend handoff](notes/suspend-handoff-2026-09-10.md). It records the
root cause (Thunderbolt NHI noirq suspend hangs the kernel; proven in both
directions), the evidence chain (pm_test ladder, why pm_trace is useless on
this firmware, S3 enters but wake resets the machine), the
`scripts/imac-tb-sleep-hook` fix wired into the patcher, and its validation.
The 2026-09-10 resume checkpoint at the top of [TODO.md](TODO.md) carries the
full investigation log. Treat `notes/standby-handoff-2026-09-10.md` as stale:
its standby changes were discarded. Check current Git and machine state
against that dated record before continuing.

**Stopping point of 2026-09-10 (evening), superseded above:** suspend works — the
Thunderbolt sleep hook is installed and a systemd s2idle cycle passed
17:13:35→17:13:54 with unbind/rebind in the journal; `mem_sleep_default=s2idle`
is on the kernel cmdline via `/etc/default/limine`. The suspend module now
also owns that default on all three backends (apply/detect/remove + tests,
`check.sh` green). A review pass the same evening made boot-config failures
fail the module on every backend, has apply switch the running kernel to
s2idle at once, and brought README/DEPENDENCIES/docs up to date; the branch
is pushed to `origin/test`. Deep S3 still resets on wake (firmware), hibernate
stays out of scope per the owner. Details:
[the suspend handoff](notes/suspend-handoff-2026-09-10.md). Before that,
release 9.9.11-test was built (`dist/`): the three suspend patches are wired
into both installers (`patch-imac5k-amdgpu.sh` lean + verbose,
`fedora-imac5k` lean) and committed, as is the audio-after-resume
chain-restart fix. The colour regression investigation is **shelved by the
owner** pending more testing — see
[the colour/audio handoff](notes/colour-audio-handoff-2026-09-10.md).
TODO.md, AGENTS.md and the notes/ handoffs are committed with the work as
checkpoints.
