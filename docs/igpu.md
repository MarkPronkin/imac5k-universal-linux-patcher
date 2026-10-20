# Intel iGPU exposure (`igpu`, experimental)

`imac-patcher --apply igpu` independently enables the iMac18,3's headless
Intel HD 630 for Quick Sync video. It is **experimental and opt-in**: safe,
all, and non-experimental batch actions skip it, just as they skip HDR.
Brightness support does not require this module.

```bash
imac-patcher --apply igpu
# Reboot, then:
imac-patcher --status
```

Only iMac18,3 with Omarchy/Limine or Arch-family GRUB 2.12+ using mkinitcpio
is supported. Other iMac models and Fedora/dracut are not offered the patch.
The new independent module has offline coverage but is not yet boot-tested.
The underlying headless Intel configuration was previously verified in the
combined macOS-mode patch; see [the original record](macos-igpu-history.md).

## Independent installation

The module installs its own mkinitcpio configuration,
`/etc/mkinitcpio.conf.d/zz-imac-igpu-experimental.conf`, which loads `i915`
first with a no-outputs VBT. The Radeon continues driving the desktop; Intel
is available to video applications through its render device. The preflight
can offer `intel-media-driver` and `libva-utils` for Intel video and diagnostics.

It uses the same firmware-mode hook, headless VBT, stable DRM device-name
rules and Radeon compositor pin as the brightness patch. On Limine its own
parameters go in `/etc/limine-entry-tool.d/imac5k-igpu.conf`; on GRUB they go
in `GRUB_CMDLINE_LINUX`, including recovery entries.

**It installs no full-range brightness ACPI table or NVRAM save service.**
Those are owned by `macos`, which may be applied or removed independently.
The shared firmware call inevitably enables Apple's native backlight path
as well as exposing the Intel PCI function; the extra brightness features
remain separate.

## Coexistence and removal

- With only `macos`, `i915` is blocked. Brightness works without Intel graphics.
- With only `igpu`, Intel graphics is enabled; no full-range brightness table
  or NVRAM save service is installed.
- With both, brightness and Intel graphics coexist. Reapplying brightness
  preserves the explicit Intel opt-in.
- `imac-patcher --remove igpu` retains the brightness table, SMBus rule,
  NVRAM service and firmware hook if `macos` is installed, and blocks Intel
  graphics again on the next boot.
- `imac-patcher --remove macos` removes its table and NVRAM service but
  retains a separately enabled `igpu` installation.
- Removing the last of the two modules restores the plain firmware boot
  and removes shared files. On GRUB the edited kernels are restored first.

Reboot after apply/remove. A live graphics driver is never unloaded by the
patcher. Status stays `partial` until the installed configuration and running
hardware state agree.

## Recovery and limitations

At the boot menu, set `module_blacklist=i915,i2c_i801` to disable Intel for
that boot while retaining the firmware brightness path. At Limine press `e`
on the entry; on GRUB edit the `linux` line with `e` and boot with ctrl-x.
From a TTY or SSH, run `imac-patcher --remove igpu` and reboot.

The VBT and Radeon pin keep Intel from driving the display. Applications
still need cross-GPU support to display frames decoded by Intel on the
Radeon desktop; exposure alone does not make every browser use Quick Sync.
The [historical video measurements](macos-igpu-history.md) record what was
verified in the previous combined implementation.
