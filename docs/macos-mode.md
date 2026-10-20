# macOS mode: working brightness with Intel graphics disabled

`imac-patcher --apply macos` enables Apple's firmware backlight path on the
iMac18,3. Since **0.3.1-alpha**, it blocks `i915`, so the Intel HD 630 exposes
no DRM graphics or render device. The Radeon handles the desktop and video.
The working brightness slider, optional full-range brightness table, SMBus
rule and brightness saving to Apple NVRAM are retained.

The firmware call needed for brightness also makes the Intel PCI function
visible at `00:02.0`. It can therefore still appear in `lspci`; blocking its
Linux driver keeps it unavailable to compositors and video applications.
Quick Sync and Intel VP9 acceleration are no longer enabled by this module.

## Apply or upgrade

```bash
imac-patcher upgrade
imac-patcher --apply macos
# Reboot, then check:
imac-patcher --status
```

Upgrading the patcher replaces the tool; **reapply `macos` and reboot** to
change the installed boot configuration. A previous release's installation
reports `partial` until updated. After applying, a still-bound Intel driver
or a remaining Intel DRM device also keeps the status `partial` until reboot.
The patcher never unloads a live graphics driver.

The module is offered only on **iMac18,3** with Omarchy/Limine or an
Arch-family GRUB installation using mkinitcpio. On GRUB, the installed
UEFI loader must support the kernel EFI stub (GRUB 2.12+); the preflight
checks the installed loader. Fedora/dracut and other models are unsupported.

## What is retained

- The `imac-setos` mkinitcpio post hook adds `iMac18,3` to the kernel EFI
  stub's Apple model list. The stub tells the firmware macOS is starting,
  which enables the ACPI backlight method. Kernel updates repeat the edit.
- `62-imac-smbus-acpi.rules` re-enables decoding on the SMBus controller used
  by the firmware's backlight writes. It is included in the initramfs, so
  it runs before brightness restoration.
- Where `iasl` and mkinitcpio's `acpi_override` hook are available,
  `make-bcl-table.py` builds and verifies the full-range brightness table.
  An unverifiable table is not installed; the firmware's own range is kept.
  Reapplying the module can add the full-range table later.
- `imac-backlight-nvram.service` saves the brightness level to Apple NVRAM
  at shutdown, preserving the level from power-on.
- The stable Radeon device names, Hyprland Radeon pin and headless VBT
  files remain compatible with existing installations and boot entries.
  These files do not enable Intel graphics while `i915` is blocked.
- The separate display, audio, colour and sleep patches keep their existing
  behavior and model restrictions.

Intel media-driver and VA-API diagnostic packages are no longer recommended
by the module. Existing packages are left installed.

## Boot configuration

The parameters are:

```text
snd_hda_core.gpu_bind=0 i915.disable_display=1 i915.vbt_firmware=imac18-3/headless-vbt.bin module_blacklist=i915,i2c_i801
```

`module_blacklist` is enforced by the kernel, so explicit module loads cannot
start `i915`. See [the kernel parameter documentation](https://www.kernel.org/doc/html/latest/admin-guide/kernel-parameters.html).
`snd_hda_core.gpu_bind=0` keeps the HD-audio controller independent of the
unbound Intel graphics driver. `i2c_i801` remains blocked so the firmware
owns the SMBus backlight path. The display-disable and VBT options are kept
for compatibility with earlier boot entries.

`/etc/mkinitcpio.conf.d/zz-imac-igpu.conf` keeps its existing filename for
upgrades but no longer prepends `i915` to the early modules. The SMBus rule
and compatibility VBT remain available in the initramfs.

On **Limine**, the parameters go in
`/etc/limine-entry-tool.d/imac5k-macos.conf`. The UKI is rebuilt, the post
hook edits it, and then Limine records its hash. Nothing edits the image
after its hash is recorded. An older in-place parameter block in
`/etc/default/limine` is removed when applying or removing the module.

On **GRUB**, the hook edits `/boot/vmlinuz-<pkgbase>`, leaving the packaged
kernel untouched. The parameters go in `GRUB_CMDLINE_LINUX`, including
recovery entries. Applying replaces the previous `module_blacklist=i2c_i801`
value rather than leaving two conflicting blacklist values. Removal restores
every edited `/boot/vmlinuz-*` before removing the hook and parameters.
Other boot arguments are retained.

## Recovery

From a TTY (ctrl-alt-F2) or SSH, run:

```bash
imac-patcher --remove macos
```

Then reboot. This removes the module's files and parameters and rebuilds the
boot image. Brightness returns to the stock firmware behavior.

If booting an older entry or snapshot that still enables Intel graphics,
ensure its kernel command line contains
`module_blacklist=i915,i2c_i801`. At Limine press `e` on the entry; on GRUB
press `e`, edit the `linux` line, and boot with ctrl-x.

If an ACPI override prevents reaching userspace, boot an installer USB,
chroot into the installation, remove
`/etc/mkinitcpio.conf.d/zz-imac-igpu.conf` and
`/etc/initcpio/acpi_override/imac-bcl100.aml`, then rebuild with
`limine-mkinitcpio` (Limine) or `mkinitcpio -P` (GRUB).

## Validation

The original firmware brightness path, NVRAM saving and repeated s2idle
sleep were verified on an iMac18,3 under Omarchy in September 2026. The
0.3.1-alpha iGPU-disabled configuration is covered by offline tests on both
boot backends, including upgrades, brightness retention and status checks;
it has not yet been reboot-tested on hardware. The GRUB path remains
untested on hardware.

The [historical iGPU guide](macos-igpu-history.md) preserves the original
implementation details, measurements and validation record through
0.3.0-alpha. Its Intel video instructions do not apply to this release.
