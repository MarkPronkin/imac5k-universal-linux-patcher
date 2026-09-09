# Handoff: GRUB support for Arch-based distros — 2026-09-09

## Latest checkpoint — resumed work completed on 2026-09-09

This section supersedes the unfinished-work list in the earlier checkpoint
below. The requested repository implementation, regression tests and docs are
complete. Hardware boot validation remains for the target GRUB installation;
do not run GRUB/mkinitcpio against this Omarchy/Limine host.

### Current machine and checkout

- Still `main`, HEAD `a92b9a1`, with no new commits or pushes.
- Host: Omarchy 4.0.3, `ID_LIKE=arch`, kernel `7.2.3-arch1-3`.
- `/etc/default/limine` exists; `/etc/default/grub`, `/boot/grub`, and
  `/etc/grub.d` remain absent. No host boot configuration was changed.
- The pre-existing `AGENTS.md` modification and four deleted issue-reply
  notes were left untouched.
- New GRUB libraries, guide and tests are staged so release tests can include
  the runtime additions. Existing tracked-file edits remain uncommitted.
  This handoff is still an untracked development note.

### Completed since the earlier checkpoint

- GRUB argument edits preserve single/double quotes, existing options,
  indentation and comments, and honor the final assignment. Computed or
  multiline command lines fail without executing/replacing them. Failed
  regeneration restores previous files, including symlinked config contents
  and disabled custom-file permissions. Timestamped `40_custom` backups are
  non-executable so they cannot regenerate obsolete entries.
- Test entries select the running kernel's pkgbase, including nested entries
  and multiple installed kernels. They retain GRUB's own initramfs directory
  (separate `/boot`, normal root or btrfs), use unique IDs, omit `savedefault`,
  preserve microcode and replace only their own complete marker blocks.
- Initramfs extraction uses `lsinitcpio --extract --cpio`, which skips an early
  microcode archive; decompressed modules are normalized to `.ko.zst`. Test
  builds explicitly include amdgpu. Staging validates the supplied known-good
  module and rebuilt default image; promotion keeps `.prev-promote` backups.
  Backup-suffixed modules can be supplied to both helpers, and the installer
  excludes those backups when locating the installed amdgpu module.
- The GRUB backend requires an existing regular mkinitcpio preset/layout and
  checks that `/boot/vmlinuz-<pkgbase>` matches the running kernel's packaged
  image before installation/staging/promotion. Dracut/UKI-only Arch layouts
  and pending mismatched kernel updates are refused rather than converted.
- GRUB driver builds use the installed Kbuild headers/configuration directly,
  including LLVM for Clang-built kernels. Preflight selects pkgbase headers,
  checks GRUB/mkinitcpio and compiler tools, and rechecks dependency installs.
  Full vermagic mismatches are fatal. Sources still come from kernel.org;
  kernel series remain restricted to 7.1/7.2. Real CachyOS compilation/boot
  has not been validated by this session.
- Fixed remaining backend crossovers: GRUB apply/restore and audio refresh
  cannot invoke an installed Limine tool; 5K removal cannot edit Limine files.
  Apply/remove/suspend propagate boot-operation failures to their callers.
- Added `tests/test_arch_grub.py`, `tests/test_grub_helpers.py`; expanded
  `tests/test_grub.py`; isolated startup `/etc/default` fixtures and tested
  Arch/EndeavourOS/CachyOS plus Fedora/Limine precedence. Release tests require
  both libraries and the new guide in the archive.
- Updated `README.md`, `DEPENDENCIES.md`, `docs/development.md`, and added
  `docs/arch-grub.md` with supported layouts, helper usage and recovery.

### Final validation

- `./scripts/check.sh`: Bash syntax clean, **208 tests passed**, no skips.
- GRUB-specific subset: 45 tests across the three GRUB test files (all are
  included in that full-suite result). Build commands, image generation and
  GRUB regeneration are stubbed; all fixtures are temporary.
- Isolated launcher subset: 15 passed, including all three Arch-family IDs
  and backend precedence.
- `git diff HEAD --check`: clean.
- The sandbox initially blocked Bubblewrap namespaces and Git index writes.
  Approved execution outside the sandbox allowed the offline suite, its
  loopback release server and temporary Git snapshot/tag. Tests still ran as
  the normal user with fake boot tools; no kernel was built and no real GRUB
  or mkinitcpio command was run against this machine.
