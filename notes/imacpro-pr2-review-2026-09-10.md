# iMac Pro PR #2: review and integration into test — 2026-09-10

User request: review the iMac Pro pull request targeting main, test compatibility
with test, then merge it into test.

## Inputs and scope

- PR: <https://github.com/MarkPronkin/imac5k-universal-linux-patcher/pull/2>
- Contributor: nicktau; head `ea6acf1e1900e0f2b84e4163bb25822e4287620a`.
- PR base: main, `e64a5266b0bcb5006ee2b33d07d76878a88d7fce`.
- Integration base: test/origin/test, `b936fce` (`v0.1.91-alpha`), clean checkout.
- The actual branch includes the newer systemd MemorySleepMode=s2idle work;
  the earlier handoff's kernel-command-line ownership description is historical.
- Host checked as iMac18,3 / Omarchy, running kernel 7.2.3-arch1-3, s2idle.
  No driver was installed, no compositor reloaded, no boot files changed, and no
  suspend or live GRUB/mkinitcpio test was run. The colour investigation stayed
  shelved.

## Review findings addressed

1. Four merge conflicts: README, patch documentation, the Arch lean patch
   list, and the test-entry cmdline normalisation. Kept all three suspend
   patches and test's existing whitespace normalisation; combined the docs.
2. The PR's global `grep 'bitdepth = 10'` accepted comments, disabled outputs,
   and unrelated monitors. Its global replacement also edited external outputs
   and changed other iMac models. The new check/edit handles active single-line
   internal eDP rules, falling back to the default output rule. It backs up
   changes, rejects unrecognised rules, and runs only for iMacPro1,1.
3. On linux-t2, `imac-alt-entry add/drop/promote t2` addressed the default UKI
   itself. Reserved that name (derived from the actual default path) and the
   separate helper's `5ktest` slot. The default is excluded from orphan repinning.
   Shared UKI derivation preserves package-name validation; the independently
   installed ESP hook validates its own package metadata.
4. Rebased the scheduling patch's context onto the existing resume-arming
   branch. The resume callback and state handling remain intact. Two older
   init hunks had unrelated trailing context that required fuzzy matching on
   7.2.3; narrowed them symmetrically without changing any generated C code.
5. Fedora's lean stack omitted the PR entirely. Both installers now select the
   same default stack in the same order. Fedora also calls the shared 10-bpc
   check/edit and propagates installer failure before editing the monitor file.

The four panel/DCE patches retain their original kernel code: the panel-mode
exception is called only for an Apple tiled slave, the master-first list is
restricted to DCE 12, and the new timing-generator callback belongs to DCE 12.
The post-commit scheduling change also applies to other supported tiled panels.

## Validation

- Baseline `./scripts/check.sh`: 260 tests passed, no skips.
- Final merged `./scripts/check.sh`: **273 tests passed, no skips**; Bash
  syntax, isolated launchers, archive contents, reproducibility, and installer
  lifecycle checks all passed.
- Full lean stack (12 patches), pristine Linux **7.1.13 and 7.2.3**:
  all patches apply with `patch -p1 --batch --forward --fuzz=0`.
- Arch verbose fallback (13 patches), pristine **7.2.3**: all apply at fuzz 0.
  On **7.1.13**, the unchanged base verbose patch needs the Arch installer's
  normal fuzz allowance (2); the full sequence passes with that allowance.
  This is an existing verbose-stack limitation, not an iMac Pro regression.
- Compiled all five affected C translation units with GCC and the prepared
  7.2.3 kernel build's original flags/configuration in a private copy:
  `amdgpu_dm.c`, `dc.c`, `dce120_timing_generator.c`, `dce110_hwseq.c`, and
  `link_edp_panel_control.c`. All passed with no diagnostics. Compared the
  prepared source to the cached suspend-validated build: only the PR's five
  intended patches changed the code.
- Added regressions for 10-bpc output selection, comments, disabled outputs,
  idempotency/backups, preserving other models, invalid kernel metadata,
  linux-t2 default protection, orphan repinning, iMac Pro startup dependency
  gating, Fedora install failure, installer stack parity/order, and release
  archive contents.
- Non-patch files pass `git diff --check`. Checked added kernel-code lines
  separately; unified diff context markers intentionally contain whitespace.

## Limits and artifacts

The contributor reports native 5K on **iMacPro1,1 / Vega 64X / Omarchy /
linux-t2 7.1.8**. This review did not reproduce that hardware test. Vega 56,
iMac Pro suspend, and iMac Pro Fedora/GRUB remain unverified. The combined
driver was not linked into a new module or booted. The verbose fallback still
does not support the iMac Pro.

The delayed-work change postpones a queued check at the end of a modeset; it
does not provide exclusion across an entire in-progress atomic commit. Its
reported timing improvement is not proof that every worker/modeset interleaving
is eliminated. No additional kernel scheduling changes were introduced here.

Compile commands, source diff, and compiler logs are under the ignored
`hardware-private/pr2-build/`. Scratch source/patch logs are under
`/tmp/imac5k-pr2-check/`; the 7.1.13 archive came from kernel.org. All tests
used temporary files and fake boot tools. The initial sandboxed baseline was
blocked only by loopback sockets/user namespaces; the complete baseline and
merged runs used approved execution as the normal user.

Only test is the merge/push destination. PR #2 continues to target main;
this task does not merge or publish a release on main.
