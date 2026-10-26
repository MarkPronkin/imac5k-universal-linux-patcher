# Debian

Debian 13 (trixie), amd64, with GRUB and initramfs-tools has a dedicated
backend. Run the patcher as your desktop user; it calls sudo for system changes:

```bash
./scripts/imac-patcher --status
./scripts/imac-patcher --apply 5k
```

Debian is detected from `ID=debian` in `/etc/os-release`. Ubuntu has its [own source/ABI rules](ubuntu.md). Other derivatives are not
included by `ID_LIKE=debian`. Limine, systemd-boot, UKI-only and dracut layouts are not
supported by the Debian graphics installer.

## Compatibility

The usual [model restrictions](../README.md#compatibility) still apply.
Native 5K requires an AMD GPU using `amdgpu`. The Debian backend accepts
Linux **6.12**, **7.1** and **7.2**, using Debian's own kernel packages and exact
matching headers and source. It uses the lean stack; `IMAC5K_STACK=verbose`
is not supported. An unported kernel fails before installation.

- `5k`: the 6.12 port includes tile wake, stitching, genlock, post-commit link
  recovery, the stitch-layer suspend fixes and the iMac Pro DCE 12 fixes.
- `audio`: the bundled iMac18,3 CS8409 driver requires **Linux 6.17+**. On
  Debian's stock 6.12 kernel it is `n/a`; existing installations remain
  removable. The patcher does not install a new kernel or substitute an older
  audio driver. On a supported newer kernel it uses APT, DKMS and
  `update-initramfs`.
- `eq`: requires working four-channel speakers, PipeWire, WirePlumber and the
  LSP LV2 plugins. Bankstown is built from its pinned source into `~/.lv2`.
  The iMac Pro uses `t2speakers` instead and needs a working T2 audio stack.
- `color`: uses KScreen on **Plasma Wayland**. GNOME colour settings are not
  implemented.
- `suspend`: the iMac18,3 hooks, DKMS USB fix and systemd s2idle policy apply;
  **systemd 256+** is required. `t2suspend` retains its requirement for a
  separately installed, working `t2bce` driver. Both modules block hibernation.
- `boot`, `macos`, and `igpu`: unavailable on Debian. The firmware-image edit
  and mkinitcpio hooks are specific to the existing Arch boot paths. HDR keeps
  its existing Omarchy/Hyprland requirements.

Offline tests cover APT selection, startup, ABI checks, installation, removal
and rollback. Both the graphics module and the USB sleep fix compile against
Debian `6.12.113+deb13-amd64`; the display port also applies to 6.12.38 at
zero fuzz. **Debian boot, display timing, physical audio and sleep remain
untested on hardware.** Compile validation is recorded in the development
notes; it does not establish those hardware results.

## Dependencies and building

The patcher offers missing packages through APT. To prepare manually:

```bash
sudo apt-get update
sudo apt-get install "linux-headers-$(uname -r)" build-essential binutils \
  bc pahole flex bison patch xz-utils curl ca-certificates tar python3 \
  libelf-dev libssl-dev initramfs-tools grub-common mokutil
./scripts/debian-imac5k --check
```

The running kernel must have its exact headers installed. The build reads
`${source:Version}` from `linux-headers-$(uname -r)` and downloads
`linux-source-<series>=<that version>` with APT, which verifies repository
hashes. This source tarball already includes Debian's kernel patches.
It never replaces a missing version with the newest source package. If an old
version is no longer available, update Debian, reboot, then retry.
There is no need to enable `deb-src` repositories.

The patch applies to a fresh temporary tree at `--fuzz=0`. Kbuild uses the
installed headers' configuration, compiler and `Module.symvers`; the full
module vermagic and `tiled_stitch` parameter are checked before installation.
Allow at least **10 GiB free** and roughly **20–40 minutes**. `IMAC5K_WORK`
sets the work directory and `IMAC5K_JOBS` limits build parallelism.

To build and inspect without installing:

```bash
./scripts/debian-imac5k --build
modinfo "$HOME/.cache/kernel-5k-build/debian-$(uname -r)/amdgpu.ko"
sudo ./scripts/debian-imac5k --install \
  "$HOME/.cache/kernel-5k-build/debian-$(uname -r)/amdgpu.ko"
```

## Installation and reboot

Installation adds `/lib/modules/<kernel>/updates/imac5k/amdgpu.ko.xz` and
`/etc/depmod.d/imac5k-<kernel>.conf`; the packaged module is preserved.
An initramfs hook, `/etc/initramfs-tools/hooks/imac5k-<kernel-id>` (`+` in the
release becomes `_` so initramfs-tools accepts the filename), explicitly
includes amdgpu for this kernel and keeps it included during later image
refreshes. It skips other kernel versions. Installation saves `/boot/initrd.img-<kernel>` under
`/var/lib/imac-patcher/5k-<kernel>/`, then builds and checks a new image with
`mkinitramfs` before replacing the boot image.

A new generator, `/etc/grub.d/09_imac5k-<kernel>`, adds an
**iMac 5K - <kernel>** entry. It copies the normal entry's root, encryption
and microcode settings, adds `amdgpu.tiled_stitch=1`, and removes
`video=eDP-1:...` only from that entry. It preserves other display arguments.
Other kernels keep their original arguments; a stock amdgpu module cannot
accept the patched-only parameter. `/etc/default/grub` and EFI bootloader
binaries are left alone. The generated menu is rebuilt with `grub-mkconfig`.

Reboot and **select the iMac 5K entry** in GRUB. A custom `GRUB_DEFAULT` or
saved selection may continue to choose your previous entry. Set the active
resolution to 5120×2880 in your desktop and run `./scripts/verify.sh`.
On KDE, apply `color` after this reboot because stitching changes the panel's
EDID identity.

**Reapply after every kernel update.** There is no automatic graphics rebuild
hook. Previous kernels remain available in GRUB as recovery options. New
entries copy the current GRUB settings; reapply after changing encryption,
root filesystem or microcode configuration too.

## Secure Boot

The graphics installer checks both kernel lockdown and Secure Boot. When
signatures are required, provide an existing enrolled key and DER certificate:

```bash
export IMAC5K_SIGN_KEY=/path/to/module-signing.key
export IMAC5K_SIGN_CERT=/path/to/enrolled-certificate.der
./scripts/imac-patcher --apply 5k
```

The module is stripped, signed with the matching headers' `sign-file`, then
compressed with XZ CRC32. The installer checks certificate enrollment first;
it does not disable Secure Boot. For `audio` and `suspend`, DKMS signs its own
modules. If its default `/var/lib/dkms/mok.pub` key is not enrolled, the patcher
prints the enrollment command; enroll it, reboot, then reapply. Set
`IMAC5K_DKMS_CERT` when DKMS uses a custom certificate; this only changes the
enrollment check, not DKMS configuration.

## Restore and recovery

While running the kernel you patched:

```bash
./scripts/imac-patcher --remove 5k
# Or directly, including when the patched GPU driver cannot load:
sudo ./scripts/debian-imac5k --restore
```

This removes that kernel's module override, depmod config, initramfs hook and managed GRUB
entry, restores its saved initramfs and rebuilds it with stock modules.
Build dependencies, signing keys and source downloads are unnecessary.
A failed rebuild retains the saved image and marks recovery incomplete so an
install cannot overwrite it; retry removal to finish.

If installation fails after starting system changes, it restores the saved
initramfs and GRUB menu and removes the override. For a hardware failure after
reboot, select another installed Debian kernel in GRUB. To restore the affected
kernel, boot it with `systemd.unit=multi-user.target nomodeset` appended for
that one boot, then run removal. Restore targets `uname -r`.

Debian's [kernel package handbook](https://kernel-team.pages.debian.net/kernel-handbook/ch-packaging.html)
describes its headers and source packages. Debian 13's kernel and desktop
versions are listed in the [release announcement](https://bits.debian.org/2025/08/trixie-released.html).
