# Development

Work from a Git checkout and run checks as a normal user. Release installations
contain the runtime scripts and user documentation; they omit `tests/`, `notes/`,
and `TODO.md`.

## Check a change

From the repository root:

```bash
./scripts/check.sh
./scripts/check.sh -v                 # show each test name
```

This checks Bash syntax, then runs the Python standard-library test suite. It
needs Bash 4.4+, Python 3, Git, curl, util-linux, diffutils, and GNU tar, gzip and coreutils. No Python
packages, kernel build tools, root access, or external network are required.
The release tests serve test downloads on the loopback interface.

To run only the tests relevant to a change:

```bash
python3 -m unittest discover -s tests -p 'test_patcher*.py' -v
python3 -m unittest discover -s tests -p 'test_fedora.py' -v
```

| Tests | Behaviour covered |
|---|---|
| `test_patcher_cli.py`, `test_patcher_driver.py`, `test_patcher_menu.py` | Argument validation, status probe reuse, fresh checks before actions, batch exit codes, and terminal input |
| `test_models.py`, `test_deps.py` | Model and module restrictions, dependency prompts and failed installs |
| `test_limine_helpers.py`, `test_patch_stacks.py` | Package-named default UKI protection, unidentified-image refusal, and matching lean stacks across installers |
| `test_startup.py` | The full launcher with commands absent from an isolated filesystem, fake pacman/DNF installs, terminal/pipe prompts, and symlink invocation |
| `test_eq.py` | Speaker routing and volume restoration |
| `test_t2speakers.py` | T2 speaker identity, channel counts, live ports/mixer, ownership, apply rollback and removal recovery |
| `test_t2speakers_audio.py` | Optional private PipeWire graph: reproduces silent rear channels and checks actual four-channel output from stereo, mono, and PulseAudio clients |
| `test_suspend.py`, `test_tb_sleep_hook.py`, `test_wifi_sleep_hook.py` | Sleep target masks, the s2idle sleep drop-in and old boot-argument cleanup; the T2 rules (t2bce bound, no T2 unload hooks, no s2idle drop-in) against a fake PCI tree; the iMac18,3 USB controller fix (DKMS build, boot load, detection, removal, Secure Boot) against fake DKMS and sysfs; the Thunderbolt and Wi-Fi sleep hooks against a fake sysfs tree |
| `test_xhci_fix.py` | The USB controller fix's DKMS package, boot-load file and release path agree with the patcher; its source skips XHC1's ACPI power methods instead of holding D0; the model gate and startup audit |
| `test_audio_jack.py` | Headphone jack detection, which streams follow the jack, and the two switching transitions |
| `test_eq.py::VendoredTuningTests` | That the vendored tuning is present, matches its recorded checksums, and still carries what apply rewrites |
| `test_audio.py` | Pinned headset source, DKMS upgrades, failures and removal |
| `test_fedora.py` | Module validation, install/restore, rollback, GRUB argument preservation and KDE colour settings |
| `test_grub.py`, `test_arch_grub.py`, `test_grub_helpers.py` | Arch-family GRUB configuration edits, rollback, entry paths and IDs, module overrides, GCC/Clang build dispatch, and staged test/promotion lifecycles with fake boot tools |
| `test_release.py` | Reproducible archives, checksum validation, launchers, upgrades, version pruning and uninstall |
| `test_review_regressions.py` | Atomic Limine config edits, pinned image verification, failed decompression/rebuilds, colour restoration, and upgrade copy failure |

Tests replace system commands or use temporary directories. They do not apply
patches to the host. Release tests write ignored artifacts in `dist/`, create a
temporary Git tag (removed afterwards), and use a temporary Git index to snapshot
runtime files, including new files. The user's index and working tree are
preserved. Test snapshots create unreachable Git objects, not branch commits.

The driver tests use a tiny local Git fixture to exercise the installer
without downloading or compiling a kernel.

The additional startup tests require `bubblewrap` and Linux user namespaces.
They mount the host read-only, hide host commands, substitute test hardware and
OS identifiers, and disable networking. These are full launcher tests with
simulated Arch/Fedora environments and package managers, not distribution VM
or hardware tests. If isolation is unavailable locally they report a skip;
to require them and fail instead of skipping:

```bash
IMAC5K_REQUIRE_STARTUP_TESTS=1 python3 -m unittest discover -s tests -p 'test_startup.py' -v
```

Both branch/PR checks and tagged release builds run `scripts/check.sh`, install
the isolation runner, and require the startup tests separately. CI runs that
isolated subset with `sudo` on the disposable runner so namespace restrictions
cannot silently skip it. Do not run the entire suite as root.

`scripts/verify.sh` has a different purpose: it probes a live machine after
installation. Offline tests cannot establish display timing, speaker quality,
or successful boot on a particular iMac; record hardware validation separately.

The T2 audio integration tests optionally use `pipewire`, `wireplumber`,
`pw-cat`, `pw-dump`, `pw-config`, `pipewire-pulse`, and `pacat`. They create
private sockets and a virtual sink, with hardware monitors disabled and no
connection to desktop audio.
They skip when these tools or Unix sockets are unavailable. Require them with:

```bash
IMAC5K_REQUIRE_T2_AUDIO_TESTS=1 python3 -m unittest discover -s tests -p 'test_t2speakers_audio.py' -v
```

## Code layout

