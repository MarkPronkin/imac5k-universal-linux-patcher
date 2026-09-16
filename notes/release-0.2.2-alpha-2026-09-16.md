# Release 0.2.2-alpha from test — 2026-09-16

User report (2026-09-16): with 0.2.1-alpha on a fresh Omarchy install
(kernel `7.2.5-3-omarchy`), `--apply 5k` stopped with "iMac 5K patch stack
did not apply cleanly to 7.2.5 source". Request: fix it, push to `test`, and
release 0.2.2 alpha.

## Cause and fix

Linux 7.2.4 added an Apple Studio Display case (`APP` AE3A/AE42/AE46, setting
`disable_second_tile`) just before `default:` in `apply_edid_quirks()`
(`amdgpu_dm_helpers.c`). Both core patches inserted the iMac panel IDs at that
spot, so their context no longer matched at `--fuzz=0`. The ID sets do not
overlap; it was a context-only conflict. 7.2.4 already had the change, so
0.2.1-alpha could not build 5K on 7.2.4 either.

`42408b4` re-anchors both core patches:

- `imac5k-lean-core-7.2.x.patch`: the same case block now goes ahead of the
  PHY SSC case, where 7.1.9 through 7.2.5 are identical.
- `imac5k-amdgpu-7.2.2.patch` (verbose fallback): its hunk also rewrote
  `default:` to log unmatched Apple panels, so moving it was not enough. The
  iMac cases and that log now sit in their own switch just before the stock
  one; the matched case returns (the function ends after the stock switch,
  so this equals the old `break`). The only visible difference: a Studio
  Display now also gets the "Apple panel not matched" info line.

## Checks

- Both full stacks (lean with the iMac Pro follow-ups, verbose with its
  increments) apply in order at `--fuzz=0` to pristine 7.2.5 from the cached
  kernel.org tarball.
- `amdgpu.ko` built for both stacks against the installed `7.2.5-3-omarchy`
  headers (GCC 16.2.1); vermagic matches the running kernel. The only warning
  is a pre-existing unused `aconnector` in the verbose core.
- The changed `amdgpu_dm_helpers.c` hunks apply to stable 7.2.2, 7.2.3 and
  7.2.4; the lean ones also to 7.1.9 and 7.1.13. The verbose core already
  failed on 7.1 before this change (another hunk), as documented.
- `IMAC5K_REQUIRE_STARTUP_TESTS=1 IMAC5K_REQUIRE_T2_AUDIO_TESTS=1
  scripts/check.sh`: 444 tests, OK.
- `git diff --check` flags only unchanged context lines inside the `.patch`
  files (a space before a tab), which are part of the diff format.

Not done: the patched module has not been installed or booted on 7.2.5.

## Open items

Those of [0.2.1-alpha](release-0.2.1-alpha-2026-09-16.md#open-items) still
stand. Add: boot the 0.2.2-alpha 5K module on `7.2.5-3-omarchy`.
