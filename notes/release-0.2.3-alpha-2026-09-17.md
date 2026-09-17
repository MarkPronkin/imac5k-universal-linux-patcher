# Release 0.2.3-alpha from test — 2026-09-17

Request (2026-09-16/17): check whether the suspend module would work on the
iMac Pro, compare it with t2linux's approach to sleep, make it compatible
with T2 sleep so it can be used on the iMac Pro and the 2020 iMacs, then
push to `test` and release 0.2.3 alpha.

## t2linux's approach (as read on 2026-09-16)

- [Wiki, Suspend](https://wiki.t2linux.org/guides/postinstall/): current T2
  kernels use `t2bce`, which suspends and resumes the BCE, VHCI and audio
  stack itself; do not unload it before suspend (it can leave internal
  devices unavailable after resume); remove old unload hooks from the
  apple-bce era. The [state page](https://wiki.t2linux.org/state/) rates
  suspend "partially working", model-dependent. No sleep mode is prescribed
  and nothing is said about the iMac Pro.
- [linux-t2-patches](https://github.com/t2linux/linux-t2-patches):
  `1001-Add-t2bce-driver-stack.patch` (since 2026-07-22; PCI driver
  `t2bce_core` on `106b:1801`) tries a stateful T2 sleep and falls back to
  `SLEEP_NO_STATE`/`RESTORE_NO_STATE` itself.
  `9001-ACPI-x86-Apple-T2-systems-need-early-CPU-offlining.patch` offlines
  secondary CPUs from a PM notifier on any Mac with the T2 bridge, because
  bringing them up in early resume took seconds each; tested on
  MacBookPro15,1/16,2, MacBookAir9,1 and "a 27-inch T2 iMac" (only the iMac
  Pro fits). That bring-up happens only on deep-sleep resume, so that tester
  used deep sleep.
- The maintainer closed a wiki PR pointing to a suspend script suite (#756):
  "No, pls, no more scripts." Community scripts that still `rmmod -f
  apple_bce` (Omarchy discussion #5862) are MacBook/Touch Bar recipes from
  the apple-bce era.

## What changed (`cff8f15`)

On T2 models (`imac_has_t2`: iMacPro1,1, iMac20,1, iMac20,2) the suspend
module, on both backends:

- requires `t2bce_core` bound to the T2 bridge; refuses with apple-bce, no
  driver, or no bridge, before changing anything;
- refuses while a file in `/etc/systemd/system`,
  `/{etc,usr/lib}/systemd/system-sleep` or `/{etc,usr/lib}/elogind/system-sleep`
  both unloads a module (`rmmod`, `modprobe -r…`/`--remove`) and names
  apple-bce or t2bce; it lists them and never deletes them;
- installs no s2idle drop-in, removes a leftover one, and does not require
  systemd 256. This is a judgement call: the S3 reset is the iMac18,3's
  firmware, and linux-t2's T2 resume work is tested on deep sleep. If deep
  resets a T2 iMac too, `suspend_uses_s2idle` is the switch.
- keeps the Thunderbolt hook, the Wi-Fi hook (BCM43602 only, so a no-op on
  the T2 models' BCM4364) and the hibernate masks. The XHC1 fix stays
  iMac18,3-only.

Detection reports `applied` only while the T2 rules hold. Other models are
unchanged; on this iMac18,3, `--status` still shows suspend applied.

## Checks

- `IMAC5K_REQUIRE_STARTUP_TESTS=1 IMAC5K_REQUIRE_T2_AUDIO_TESTS=1
  scripts/check.sh`: 451 tests, OK. New `T2SuspendTests` run both backends
  against a fake PCI tree and fake hook directories; disabling the T2 gate
  (22 failures) or the `modprobe -rv` match (2 failures) is caught.
- `git diff --check`: clean.

Not done: nothing is tested on a T2 iMac. Unknowns there: whether deep sleep
resumes, whether the Thunderbolt hook is needed, whether the PCH xHCI has
the iMac18,3's second-sleep reset.

## Publication

- `v0.2.3-alpha` is annotated by MarkPronkin and points at `3fde421`
  (`cff8f15` change, then this record); `test` was fast-forwarded from
  `c1086d2`. `main` was not touched.
- Two builds from the tag in fresh clones were identical:
  `29aa803f6275f4baf6a8d8f1dedb8db5ae9af4bb0b6a68d9b7e06c5ddedc778b`,
  276513 bytes, `VERSION` 0.2.3-alpha, `COMMIT` `3fde421`; no notes, tests
  or workflow files inside.
- Published at 17:05 UTC with `gh release create` as MarkPronkin; the API
  lists MarkPronkin as author and uploader of both assets; target `test`,
  pre-release. Verification run 35250571100 passed (checks, isolated
  startup tests, rebuild and byte comparison).
- `install.sh --version v0.2.3-alpha` into a scratch HOME verified the
  checksum and installed 0.2.3-alpha.
- The notes point iMac Pro testers to #1 and #3. #3 (the suspend thread) also
  holds PandaWood's intermittent amdgpu divide-error report; in it the owner
  said s2idle is enough on a desktop. This release keeps the kernel's mode
  on T2 models only, following t2linux; revisit if the owner prefers s2idle
  there too.

## Open items

Those of [0.2.2-alpha](release-0.2.2-alpha-2026-09-16.md#open-items) still
stand. Add: repeated suspend/wake on an iMac Pro with `linux-t2` (t2bce);
the README lists audio on iMac20,1/20,2 as "Unsupported", probably "N/A: T2
audio".
