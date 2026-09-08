# Fedora KDE

`imac-patcher` was written for Omarchy (Arch + Hyprland + Limine). This guide
covers the Fedora KDE backend: the same patcher, the same module names and the
same `--apply` / `--remove` commands, but driven by DNF, Fedora's kernel source
RPM, dracut, GRUB/BLS and KScreen instead.

Run it as your desktop user from a terminal inside a **Plasma Wayland** session:

```bash
./scripts/imac-patcher --status
./scripts/imac-patcher
```

The patcher detects Fedora itself — there is no flag to pass and nothing to
configure. If you are curious about *how* that dispatch works, see
[How the port is wired in](#how-the-port-is-wired-in) at the end.

---

## Status and scope

All Retina 5K iMac identifiers, including iMac Pro, pass the model check; see
the [model and module table](../README.md#models-and-module-availability).
The display backend requires `amdgpu`. The bundled CS8409 audio driver remains
specific to `iMac18,3`, and compatibility on other models is not hardware-verified.

The kernel patches themselves are unchanged; this port is the Fedora
integration *around* them. What that means concretely:

| | State |
|---|---|
| Install / restore logic | Covered by offline integration tests (`tests/`) |
| Graphics module build | Compiled and linked against Fedora `7.1.13-200.fc44.x86_64`; vermagic matches and `tiled_stitch` is present |
| Patch application | Both lean patches apply to that Fedora source at `--fuzz=0` |
| Display and audio behaviour on Fedora hardware | **Not yet validated.** The patches were hardware-tested on Omarchy |

Kernel series **7.1 and 7.2** remain the only accepted series, exactly as on
Omarchy. Fedora backports into its own kernel tree can still make a patch fail
to apply or fail to build on a specific release; the installer stops rather than
guessing.

**Fedora Kinoite and the other Atomic variants are not supported** for kernel or
audio installation. Their image-based deployment model needs separate packaging,
so the installer refuses to run on them (it checks for `/run/ostree-booted`).

---

## Native 5K

```bash
./scripts/imac-patcher --apply 5k
```

### Dependencies

The patcher lists anything missing and offers to install it with DNF. The one
that trips people up is **`kernel-devel-$(uname -r)`** — not `kernel-headers`,
and it must match the *running* kernel exactly. If that exact version is no
longer in the repos, update Fedora, reboot into the new kernel, and start again.

To prepare everything by hand instead:

```bash
sudo dnf install "kernel-devel-$(uname -r)" gcc make binutils bc dwarves \
    flex bison patch xz curl tar rpm-build koji python3 python3-rpm-macros \
    elfutils-libelf-devel openssl-devel dracut grubby mokutil perl-interpreter \
    findutils diffutils git
./scripts/fedora-imac5k --check
```

### How the build works

Unlike the Omarchy installer, which fetches a vanilla tarball from kernel.org,
the Fedora backend builds against Fedora's own tree so the module ABI matches
the kernel you are actually running:

1. Reads the exact source RPM name from the installed `kernel-core` package.
2. Downloads that source RPM from Koji (cached in the work directory).
3. Runs `rpmbuild -bp` to unpack it *with Fedora's own patches applied*.
4. Applies this repo's 5K patch stack to that prepared tree, `--fuzz=0`,
   dry-run first.
5. Compiles only `drivers/gpu/drm/amd/amdgpu` against
   `/usr/lib/modules/$(uname -r)/build`, using Fedora's `.config` and
   `Module.symvers` rather than inferring an ABI from a vanilla tree.

Source preparation uses `--nodeps`: a module build does not need the kernel
RPM's full `BuildRequires`. If a future Fedora spec revision needs another
preparation tool, install what `rpmbuild` names, or run
`sudo dnf builddep /path/to/the/cached/SPECS/kernel.spec`, then retry.

Budget roughly **10–15 GB of free space** and **20–40 minutes** for a first
build; Fedora's source preparation adds to both compared with the Arch path.
Output is cached under `~/.cache/kernel-5k-build/fedora-$(uname -r)/`, and a
change to the patch stack gets its own tree — a new stack is never applied on
top of an old one. `IMAC5K_WORK` moves the cache, `IMAC5K_JOBS` caps compile
parallelism, and `IMAC5K_STACK=verbose` selects the older verbose stack instead
of the default lean pair.

You can build without installing, and install separately:

```bash
./scripts/fedora-imac5k --build
sudo ./scripts/fedora-imac5k --install \
    "$HOME/.cache/kernel-5k-build/fedora-$(uname -r)/amdgpu.ko"
```

### What installation changes

Installation refuses to proceed unless the module's full vermagic matches the
running kernel and the `tiled_stitch` parameter is present. Then:

| Path | What happens |
|---|---|
| `/usr/lib/modules/<kernel>/updates/imac5k/amdgpu.ko.xz` | The patched module. Fedora's packaged `amdgpu` is left untouched |
| `/etc/depmod.d/imac5k-<kernel>.conf` | A kernel-specific `override` line pointing at it |
| `/boot/initramfs-<kernel>.img` | Rebuilt with dracut, after the original is saved |
| GRUB entry for **that kernel only** | Gains `amdgpu.tiled_stitch=1`. Any `video=eDP-1:...` override is saved and removed so it cannot pin a lower resolution. Every other argument is left alone |
| `/var/lib/imac-patcher/5k-<kernel>/` | The stock initramfs and the original display arguments |

Two deliberate omissions. The installer never uses
`grubby --update-kernel=ALL`, so your other installed kernels stay untouched and
remain available as a recovery path. And there is no automatic rebuild hook: the
module is built for one kernel version, so **re-run the patcher after every
kernel update** (the patcher reports `partial` until you do).

The Limine test-entry and ESP-hygiene helpers refuse to run on Fedora. This port
does not rewrite the EFI fallback or manage boot entries beyond the single
`grubby` argument change above.

### After rebooting

Open KDE **System Settings → Display & Monitor → Display Configuration**, select
**5120×2880**, and pick a scale (200% is a sensible starting point). The kernel
stitch layer presents the two tiles to KWin as a single output, so nothing
compositor-side needs to change.

Then run `./scripts/verify.sh` and check the *active* mode, motion across the
seam, and audio. A 5120×2880 mode merely being listed does not mean it is in
use.

---

## Restore and recovery

While running the kernel you patched:

```bash
./scripts/imac-patcher --remove 5k
# or, directly:
sudo ./scripts/fedora-imac5k --restore
```

This removes the module override and the depmod config, restores the original
display arguments, and rebuilds the stock initramfs. It needs no build
dependencies and no signing keys, so it works from a minimal environment.

If installation fails part-way through the module, initramfs or GRUB changes, it
rolls itself back to the saved stock initramfs automatically. Even so, keep a
bootable backup for your first hardware trial, as the upstream project
recommends.

**If the graphical session does not come up:** pick another installed Fedora
kernel in GRUB. To get a text console on the *affected* kernel, edit its GRUB
entry for that one boot and append
`systemd.unit=multi-user.target nomodeset`, then run `--restore` there. Restore
always targets `uname -r`, so running it from a different kernel will not clean
up the broken one.

---

## Secure Boot

The graphics installer checks kernel lockdown and Secure Boot state before it
installs anything. Where signing is enforced, supply your own enrolled signing
key and DER certificate — the installer signs the module after stripping and
before compression, and it never disables Secure Boot.

If you already have a key pair, enroll the certificate, reboot, and confirm the
enrollment in the firmware MOK manager:

```bash
sudo mokutil --import /path/to/certificate.der
```

Then:

```bash
export IMAC5K_SIGN_KEY=/path/to/private-key.priv
export IMAC5K_SIGN_CERT=/path/to/certificate.der
./scripts/imac-patcher --apply 5k
```

The patcher passes those two variables through `sudo` for you. Installing
directly needs
`sudo --preserve-env=IMAC5K_SIGN_KEY,IMAC5K_SIGN_CERT ...`. Keep the private key
private.

Audio is different: DKMS does its own signing. If DKMS's key is not enrolled,
the audio installer prints the enrollment command and stops *before* touching
the initramfs.

---

## Audio, tuning, colour and sleep

```bash
./scripts/imac-patcher --apply audio
./scripts/imac-patcher --apply eq color suspend
```

**Audio** verifies the iMac model and the CS8409 codec, then registers the
upstream driver with DKMS directly rather than through its install wrapper —
the wrapper assumes `updates/dkms` and loops over every installed kernel, which
can hide a failed build behind a later success. DKMS keeps its own source copy
under `/usr/src`, so later kernels rebuild without the cache. An existing
registration is reused, and the initramfs is rebuilt at the end. Reboot before
testing speakers and microphone.

**Tuning** (`eq`) switches the speaker card to Analog Surround 4.0 and loads a
PipeWire filter-chain over it. `lsp-plugins` comes from Fedora's repositories;
`bankstown` does not exist as a Fedora package and has to be built from
https://github.com/chadmed/bankstown into `~/.lv2` first, or the module stops
and says so rather than installing a graph that cannot load.

**Colour** selects the internal panel's **EDID** colour profile through
`kscreen-doctor`. This uses the colour information the panel advertises — it is
not a measurement-based calibration. The previous sRGB/ICC/EDID selection is
saved and put back by `--remove color`; existing ICC profile *files* are never
touched. KScreen has to be reachable from the current Plasma Wayland session.
No Hyprland config is written and no live KWin configuration file is
overwritten.

**Sleep** uses the same systemd target masks as the upstream project. If you
want KDE's Power Management UI to reflect the change, disable automatic sleep
there as well. If the retired `idle=poll` variant left the argument on the
current kernel's GRUB entry, applying or removing the module strips it with
grubby. `--remove suspend` lifts the masks.

---

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `Missing Python RPM macros` from `--check`, or preparation dies at `%py3_shebang_fix` with `fg: no job control` | An undefined RPM macro reaches `/bin/sh` literally. `sudo dnf install python3-rpm-macros` and retry — the downloaded source RPM is reused and preparation reruns automatically |
| `Install matching development files` | `kernel-devel` does not match the running kernel. Install `kernel-devel-$(uname -r)`, or update and reboot first |
| `Module vermagic does not match` | The module was built against a different kernel than the one running. Rebuild after rebooting into the kernel you intend to patch |
| `Compressed module uses ... integrity check` | Fedora's kernel XZ decoder only accepts CRC32; the installer already compresses with `--check=crc32`, so this indicates a modified module |
| `Signing certificate is not enrolled` | Enroll the DER certificate with `mokutil --import`, reboot and confirm in the MOK manager |
| Desktop comes up on llvmpipe (software rendering) | `amdgpu` failed to load. `./scripts/verify.sh` prints the kernel log lines; `--restore` returns you to stock |
| 5120×2880 is listed but not active | Select it explicitly in KDE Display Configuration; an offered mode is not an active one |
| Patcher reports `partial` after a kernel update | Expected — the module is per-kernel. Re-run `--apply 5k` |

---

## How the port is wired in

The design goal was to add Fedora without forking or rewriting the Omarchy
implementation. The patcher is a set of `mod_<id>_<verb>` shell functions
(`detect`, `apply`, `remove`, …) over the module list
`audio eq color suspend boot 5k`. The Fedora backend **redefines only the
functions that differ**, and it is sourced *after* the originals, so anything it
does not mention keeps the Omarchy behaviour verbatim.

```
scripts/imac-patcher
  ├─ source lib/platform.sh          detection helpers, always
  ├─ …original Omarchy mod_* definitions…
  ├─ source lib/fedora.sh   if Fedora   → overrides audio, suspend, boot, 5k
  └─ source lib/kde.sh      if KDE      → overrides color
```

### New files

| File | Role |
|---|---|
| `scripts/lib/platform.sh` | `imac_is_fedora`, `imac_is_atomic`, `imac_is_kde`, `imac_require_limine`. Detection reads `/etc/os-release`, `/run/ostree-booted` and `XDG_CURRENT_DESKTOP` — never an installed tool, so a stray `grubby` or `hyprctl` cannot change the decision |
| `scripts/lib/fedora.sh` | Fedora `mod_*` overrides: DNF dependency prompts, the DKMS audio path, the 5K module wrapper, and a `boot` module that reports `n/a` because Limine repair is meaningless on GRUB |
| `scripts/lib/kde.sh` | The `color` module on KDE, delegating to `kde-display.py` |
| `scripts/fedora-imac5k` | The Fedora graphics installer: `--check`, `--build`, `--install MODULE`, `--restore`. Builds as your user; only install and restore need root. Its functions are sourceable so the tests can drive them |
| `scripts/kde-display.py` | KScreen wrapper: reads the panel's colour profile source, applies EDID, restores the saved selection, and reports whether 5120×2880 is the *active* mode |
| `tests/test_fedora.py` | Offline tests for the installer and the display helper |
| `tests/test_patcher_menu.py` | Drives the real interactive menu with mock modules |
| `docs/fedora-kde.md` | This guide |

### Changed files

| File | Change |
|---|---|
| `scripts/imac-patcher` | Sources `lib/platform.sh` and, conditionally, the two backends. Also: propagates module failures into the exit status instead of always exiting `0`, and reads the menu selection with `mapfile` so module prompts and child installers keep the terminal on stdin (a redirected `while read` loop handed them its own EOF) |
| `scripts/patch-imac5k-amdgpu.sh` | On Fedora, `exec`s `fedora-imac5k`; otherwise asserts Limine as before |
| `scripts/imac-alt-entry`, `scripts/imac-test-entry`, `scripts/95-limine-esp-hygiene` | Refuse to run on Fedora with a pointer to the supported path, rather than acting on a bootloader that is not there |
| `scripts/verify.sh` | Reports KDE output state via `kscreen-doctor` when on KDE and Hyprland otherwise, and adds the checks needed to diagnose a failed graphics install: installed vs loaded module, vermagic, `tiled_stitch`, bound DRM driver, GL renderer (llvmpipe means no acceleration), audio/DKMS state. Optional tools are probed before use |
| `patches/imac5k-lean-core-7.2.x.patch`, `patches/imac5k-stitch-layer-7.x.patch` | Match context adjusted so both apply to Fedora `7.1.13-200.fc44` as well as 7.2.x. **No change to the driver code they add** — six hunks anchored on adjacent 7.2-only firmware, HDMI, IRQ and atomic-commit code were re-anchored on stable insertion points |
| `README.md`, `patches/README.md` | Document the two supported platforms and point here |

### Tests

```bash
python3 -m unittest discover -s tests -v
```

Everything runs offline against temporary directories and mock boot tools — no
root, no package installation, and nothing on the host is touched. Covered:
rejection of a module whose vermagic does not match, install and restore round
trip, rollback when dracut fails, preservation of unrelated GRUB arguments,
active-vs-available mode detection, KDE colour save/restore round trip, and the
interactive menu's stdin handling and exit status.

### References

- [Fedora kernel source RPM workflow](https://fedoraproject.org/wiki/Building_a_custom_kernel/Source_RPM)
- [dracut manual](https://man7.org/linux/man-pages/man8/dracut.8.html)
- [KDE KScreen command implementation](https://github.com/KDE/libkscreen/blob/master/src/doctor/doctor.cpp)