- Release tests produced ignored `dist/` artifacts and cleaned their temporary
  Git tag; no publication occurred.

## Earlier implementation checkpoint (historical)

## The user's request

"add grub support for arch based distros". Scope, decided with the user up front:

- Distros: Arch + EndeavourOS + CachyOS required; detection is `ID_LIKE=arch`
  broadly ("more universal"). No Manjaro-specific packaging beyond what pkgbase
  detection gives for free.
- Feature scope: **full parity** — the 5K amdgpu module works on GRUB (cmdline via
  `/etc/default/grub` + `grub-mkconfig`, initramfs via `mkinitcpio -P`).
- The test-entry helpers (`imac-alt-entry`, `imac-test-entry`) **are ported to GRUB**,
  not just gated off.

Hard constraint added later, mid-implementation: **"don't test grub directly on this
machine"** — this host is Omarchy/Limine. Never run grub-mkconfig/mkinitcpio or touch
`/etc/default/grub`, `/boot/grub`, `/etc/grub.d` here. GRUB code is exercised only by
the stubbed offline tests (`scripts/check.sh`). This machine always takes the Limine
path anyway because `/etc/default/limine` exists (Limine wins precedence).

The approved plan is at the session plan file; its design summary:

- Precedence: **Fedora > Limine > GRUB > refuse**. Bootloader detected by config
  presence only (`/etc/default/limine`, `/etc/default/grub`), per the platform.sh rule.
- New `scripts/lib/grub.sh` (primitives) + `scripts/lib/arch-grub.sh` (module
  overrides, sourced like `lib/fedora.sh`).
- GRUB test entries = cloned first grub.cfg menuentry in marker-delimited blocks in
  `/etc/grub.d/40_custom` + a separate initramfs image
  `/boot/initramfs-<pkgbase>-imac-<name>.img`. Default entry untouched; bad test build
  is escaped by rebooting into the default. No grub-reboot.

## Changes already made (all bash -n clean)

- `scripts/lib/platform.sh` — added `imac_is_arch` (ID=arch or ID_LIKE has arch),
  `imac_has_limine`, `imac_has_grub`, `imac_is_arch_grub` (limine wins ties),
  `imac_kernel_pkgbase` (reads `/usr/lib/modules/$KREL/pkgbase`, fallback `linux`).
- `scripts/lib/grub.sh` (new) — env-overridable `GRUB_DEFAULT_FILE`/`GRUB_CFG`/
  `GRUB_CUSTOM`/`GRUB_SUDO`; `grub_regen`, `grub_cmdline_has/add/remove` (timestamped
  backups, idempotent, token-exact), marker-delimited `grub_clone_entry`/
  `grub_drop_entry`/`grub_entry_exists`/`grub_list_entries` (clone of grub.cfg's first
  menuentry, microcode-aware initrd swap; refuses a 40_custom without the stock
  `exec tail -n +3 $0` header, creates it executable when missing), and image helpers
  `grub_image_path`/`grub_image_module` (bsdtar extract)/`grub_build_image`
  (mkinitcpio `--moduleroot` or live tree).
  NOTE: `grub_entry_begin/end` print a trailing newline on purpose (unit test caught
  marker+menuentry landing on one line).
