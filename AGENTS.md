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

When resuming the sleep/suspend work, read the 2026-09-10 resume checkpoint at
the top of [TODO.md](TODO.md). It records the stitch-layer BUG that froze the
staged suspend test, the candidate `patches/5k-logical-modeset-guard.patch`
and its built test module, and the next steps. Treat
`notes/standby-handoff-2026-09-10.md` as stale: its standby changes were
discarded. Check current Git and machine state against that dated record
before continuing.

**Latest stopping point (2026-09-10, evening):** release 9.9.11-test is built
(`dist/`). The three suspend patches are wired into both installers
(`patch-imac5k-amdgpu.sh` lean + verbose, `fedora-imac5k` lean) and committed,
as is the audio-after-resume chain-restart fix. Before that, read
[the colour/audio handoff](notes/colour-audio-handoff-2026-09-10.md). It
covers the `5K-resume-linkarm` test boot and its `devices` PASS, the
audio-after-resume fix (a real resume with it is still untested), and the
colour regression investigation, **shelved by the owner** pending more
testing. TODO.md, AGENTS.md and the notes/ handoffs are left uncommitted by
convention of the running sessions.
