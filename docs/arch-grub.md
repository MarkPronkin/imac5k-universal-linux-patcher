# Arch-family GRUB support

Arch Linux, EndeavourOS, CachyOS and other distributions declaring
`ID_LIKE=arch` can use the 5K installer with **GRUB and mkinitcpio**. This
backend has offline regression coverage, and the install-and-boot path is
hardware-validated on CachyOS — iMac18,3, `linux-cachyos` 7.2.3, KDE Plasma
Wayland — where native 5K, audio, speaker tuning, colour and the sleep block
all come up after the reboot. The staged test entries and promotion described
below have not been exercised on hardware, and neither has EndeavourOS or plain
Arch, though both use this same backend.

## Supported setup

- A compatible Retina 5K iMac using amdgpu, with kernel **7.1.x or 7.2.x**.
- `/etc/default/grub` and the generated `/boot/grub/grub.cfg`.
- A mkinitcpio preset and regular `/boot/vmlinuz-<pkgbase>` and
  `/boot/initramfs-<pkgbase>.img` files for the running kernel.
- Matching kernel headers. The package comes from the kernel’s `pkgbase`
  metadata: for example, `linux-cachyos` needs `linux-cachyos-headers`.

A distro name alone does not establish support: an EndeavourOS or CachyOS
installation using dracut, systemd-boot or only UKIs needs a different boot
backend. The patcher does not convert those installations. Boot repair
(`boot`) remains specific to Omarchy/Limine and reports **n/a** on GRUB.

Detection prefers Fedora’s backend first, then `/etc/default/limine`, then
Arch-family `/etc/default/grub`. If both bootloader configs exist, Limine wins.
An installed Limine command does not select the Limine backend on GRUB.

## Apply and restore

```bash
./scripts/imac-patcher --status
./scripts/imac-patcher --apply 5k
# Reboot to load the patched module.
./scripts/imac-patcher --remove 5k
```

The installer uses kernel.org driver sources and the exact installed Kbuild
headers/configuration. Clang-built kernels use LLVM tools, including their
LTO settings. A failed build or mismatched module vermagic stops installation.
Distribution-specific source changes may still require a patch port; the
kernel-series restriction remains in force.

Applying adds `amdgpu.tiled_stitch=1` to the existing GRUB kernel arguments,
rebuilds the initramfs, and regenerates GRUB. Removing restores the stock
module and removes that argument. Other parameters, including encrypted-root
and external-display options, are preserved. Single- and double-quoted
assignments are supported; computed or multiline command-line assignments
are refused with an explanation before installing the driver.

The preflight offers missing build tools and the correct headers package.
After a kernel update, reboot into the installed kernel before applying or
promoting a module. The patched module needs to be rebuilt for each new kernel.

The suspend module allows suspend and keeps hibernate blocked. Through GRUB it
adds `mem_sleep_default=s2idle` to the kernel arguments (deep S3 resets on wake
on this hardware) and removes the retired `idle=poll` parameter if present; it
also installs the Thunderbolt sleep hook. Read the suspend section of the
[README](../README.md) before applying it.

## Test entries

To try a supplied module while keeping the normal kernel image intact:

```bash
sudo ./scripts/imac-alt-entry add trial /path/to/amdgpu.ko
sudo ./scripts/imac-alt-entry list
# Select /Test - trial in the GRUB menu, then evaluate that boot.
sudo ./scripts/imac-alt-entry promote trial
# Or discard it:
sudo ./scripts/imac-alt-entry drop trial
```

Each named entry gets `/boot/initramfs-<pkgbase>-imac-<name>.img` and a marked
block in `/etc/grub.d/40_custom`. It clones the normal entry for that kernel
package, preserving GRUB’s root, encryption, btrfs and microcode paths. It has
a unique menu ID and does not save itself as the default. `IMAC_CMDLINE` is
Limine-only; GRUB entries inherit the generated kernel arguments.

`imac-test-entry stage /path/to/known-good-amdgpu.ko.zst` instead captures the
currently installed module in the `5ktest` slot and installs the supplied
known-good module in the normal image. Its `promote`, `drop` and `status`
commands manage that slot. Both helpers verify the module inside rebuilt
images. Promotion keeps the previous module beside the installed one as
`.prev-promote`; staging keeps `.prev-stage`.

Use a distinct name for each test. Re-adding a name replaces its marked
entry. Test images belong to one kernel version; remove them before upgrading
that kernel and create fresh entries afterwards. Listing images under a new
kernel does not make old modules compatible.

## Restore and recovery

If a test fails to boot, select the normal entry in GRUB. To undo a regular
5K installation, boot a usable session and run `imac-patcher --remove 5k`.
The installer retains `amdgpu.ko*.stock-backup` beside the installed module.

GRUB file edits keep timestamped backups and restore the previous input and
generated menu if regeneration fails. Backups of `40_custom` are deliberately
not executable, so GRUB cannot run them as extra menu generators. A failed
promotion keeps the previous module, test entry and test image for recovery;
read the reported error before rebooting.

If manual boot-configuration recovery is necessary, restore the appropriate
`/etc/default/grub.backup-*` or `40_custom.backup-*` file, then regenerate with
`sudo grub-mkconfig -o /boot/grub/grub.cfg`. Restoring a module also requires
`sudo depmod <kernel-release>` and `sudo mkinitcpio -P`. These are recovery
commands for the target GRUB installation, not development checks.

CachyOS documents the same GRUB command-line configuration and regeneration
path in its [boot manager guide](https://wiki.cachyos.org/configuration/boot_manager_configuration/#kernel-commandline-configuration).
