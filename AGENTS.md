# Current work checkpoint

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

**Latest stopping point (2026-09-10, evening):** suspend works — the
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
