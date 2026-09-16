# Review fixes — 2026-09-16

Implemented during the review recheck on `review/full-audit-2026-09-11`, in the
working tree based on `c57b129`. This note replaces the two root-level review
reports and records the fixes, affected files, validation, and limits.

Existing working-tree and staged changes were preserved. The changes remain
local: no commit, push, merge, or release was made. The branch's existing
restriction against pushing, merging, or releasing remains in place.

The subsequent iMac Pro T2 speaker review and its additional fixes are recorded
in [the T2 fix note](t2-speakers-review-2026-09-16.md).

## 1. Module framework, startup, and upgrade

Files: [imac-patcher](../scripts/imac-patcher),
[platform.sh](../scripts/lib/platform.sh).

- Check script/repository path resolution and platform-library loading before
  continuing startup.
- Validate release `VERSION` contents and propagate read failures, including
  the version command's exit status. Reject an unknown current version before
  attempting an upgrade.
- Check local installer copies for copy failure and empty contents before
  executing them. Run upgrade in a subshell with cleanup traps for temporary
  installers on exit, interruption, and termination.
- Send warnings to stderr so diagnostics cannot contaminate captured module
  states or status output.
- Validate each detection result and exit status. Empty, multiline, invalid,
  or failed probes stop the corresponding action. Status displays `error` and
  returns failure; interactive startup does not continue on failed status.
- Recheck the module state after an action and propagate detection errors.
- Deduplicate module IDs in argument parsing and batch execution.
- Add a per-user operation lock for mutations and the interactive menu, with
  `flock` included in dependency checks.
- Restore the text menu's cursor on SIGINT/SIGTERM and reset those traps when
  leaving the picker.
- Check header-package lookup failures before adding package arguments.
- Recognize `ID_LIKE=archlinux` and avoid noisy reads of absent OS metadata.

## 2. Release installation and removal

File: [install.sh](../install.sh).

- Validate explicitly supplied and API-returned release tags before using them
  in URLs or destination paths.
- Normalize installation and launcher directories, reject newlines in launcher
  directory names, and lock each installation directory against concurrent runs.
- Check the additional `flock`, `realpath`, and `diff` dependencies.
- Stage extraction inside the installation directory so publishing a completed
  version uses a rename on the same filesystem.
- Replace `current` and launcher symlinks through a temporary sibling and
  atomic rename.
- Reuse an identical same-version installation. Refuse a differing or modified
  existing version while preserving it and the current installation.
- Require exactly one checksum entry with the exact archive filename and a
  64-character hexadecimal SHA-256. Warn when verification is disabled.
- Record custom launcher paths. Uninstall removes only launchers still pointing
  to this installation and preserves replacements made by the user.
- Prune real version directories with null-delimited filenames, preserving the
  current version and two other recent versions without traversing symlinks.

## 3. Release archive generation

File: [make-release.sh](../scripts/make-release.sh).

- Validate the version before constructing archive paths.
- Serialize release builds with a lock in `dist/`.
- Build temporary archives and manifests within `dist/`, then rename completed
  files into place.
- Regenerate `SHA256SUMS` for every release archive in the directory, preserving
  checksum coverage when multiple versions are present.

## 4. Limine boot entries and module verification

Files: [imac-alt-entry](../scripts/imac-alt-entry),
[imac-test-entry](../scripts/imac-test-entry), new
[limine-config.py](../scripts/lib/limine-config.py), and
[grub.sh](../scripts/lib/grub.sh).

- Replace truncating configuration writes with backed-up, atomic entry updates
  that preserve the config's symlink, permissions, and ownership.
- Match complete entry titles, so deleting one name cannot remove a neighbour
  with the same prefix or an entry without a cmdline.
- Read the cmdline associated with the intended default image; reject missing
  or ambiguous cmdlines.
- Verify the recorded image path and BLAKE2 hash before promotion.
- Normalize supplied modules, validate compression and kernel release, and
  support `.ko`, `.zst`, `.xz`, `.gz`, and recognized backup suffixes.
- Extract UKI modules through the shared initramfs helper, including images with
  prepended microcode and modules stored uncompressed.
- Propagate decompression failures before comparing module hashes, preventing
  two failed reads from appearing equal.