| Path | Responsibility |
|---|---|
| `scripts/imac-patcher` | CLI, menu, module orchestration and the base Omarchy implementations |
| `scripts/lib/platform.sh` | Model, GPU, distribution and desktop detection |
| `scripts/imac-audio-jack-switch` | Swaps the built-in output between the tuned speaker sink and the untuned jack output, installed by the `eq` module |
| `scripts/t2-speakers.py` | Owns the iMac Pro WirePlumber rule, verifies its live conversion, and handles rollback/recovery |
| `scripts/lib/grub.sh` | Arch GRUB command-line edits, generated menu selection, custom test entries and mkinitcpio image helpers |
| `scripts/lib/arch-grub.sh` | Arch-family GRUB module overrides; Limine boot repair is n/a |
| `scripts/lib/fedora.sh` | Fedora module overrides using DNF, DKMS, dracut and GRUB |
| `scripts/lib/kde.sh`, `scripts/kde-display.py` | KDE colour handling through KScreen |
| `scripts/patch-imac5k-amdgpu.sh`, `scripts/fedora-imac5k` | Platform-specific graphics builds, installation and restore |
| `scripts/imac-alt-entry`, `scripts/imac-test-entry` | Isolated module test entries and promotion for Limine and Arch-family GRUB |
| `scripts/95-limine-esp-hygiene` | Omarchy/Limine ESP maintenance |
| `install.sh`, `scripts/make-release.sh` | Download/install a release and build its reproducible archive |
| `patches/`, `configs/` | Kernel patches and configuration templates |
| `assets/imac-audio/` | The vendored speaker tuning: upstream's config and four impulse responses, byte-identical to the commit its README names, with upstream's MIT `LICENSE` |

Two files are carried verbatim from upstream and must stay byte-identical:
`patches/cs8409-headset-capture.patch` and `assets/imac-audio/iMacAudio.conf`.
`git diff --check` reports upstream's own trailing whitespace in both — do not
"fix" it. For the tuning, `VendoredTuningTests` fails if you do.


Platform overrides load after the base definitions; KDE overrides load last.
Backend precedence is Fedora, then Limine, then Arch-family GRUB. Bootloader
selection uses configuration presence, never installed commands. GRUB tests
use temporary boot files and fake `grub-mkconfig`/`mkinitcpio` commands; they
must not regenerate this development machine’s boot configuration.
Shared changes belong in the base implementation, with overrides only where
the platform behaves differently. Check both implementations when changing
the module contract or a patch stack.

## Module contract

Each ID in `MODULES` implements these Bash functions:

| Function | Contract |
|---|---|
| `mod_<id>_title`, `_desc` | Print user-facing text |
| `mod_<id>_tier` | Print `safe` or `boot`; the tier may depend on current boot configuration |
| `mod_<id>_detect` | Print exactly `applied`, `not-applied`, `partial`, or `n/a`; inspect without applying changes |
| `mod_<id>_apply`, `_remove` | Perform the requested operation and return nonzero on failure |

`show_status` captures one state and tier per module for the status display and
the following menu. This snapshot is for presentation. `run_module` probes
again before acting, since an earlier action can change another module's
prerequisites. Safe batches also recheck each module's tier before running it.

Keep diagnostics out of detection's standard output. Check failure returns
explicitly: the main patcher uses `set -uo pipefail`, and Bash can also suppress
`errexit` inside functions invoked by a conditional. A later successful command
must not hide a failed install or restore. Tests should exercise observable
behaviour with mocked system tools, including failure and recovery where system
files are involved.

CLI validation happens before the hardware/dependency gates. Adding a module
means updating `MODULES`, help text, compatibility documentation, and any
platform override it needs. `--force` bypasses only the launcher model gate;
keep hardware restrictions inside the module itself.

## Releases

Build from a committed revision:

```bash
./scripts/make-release.sh 0.2.1-alpha HEAD
```

This produces `dist/imac5k-patcher-0.2.1-alpha.tar.gz` and `dist/SHA256SUMS`.
It archives the requested Git commit, so uncommitted edits are excluded.
The checksum manifest includes every release archive currently in `dist/`.
`VERSION` and `COMMIT` identify the release, and archive metadata is fixed to
make repeated builds of the same version and commit byte-identical.

Apply/remove/menu operations use a per-user `flock` under the patcher's state
directory. Diagnostics go to stderr. Failed or invalid module detection stops
that action and makes `--status` return nonzero; a successful action can still
report `partial` when a reboot is required.

The allowlist in `scripts/make-release.sh` controls release contents. When
adding runtime files, confirm they are included and add coverage to the release
contents test. Launchers use symlinks, so resolve resources from the script's
real location rather than the caller's working directory.

Publish from the maintainer's own GitHub account, so GitHub credits the
release to them and not to `github-actions`. Push an annotated tag, build the
archive from that tag in a fresh clone (its `dist/` then lists only this
archive in `SHA256SUMS`), and upload both files with the release:

```bash
git tag -a v0.2.1-alpha -m "v0.2.1-alpha: ..." && git push origin v0.2.1-alpha
git clone --branch v0.2.1-alpha . /tmp/imac5k-release
/tmp/imac5k-release/scripts/make-release.sh 0.2.1-alpha v0.2.1-alpha
gh release create v0.2.1-alpha --verify-tag --prerelease --target test \
    --title v0.2.1-alpha --notes-file release-notes.md \
    /tmp/imac5k-release/dist/imac5k-patcher-0.2.1-alpha.tar.gz \
    /tmp/imac5k-release/dist/SHA256SUMS
```

`--target` names the branch the release comes from. Versions containing a
hyphen are prereleases. Publishing triggers `.github/workflows/release.yml`:
it runs the checks, rebuilds the archive from the tagged commit in an emptied
`dist/` (the release tests leave archives there), and fails if the published
tarball or `SHA256SUMS` differ or a suffixed version is not marked as a
prerelease. The published event uses the workflow as it is in the tagged
commit; to check an existing release with the current workflow, run
`gh workflow run release.yml --ref test -f tag=v0.2.1-alpha`. Pushing a tag
or building locally publishes nothing.
