# Ubuntu 26.04 LTS

Ubuntu **26.04 LTS (Resolute Raccoon), amd64**, with GRUB and initramfs-tools
has an APT backend. Run the patcher as your desktop user:

```bash
./scripts/imac-patcher --status
./scripts/imac-patcher --apply 5k
```

Ubuntu is detected by `ID=ubuntu` in `/etc/os-release`. Other `ID_LIKE`
derivatives are not automatically supported. The initial target is Ubuntu
26.04's **Linux 7.0 generic** kernel; older LTS kernels such as 6.8 need a
separate patch port. The installer accepts the 7.0, 7.1 and 7.2 series using
official generic/HWE headers and exact matching Ubuntu sources. OEM, cloud,
lowlatency, mainline PPA and third-party kernels need their own integration.
It does not install or switch kernels. Limine, UKI-only, systemd-boot and
dracut layouts are unsupported by this graphics backend.

## Modules and validation

The [model restrictions](../README.md#compatibility) apply on Ubuntu too.

- `5k` requires `amdgpu`. The lean 7.0 port includes panel wake, stitching,
  cursor, genlock, link recovery, suspend/resume and the iMac Pro timing fixes.
  `IMAC5K_STACK=verbose` is unavailable on the APT backend.
- `audio` uses DKMS and initramfs-tools for the iMac18,3 CS8409 driver. It
  requires Linux 6.17+, which Ubuntu 26.04's 7.0 kernel satisfies. It installs
  the exact matching `linux-source` package and retains a DKMS source-version
  guard for future rebuilds; if the source archive has since been replaced by
  another ABI's version, rebuild stops with the exact package to install.
  Audio and the USB sleep fix also install `zstd` for DKMS compression.
- `eq` requires working four-channel audio, PipeWire, WirePlumber and the
  LSP LV2 plugins; Bankstown builds from its pinned source into `~/.lv2`.
  The iMac Pro uses `t2speakers` with an independently working T2 audio stack.
- `color` supports **Plasma Wayland**, including Kubuntu's desktop. GNOME
  colour settings are not implemented.
- `suspend` remains specific to iMac18,3 and requires systemd 256+; `t2suspend`
  needs a working T2 kernel/driver stack. Both block hibernation. The generic
  graphics backend does not provide the T2 drivers.
- `boot`, `macos` and `igpu` are unavailable on Ubuntu. HDR retains its
  existing Omarchy/Hyprland requirements.

Build and filesystem validation use isolated Ubuntu userspace on a different
host distribution. Graphics, CS8409 audio and the XHC1 USB sleep module
compile for `7.0.0-38-generic`; graphics installation and restoration pass with
Ubuntu's real depmod and initramfs tools. Signed, compressed audio installation
and removal also pass through Ubuntu's real DKMS. See the
[validation record](../notes/ubuntu-support-2026-10-26.md).
**Ubuntu hardware boot, active 5K,
Secure Boot loading, physical audio and repeated suspend still require
hardware testing.**

## Dependencies and exact kernel sources

The patcher offers missing packages through APT. To prepare graphics manually:

```bash
sudo apt-get update
sudo apt-get install "linux-headers-$(uname -r)" build-essential binutils \
  bc pahole flex bison patch xz-utils bzip2 curl ca-certificates tar python3 \
  libelf-dev libssl-dev initramfs-tools grub-common mokutil
./scripts/ubuntu-imac5k --check
```

The running kernel needs its exact headers. The source version comes from
`${source:Version}` of `linux-headers-$(uname -r)`, rather than the signed
image package or a guess from the ABI name. For example, `7.0.0-38-generic`
uses `linux-source-7.0.0=7.0.0-38.38`. HWE source versions retain their full
suffix. APT verifies the package against its repository metadata; `deb-src`
is unnecessary. If the exact source version has left the repositories,
update Ubuntu, reboot and retry. A newer source is not substituted.

Ubuntu's source archive includes its downstream patches. The patcher applies
the selected stack to a fresh tree at `--fuzz=0` and builds with the installed
headers' configuration and `Module.symvers`. Full module vermagic, name and
the stitch parameter must match before installation. Allow **10 GiB free**
and roughly **20–40 minutes**; `IMAC5K_WORK` sets the build directory and
`IMAC5K_JOBS` limits parallelism.

To build without installing:

```bash
./scripts/ubuntu-imac5k --build
modinfo "$HOME/.cache/kernel-5k-build/ubuntu-$(uname -r)/amdgpu.ko"
```

## Installation and reboot

The shared Debian/Ubuntu transaction installs a per-kernel module override at
`/lib/modules/<kernel>/updates/imac5k/amdgpu.ko.xz`, a depmod configuration and
an initramfs hook that includes amdgpu only for that exact kernel. It saves
the original image under `/var/lib/imac-patcher/5k-<kernel>/`, then builds and
checks the replacement image with `mkinitramfs` and `lsinitramfs`.

A separate **iMac 5K - <kernel>** GRUB entry inherits the normal entry's root,
encryption and microcode settings. Only this entry gains
`amdgpu.tiled_stitch=1` and loses an internal-panel `video=eDP-1:...` override.
Select it after reboot, set 5120×2880 in your desktop and run
`./scripts/verify.sh`. A custom GRUB default or saved selection can continue
to choose the old entry. On Plasma, apply `color` after reboot because the
stitched panel has a different EDID identity.

**Reapply after every kernel update** and after changing root, encryption or
microcode boot settings. Graphics has no automatic DKMS rebuild hook. Keep
another installed Ubuntu kernel available in GRUB for recovery.

## Secure Boot

The graphics installer checks Secure Boot and kernel lockdown. When signing
is required, supply an existing enrolled key and DER certificate:

```bash
export IMAC5K_SIGN_KEY=/path/to/module-signing.key
export IMAC5K_SIGN_CERT=/path/to/enrolled-certificate.der
./scripts/imac-patcher --apply 5k
```

The module is stripped, signed with the matching headers' `sign-file`, then
compressed with XZ CRC32. The installer checks certificate enrollment first.
For `audio` and `suspend`, DKMS signs its modules. Ubuntu normally uses
`/var/lib/shim-signed/mok/MOK.der`; if the generated key is not enrolled, the
patcher prints the `mokutil --import` command. Enroll it, reboot and confirm
in MOK Manager, then reapply. If DKMS uses a custom certificate, set
`IMAC5K_DKMS_CERT` to that certificate for the enrollment check; this variable
does not change DKMS's own signing configuration.

## Restore and recovery

While running the kernel you patched:

```bash
./scripts/imac-patcher --remove 5k
# Directly, including when amdgpu cannot bind:
sudo ./scripts/ubuntu-imac5k --restore
```

Removal restores the saved image, removes the override, hook and managed
entry, and rebuilds with stock modules. It needs no source download, compiler
or signing key. Failed installation restores the previous module selection,
image and menu; incomplete recovery retains the backup and blocks another
install until removal finishes.

If the desktop cannot start after reboot, select another installed Ubuntu
kernel in GRUB. To restore the affected kernel, boot it with
`systemd.unit=multi-user.target nomodeset` appended for that one boot, then
run removal. Restore targets `uname -r`.

Canonical documents Ubuntu 26.04's Linux 7.0 base in its
[release announcement](https://canonical.com/blog/canonical-releases-ubuntu-26-04-lts-resolute-raccoon)
and its source/headers workflow in the
[kernel build guide](https://documentation.ubuntu.com/kteam-docs/public/how-to/build-kernel.html).
