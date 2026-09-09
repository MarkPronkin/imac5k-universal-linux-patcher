# Development

Work from a Git checkout and run checks as a normal user. Release installations
contain the runtime scripts and user documentation; they omit `tests/` and the
development notes.

## Check a change

From the repository root:

```bash
./scripts/check.sh
./scripts/check.sh -v                 # show each test name
```

This checks Bash syntax, then runs the Python standard-library test suite. It
needs Bash 4.4+, Python 3, Git, curl, and GNU tar, gzip and coreutils. No Python
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
| `test_startup.py` | The full launcher with commands absent from an isolated filesystem, fake pacman/DNF installs, terminal/pipe prompts, and symlink invocation |
| `test_eq.py`, `test_suspend.py` | Speaker routing/volume restoration and sleep masks with old boot-argument cleanup |
| `test_audio_jack.py` | Headphone jack detection, which streams follow the jack, and the two switching transitions |
| `test_eq.py::VendoredTuningTests` | That the vendored tuning is present, matches its recorded checksums, and still carries what apply rewrites |
| `test_audio.py` | Pinned headset source, DKMS upgrades, failures and removal |
| `test_fedora.py` | Module validation, install/restore, rollback, GRUB argument preservation and KDE colour settings |
| `test_release.py` | Reproducible archives, checksum validation, launchers, upgrades, version pruning and uninstall |

Tests replace system commands or use temporary directories. They do not apply
patches to the host. Release tests write ignored artifacts in `dist/`, create a
temporary Git tag (removed afterwards), and use `git stash create` to snapshot
tracked changes without altering the working tree or index. New runtime files
must be staged before release tests can include them in that snapshot. Inspect
the files and stage only the intended additions; never use a stash operation
that moves your working changes out of the checkout.

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

## Code layout

| Path | Responsibility |
|---|---|
| `scripts/imac-patcher` | CLI, menu, module orchestration and the base Omarchy implementations |
| `scripts/lib/platform.sh` | Model, GPU, distribution and desktop detection |
| `scripts/imac-audio-jack-switch` | Swaps the built-in output between the tuned speaker sink and the untuned jack output, installed by the `eq` module |
| `scripts/lib/fedora.sh` | Fedora module overrides using DNF, DKMS, dracut and GRUB |
| `scripts/lib/kde.sh`, `scripts/kde-display.py` | KDE colour handling through KScreen |
| `scripts/patch-imac5k-amdgpu.sh`, `scripts/fedora-imac5k` | Platform-specific graphics builds, installation and restore |
| `scripts/imac-alt-entry`, `scripts/imac-test-entry`, `scripts/95-limine-esp-hygiene` | Omarchy/Limine boot helpers |
| `install.sh`, `scripts/make-release.sh` | Download/install a release and build its reproducible archive |
| `patches/`, `configs/` | Kernel patches and configuration templates |
| `assets/imac-audio/` | The vendored speaker tuning: upstream's config and four impulse responses, byte-identical to the commit its README names |

Two files are carried verbatim from upstream and must stay byte-identical:
`patches/cs8409-headset-capture.patch` and `assets/imac-audio/iMacAudio.conf`.
`git diff --check` reports upstream's own trailing whitespace in both — do not
"fix" it. For the tuning, `VendoredTuningTests` fails if you do.


Platform overrides load after the base definitions; KDE overrides load last.
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
./scripts/make-release.sh 0.2.0-alpha HEAD
```

This produces `dist/imac5k-patcher-0.2.0-alpha.tar.gz` and `dist/SHA256SUMS`.
It archives the requested Git commit, so uncommitted edits are excluded.
`VERSION` and `COMMIT` identify the release, and archive metadata is fixed to
make repeated builds of the same version and commit byte-identical.

The allowlist in `scripts/make-release.sh` controls release contents. When
adding runtime files, confirm they are included and add coverage to the release
contents test. Launchers use symlinks, so resolve resources from the script's
real location rather than the caller's working directory.

Pushing a `v*` tag triggers `.github/workflows/release.yml`: checks, archive
creation, then publication with its checksum. Tags containing a hyphen are
published as prereleases. Building locally does not publish anything.