- `scripts/lib/arch-grub.sh` (new) — overrides: `mod_boot_*` → n/a (Limine-specific),
  `boot_config_has`→`grub_cmdline_has`, `sync_boot_files` (mkinitcpio -P + regen),
  `verify_cmdline` (grep the default entry's linux line in grub.cfg),
  `suspend_drop_no_cstates`, `remove/add_4k_fallback`, `mod_5k_desc`. Sets
  `GRUB_SUDO=sudo`. Base `mod_5k_detect/apply/remove` and `mod_suspend_*` are reused.
- `scripts/imac-patcher` — sources `lib/arch-grub.sh` when `imac_is_arch_grub` (next to
  the fedora/kde overrides); `startup_deps_note` gained an `archgrub` flag (suspend →
  +grub-mkconfig; 5k → `mkinitcpio grub-mkconfig` instead of `limine-mkinitcpio`;
  boot → skipped); `mod_5k_preflight` and `audio_arch_deps` now use the pkgbase-derived
  headers package instead of hardcoded `linux-headers`.
- `scripts/patch-imac5k-amdgpu.sh` — `imac_require_limine` gate replaced by a
  Limine/GRUB dispatch (sources lib/grub.sh on GRUB); added `warn()`; `--restore`
  removes the param via `grub_cmdline_remove`; apply adds it via `grub_cmdline_add`;
  the shadow-config + UKI-fallback tail is wrapped in `if (( ! GRUB ))`; headers hint
  uses pkgbase.
- `scripts/imac-test-entry` — header updated; Fedora refusal via platform.sh; added
  `warn()`; GRUB backend block before the Limine `case`: `grub_stage` (build test
  initramfs from live tree, verify it carries the installed module, install named
  known-good + `mkinitcpio -P`, clone entry `5ktest`), `grub_promote` (extract from
  test image → install → `mkinitcpio -P` → verify default image carries it → drop
  entry), `grub_drop`, `grub_status` (same journalctl "running now" block). After the
  GRUB branch, an `imac_has_limine` gate refuses everything else.
- `scripts/imac-alt-entry` — same treatment: `grub_add` (private module tree +
  `mkinitcpio --moduleroot` plain initramfs, b2sum-verified, cloned entry),
  `grub_promote` (keeps `.prev-promote`, verifies rebuilt default image),
  `grub_drop`, `grub_list`. Header updated (IMAC_CMDLINE is Limine-only now).
- `tests/test_grub.py` (new) — 10 tests over lib/grub.sh with tempdir fixtures and a
  stubbed grub-mkconfig: token matching, idempotent add, remove in first/middle/only
  position and on `GRUB_CMDLINE_LINUX`, noop cases, clone retitle/initrd swap with and
  without microcode, exec-tail header rules, drop isolation, list. **All 10 pass.**

## Validation so far

- `bash -n` clean: platform.sh, grub.sh, arch-grub.sh, imac-patcher,
  patch-imac5k-amdgpu.sh, imac-alt-entry, imac-test-entry.
- `python3 -m unittest tests.test_grub` → OK (10 tests).
- Nothing else run yet. No GRUB command has been executed on this machine.

## Exactly where work stopped — what remains

1. `tests/test_arch_grub.py` (new, not started): source `lib/arch-grub.sh` with stubs
   (pattern: tests/test_suspend.py + tests/test_fedora.py) — `mod_boot_detect`→n/a,
   `boot_config_has` against a fake `/etc/default/grub`, `suspend_drop_no_cstates`
   removes idle=poll and regenerates, `verify_cmdline` greps grub.cfg,
   remove/add_4k_fallback roundtrip. Set `SCRIPT_DIR` to the repo's scripts/ and
   GRUB_* env vars to tempdirs before sourcing; stub `sudo(){ "$@"; }`,
   `grub-mkconfig`, `mkinitcpio`.
2. `tests/test_startup.py`: make `launch()` always `--ro-bind` a fake `/etc/default`
   dir (empty for existing tests — also fixes host `/etc/default/limine` leaking into
   the bwrap sandbox on the dev machine); add a GRUB test: fake `grub` file →
   `5k missing dependencies:` includes `grub-mkconfig`, excludes limine; the boot row
   shows n/a. Existing assertions must keep passing (none reference the boot line).
3. `tests/test_release.py` (~line 101): add `scripts/lib/grub.sh` and
   `scripts/lib/arch-grub.sh` to the tarball contents assertions.
4. Docs: `README.md` distribution table (Arch row: GRUB supported; note
   EndeavourOS/CachyOS via ID_LIKE=arch; keep the "each backend refuses to touch the
   other's bootloader" policy), `DEPENDENCIES.md` (grub/grub-mkconfig rows,
   pkgbase-derived headers names), `docs/development.md` code-layout table (the two
   new lib files).
5. Run `scripts/check.sh` (bash -n + full unittest suite). Consider also running the
   full suite BEFORE docs to catch regressions early.
6. Live smoke on real Arch+GRUB hardware is the user's side, not this machine's.

## Working-tree state at handoff

GRUB work (this task): modified `scripts/imac-alt-entry`, `scripts/imac-patcher`,
`scripts/imac-test-entry`, `scripts/lib/platform.sh`, `scripts/patch-imac5k-amdgpu.sh`;
untracked `scripts/lib/arch-grub.sh`, `scripts/lib/grub.sh`, `tests/test_grub.py`.
Unrelated pre-existing change, NOT from this task — do not touch: deletions of
`notes/issue-4455-reply-3-lean.{html,md}` and `notes/issue-4455-reply-4-rebootpci.{html,md}`.
Nothing is committed yet.
