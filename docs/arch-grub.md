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
macOS mode (`macos`) is available on this backend; see
[below](#macos-mode-the-igpu-and-brightness).

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

Both sleep modules allow suspend and keep hibernate blocked, and remove the
retired `idle=poll` parameter through GRUB if present. On the iMac18,3,
`suspend` installs the Thunderbolt and Wi-Fi sleep hooks and a systemd drop-in
that makes suspend use s2idle (deep S3 resets on this hardware), and builds the
`imac5k-xhci-d0` USB controller fix through DKMS for every installed kernel with
headers (with Clang on a Clang-built kernel such as CachyOS's) and loads it at
boot; without it every second sleep resets the machine. On T2 models (iMac Pro,
2020 iMacs), `t2suspend` requires `linux-t2`'s `t2bce` driver, refuses while
anything unloads the T2 driver around sleep, installs only the Thunderbolt hook
and keeps the kernel's sleep mode. The 2014-2015 models sleep with the stock
kernel and need neither. Read the suspend section of the
[README](../README.md) before applying either.

## macOS mode: the iGPU and brightness

On the iMac18,3, `imac-patcher --apply macos` works on this backend too. The
Intel HD 630 is exposed for video, and the brightness keys dim the panel, over
its full range where the ACPI table can be rebuilt. It installs what it does
on Omarchy (see [macOS mode](macos-mode.md#on-arch-family-grub)), with three
differences:

- The mkinitcpio hook edits `/boot/vmlinuz-<pkgbase>`, the image GRUB loads,
  each time mkinitcpio runs, kernel updates included. The packaged kernel is
  never touched.
- The four kernel parameters go in `GRUB_CMDLINE_LINUX` rather than
  `GRUB_CMDLINE_LINUX_DEFAULT`, so recovery entries, which boot the same edited
  image, get them too.
- `imac-patcher --remove macos` restores every edited `/boot/vmlinuz-*`
  before it removes anything else, because rebuilding the initramfs never
  re-copies the kernel.

It needs **GRUB 2.12 or newer as installed on the ESP**: older builds start
Linux without its EFI stub, and the stub is what makes the firmware call. The
preflight reads `/boot/grub/x86_64-efi/linux.mod`, the loader `grub-install`
copied there, and refuses an older one. Upgrading the `grub` package does not
update it; run your `grub-install` command again. As for 5K, the kernel in
`/boot` must be the running one. A kernel carrying only this edit still
counts as the running one for the 5K preflight and the test-entry helpers
below.

If the desktop does not come back, press `e` at the GRUB menu, append
`module_blacklist=i915` to the line that starts with `linux`, and boot with
ctrl-x. This path has offline test coverage only and has not been booted on
hardware yet.

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