- Check rebuild failures explicitly and verify that a successful rebuilt
  default image actually contains the intended module.
- Preserve the first module backup across promotion retries.
- Validate staging inputs before mutation and refuse to overwrite an existing
  staged test UKI.
- Capture entries before regeneration. Restore only recorded entries whose
  image hashes still match, keeping their original cmdlines; do not invent
  entries for unidentified images.
- Replace an entry in one configuration update and retain the test image until
  promotion verification succeeds. Propagate fallback image copy failures.

## 5. GRUB boot entries and configuration

Files: [grub.sh](../scripts/lib/grub.sh),
[imac-alt-entry](../scripts/imac-alt-entry), and
[imac-test-entry](../scripts/imac-test-entry).

- Use checked privileged reads for configuration access and parent-directory
  probes instead of treating access failures as missing files.
- Accept literal `!` in supported kernel arguments and trailing whitespace or
  comments on a menuentry's closing brace.
- Share module normalization and decompression-failure checks with Limine.
- Check that a managed entry references the expected image before promotion.
- Read the image recorded in the managed entry for drop/list/status, avoiding
  orphaned images when the running kernel package has changed.
- Preserve the first promotion backup on retries.

## 6. Arch graphics build

Files: [patch-imac5k-amdgpu.sh](../scripts/patch-imac5k-amdgpu.sh) and its
preflight in [imac-patcher](../scripts/imac-patcher).

- Resolve the supported module locations deterministically and refuse missing
  or ambiguous results.
- Check required tools, the installed kernel build configuration, matching
  headers, and at least 10 GiB of free space before building.
- Select Clang/LLVM when the installed kernel requires it on both backends.
- Use the installed Kbuild environment on Limine as well as GRUB, and compare
  the complete vermagic string before installing the built module.
- Lock the build workspace, verify downloaded or cached kernel archives against
  kernel.org's SHA-256 manifest, and extract a fresh isolated source tree for
  each build. Remove the temporary source tree on exit while retaining the
  verified archive cache.
- Enforce `--fuzz=0 --batch --forward` during patch dry-run and application.
- Print recovery instructions before mutation and use CRC32 for XZ-compressed
  modules.

## 7. Fedora graphics recovery

File: [fedora-imac5k](../scripts/fedora-imac5k).

- Check argument reads and aggregate failures while restoring kernel arguments.
- Restore the saved stock initramfs through a temporary sibling and rename
  before attempting fallible follow-up recovery steps.
- Build replacement initramfs images separately, then install them atomically;
  partial dracut output cannot truncate the restored stock image.
- Attempt all rollback steps and report incomplete recovery instead of hiding
  failures.
- Preserve the original stock backup and recovery state for retries, including
  after the installed marker is removed.
- Record incomplete recovery and refuse another install until restore succeeds.
- Print recovery guidance before mutation.

## 8. Boot maintenance and diagnostics

Files: [imac-patcher](../scripts/imac-patcher),
[verify.sh](../scripts/verify.sh).

- Propagate boot-detection probe failures, shadow-config archive/removal errors,
  maintenance-hook installation/removal errors, and fallback copy failures.
- Create the maintenance-hook destination directory during installation.
- Reject missing UKI paths and empty extracted command lines.
- Pass paths to privileged shell snippets as positional arguments.
- Discover GPU PCI addresses from DRM devices instead of assuming `01:00.0`.

## 9. Audio detection, jack switching, and EQ

Files: [imac-patcher](../scripts/imac-patcher),
[imac-audio-jack-switch](../scripts/imac-audio-jack-switch).

- Report failed DKMS status/conflict queries as detection errors while retaining
  the expected absent-DKMS state handling.
- Require a unique PCI card offering the four-channel speaker profile in both
  selectors. Ignore external USB cards and refuse ambiguous PCI matches.
- Force the C locale for event subscription parsing.
- Reconcile the initial jack state, latch a transition only after success, and
  allow a failed transition to be retried on subsequent events.
- Stop a transition on service-stop failure. Do not start the EQ chain after
  timing out while waiting for the required card profile.
- Match sink names exactly and scope the raw-speaker hide rule to the selected
  card. Restrict default-output claims to the intended analog outputs.
- Parse colon-separated LV2 paths without word splitting or glob expansion.
- Escape literal paths in generated configuration replacements and check saved
  profile writes.
- Continue EQ file/unit cleanup when hardware volume restoration fails, retain
  the restoration state, and return failure so recovery can be retried.
- Propagate saved-profile restoration failures and count retained state files
  when detecting a partial installation.
- Preserve external default outputs during removal and restore only an
  appropriate analog sink on the original card.
- Delete only owned impulse-response files, preserve unrelated user files, and
  guard bankstown bundle removal.

## 10. Colour configuration

Files: new [hypr-color.py](../scripts/hypr-color.py),
[kde-display.py](../scripts/kde-display.py), and
[imac-patcher](../scripts/imac-patcher).

### Hyprland

- Select one literal internal-panel monitor rule; ignore external rules and
  comments. Refuse missing or ambiguous supported configuration.
- Preserve a general fallback rule by adding a specific internal-panel override.
- Atomically save the previous colour selection and configuration changes.
- Restore the previous value, including an absent colour field, or remove the
  override created by apply. Preserve unrelated edits and subsequent manual
  colour changes.
- Validate saved state against the configuration and monitor. Report legacy
  installs without saved state instead of guessing their previous selection.
- Return success for a successful edit when `hyprctl` is unavailable.

### KDE

- Escape output identifiers and fail on a missing output block or command error.
- Compare mode width/height without requiring exact equality of the size object.
- Discard stale saved state only on a verified panel-identity change; preserve
  the saved selection and fail when an expected identity is missing.
- Poll for the requested profile after asynchronous KScreen application.
- Handle missing state files and malformed response types explicitly. Keep
  unsupported non-Wayland status distinct from a failed query.

## 11. Documentation and regression coverage

Updated [README](../README.md), [DEPENDENCIES](../DEPENDENCIES.md),
[development guide](../docs/development.md), and
[audio asset documentation](../assets/imac-audio/README.md) for dependency and
build requirements, checksum guarantees, release retention/reinstallation,
audio configuration rewrites, colour state, and test behaviour.

Tests added or extended:

| Files under `tests/` | Coverage |
|---|---|
| `test_review_regressions.py` | Hyprland restoration and unrelated edits; external/ambiguous audio cards; atomic Limine updates, pins and saved entries; failed decompression, stale rebuilds, and failed upgrade copies |
| `test_patcher_driver.py` | Failed/invalid probes, status failures, duplicate module IDs |
| `test_audio.py`, `test_audio_jack.py`, `test_eq.py` | DKMS query failures, initial reconciliation, transition retry/timeouts, cleanup with missing hardware, external outputs, preserved user files, literal paths |
| `test_fedora.py` | Partial dracut output, grubby read/write failures, recovery retries, missing panel identity |
| `test_arch_grub.py`, `test_grub_helpers.py`, `test_limine_helpers.py` | Both build backends and compiler choices, ABI mismatches, entry/image mismatch, kernel-package switches, unidentified-image refusal |
| `test_release.py` | Real multi-archive manifests, exact/missing checksums, bypass warnings, version validation, immutable reinstall, custom/replaced launchers, pruning, locks, latest-release lookup, archive contents and reproducibility |
| `test_deps.py`, `test_startup.py` | Fixtures for the new lock dependency and stderr diagnostics; required isolated launcher checks |

Release tests use a temporary Git index to snapshot the runtime working tree,
including new helper files, without changing the user's index. The archive
checks include the installer, license, documentation, version/commit metadata,
and new runtime helpers.

## Validation and limits

Completed before this documentation-only consolidation:

```bash
IMAC5K_REQUIRE_STARTUP_TESTS=1 bash scripts/check.sh
git diff --check
```

**396 tests passed**, including the required bubblewrap startup checks. Bash
syntax and diff checks passed. The test log was saved at
`/tmp/imac-review-check.log`.

Boot/package/audio commands were mocked; fixtures used temporary files, local
HTTP downloads, and temporary Git objects. No live boot regeneration, driver
installation, or desktop/audio reconfiguration was performed. Kernel patches
and vendored tuning were unchanged; unresolved driver hypotheses are not
claimed as fixes.

Boot promotion spans multiple files and does not provide a transactional
rollback of the entire boot partition. Legacy colour state may require a
manual selection, and live stream moves can still race application changes.
