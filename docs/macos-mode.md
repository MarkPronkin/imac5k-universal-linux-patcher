# macOS mode: the Intel iGPU and a backlight that works

`imac-patcher --apply macos` makes the kernel tell Apple's firmware that macOS
is starting. On the iMac18,3 that single call changes two things at once, which
is why they are one module and not two:

- the firmware stops hiding the **Intel HD 630** at `00:02.0`, and
- its own ACPI backlight path starts driving the panel, so **`acpi_video0`
  actually dims it** instead of accepting writes and doing nothing.

The Radeon Pro 575 keeps the display, the compositor and all 3D. The Intel chip
never drives an output; it encodes and decodes video, the way macOS runs it
(`NumFrameBuffer 0`, Quick Sync).

**Status: confirmed on an iMac18,3 under Omarchy, 2026-09-21**, on kernel
7.2.5-3-omarchy. Ported from
[ahmadtv/omarchy-imac18-3](https://github.com/ahmadtv/omarchy-imac18-3), where
every stage was developed and verified first.

What the first boot showed here:

| | |
|---|---|
| Intel HD 630 | present at `00:02.0`, i915 bound, **no connectors at all** — the headless VBT did its job, no eDP invented on DDI A |
| Quick Sync | `renderD128`, the first render node, so it is the default for video: H.264 encode (including low-power), HEVC Main and Main10 encode and decode |
| Radeon | keeps `boot_vga`, the panel and the compositor — Hyprland holds `card2`/`renderD129` only, so the `AQ_DRM_DEVICES` pin took |
| Audio | CS8409 still ALSA card 0 with the EQ chain running, no Intel HDMI codec: `snd_hda_core.gpu_bind=0` did its job |
| Brightness | **the panel dims**, confirmed by eye — it never did on this machine before |
| Power | the iGPU runtime-suspends to D3hot, rc6 residency climbing |
| NVRAM | `backlight-level` written at shutdown, so the panel lights at the saved level from power-on |

**Two s2idle cycles in one boot passed with macOS mode enabled** — see
[Suspend](#suspend-which-was-the-open-question) below for the validation limits.

**Arch-family GRUB** (Arch, CachyOS, EndeavourOS with mkinitcpio) gets the same
module, iGPU and brightness alike, through the kernel image GRUB loads
instead of a UKI — see [On Arch-family GRUB](#on-arch-family-grub). That path
is covered by offline tests but **has not been booted on hardware yet**.

## How the firmware is told

The x86 EFI stub already makes the call. `apple_set_os()` in
`drivers/firmware/efi/libstub/x86-stub.c` runs from `efi_stub_entry()` for the
models listed in `apple_match_product_name()`:

```c
static const char type1_product_matches[][15] = {
	"MacBookPro11,3", "MacBookPro11,5", "MacBookPro13,3",
	"MacBookPro14,3", "MacBookPro15,1", "MacBookPro15,3",
	"MacBookPro16,1", "MacBookPro16,4",
};
```

Eight fixed-width slots, stored uncompressed in the stub — they are plainly
visible in `/usr/lib/modules/$(uname -r)/vmlinuz`. Rather than rebuild a whole
kernel for a fourteen-byte change, `scripts/imac-setos` is installed as a
mkinitcpio post hook at `/etc/initcpio/post/imac-setos` and rewrites the last
slot to `iMac18,3` in every UKI mkinitcpio builds, kernel updates included.
The bytes are exactly what the one-line source patch would compile to.

The ordering this depends on holds on Omarchy and is checked after every apply:

1. `limine-mkinitcpio` builds the UKI,
2. mkinitcpio runs its post hooks on the image it just built — the edit lands,
3. `limine-entry-tool` then registers it and pins its **BLAKE2B hash** in
   `limine.conf`, which is set to `hash_mismatch_panic`.

Nothing may modify a UKI after step 3, so the module never edits an image
out of band: every change goes through a rebuild. If a future kernel moves or
reshapes the model list, the hook prints a warning and leaves the image stock
rather than failing a kernel update, and the patcher reports that the edit did
not land.

The upstream fix is to add `"iMac18,3"` to that list; the hook goes away once a
kernel carries it.

### On Arch-family GRUB

GRUB loads a plain kernel image, not a UKI, so the edit goes into that image:
`/boot/vmlinuz-<pkgbase>`, the copy GRUB's menu entries name. It only counts if
GRUB starts that image through its EFI stub, and GRUB 2.12 and later do: on
x86_64 EFI they hand the kernel to the firmware's LoadImage/StartImage, whose
entry point, `efi_pe_entry()`, runs the same `efi_stub_entry()` →
`setup_quirks()` → `apple_set_os()` path a UKI takes. ("Transition to EFI
Linux kernel stub loader for x86 architecture" in GRUB 2.12's release notes;
Arch ships 2.14, with no patch to the loader.) Earlier builds boot Linux with
the legacy x86 protocol, jump past the stub, and set_os never runs.

What counts is the GRUB that `grub-install` last put on the machine, not the
installed package: upgrading the package does not reinstall it. The preflight
therefore reads `/boot/grub/x86_64-efi/linux.mod`, the loader module
`grub-install` copies there. A build with the EFI-stub loader names its source
file, `loader/efi/linux.c`, inside the module. Checked against Arch's own
packages: `2.06.r499` and older lack it, `2.06.r591` and every 2.12+ build
carry it. The module is refused on an older GRUB, with a pointer to
`grub-install`, and when the machine did not start through UEFI at all. GRUB
still takes the legacy path when an old shim without its loader protocol
started it; these iMacs have no Secure Boot for a shim to be needed.

The hook keeps the edit through kernel updates the same way. The Arch preset
sets `ALL_kver="/boot/vmlinuz-<pkgbase>"`, so mkinitcpio passes that copy to
post hooks as the kernel image, and pacman's mkinitcpio hook re-copies it from
the package's `/usr/lib/modules/<version>/vmlinuz` before every build of a new
kernel. The hook edits only a regular file under `/boot` whose name starts with
`vmlinuz-`. The packaged image, which is what `limine-mkinitcpio` hands it,
and anything reached through a symlink are left alone. Nothing pins a hash, so
no bootloader configuration has to follow the edit.

Two things differ from Limine, both handled by the module:

- **The parameters go in `GRUB_CMDLINE_LINUX`.** Recovery entries are built
  from that variable alone, without `GRUB_CMDLINE_LINUX_DEFAULT`, and they boot
  the same edited image. An i915 started without its VBT there would create the
  phantom eDP port described below.
- **Removal has to undo the edit.** A UKI is rebuilt from the packaged kernel,
  but rebuilding the initramfs never re-copies a GRUB kernel.
  `imac-patcher --remove macos` therefore puts `MacBookPro16,4` back in every
  `/boot/vmlinuz-*` that carries the edit before it removes anything else. If
  that fails, the install is left whole rather than an edited kernel without
  its parameters.

A `/boot` kernel that differs from the package by exactly this edit still
counts as the running kernel for every check that compares the two. Those are
the 5K preflight and the GRUB `imac-alt-entry` and `imac-test-entry` helpers.

## What gets installed

| File | Installed as | Why |
|---|---|---|
| `scripts/imac-setos` | `/etc/initcpio/post/imac-setos` | The set_os model-list edit, reapplied on every kernel update |
| `configs/macos/zz-imac-igpu.conf` | `/etc/mkinitcpio.conf.d/` | i915 first in the initramfs, with the VBT and the SMBus rule |
| `configs/macos/headless-vbt.bin` | `/usr/lib/firmware/imac18-3/headless-vbt.bin` | A valid VBT that declares no outputs |
| `configs/macos/61-imac-dri-names.rules` | `/etc/udev/rules.d/` | Stable `/dev/dri/{amd,intel}-{card,render}` names |
| `configs/macos/62-imac-smbus-acpi.rules` | `/etc/udev/rules.d/` and the initramfs | Re-enables the SMBus controller the firmware's backlight method uses |
| `scripts/make-bcl-table.py` | builds `/etc/initcpio/acpi_override/imac-bcl100.aml` | The brightness table, extended from 80% to the full range |
| `scripts/imac-backlight-nvram` + `configs/macos/imac-backlight-nvram.service` | `/usr/local/bin/`, `/etc/systemd/system/` | Saves the level to Apple NVRAM at shutdown |
| `configs/macos/imac-gpu.lua` | `~/.config/hypr/` plus a `require` in `hyprland.lua` | Keeps Hyprland on the Radeon |
| — | `/etc/limine-entry-tool.d/imac5k-macos.conf` on Limine, `GRUB_CMDLINE_LINUX` in `/etc/default/grub` on GRUB | The four kernel parameters |

The kernel parameters are
`snd_hda_core.gpu_bind=0 i915.disable_display=1
i915.vbt_firmware=imac18-3/headless-vbt.bin module_blacklist=i2c_i801`.
On Limine they are written as a drop-in that **appends** with `+=`. Omarchy's
`/etc/default/limine` appends too, and the entry tool reads both; editing that
file's line in place matches nothing there. On GRUB they are added to
`GRUB_CMDLINE_LINUX` in one edit, the file is backed up first, and `grub.cfg`
is regenerated. Other arguments, quoting and comments are kept, as for the 5K
parameter.

Everything else is the same on both. The Hyprland pin is installed wherever an
Omarchy-style `~/.config/hypr/hyprland.lua` exists. KDE Plasma gets none, and
by KWin's source needs none: KWin skips any DRM device that libdrm's
`drmIsKMS()` rejects, which takes at least one connector, and the headless VBT
leaves the HD 630 with none. That is read from the source, not yet seen on
hardware.

`scripts/imac-igpu-check` is a read-only status report — run it after the first
reboot. `sudo` adds i915 parameters, DMC and runtime-PM detail.

## Why a VBT and not just `disable_display=1`

`i915.disable_display=1` gates connector `detect()` and hotplug polling. It does
**not** stop connectors being created. This iMac's OpRegion has an empty VBT
mailbox, and with no VBT `init_vbt_missing_defaults()` makes every DDI port a
connector and marks port A internal — so i915 runs eDP AUX and panel-power
sequencing on DDI A at probe. That is exactly what blanked the AMD-driven panel
in the one upstream attempt at this on an iMac20,1 (Atharva Tiwari, Jan–Feb
2026, unmerged).

`i915.vbt_firmware=` takes precedence over the OpRegion, and a valid VBT with an
empty BDB has no child devices, so `intel_setup_outputs()` iterates an empty
encoder list: no connectors, no AUX, no PPS, while the display engine is still
initialised and can still reach DC5/DC6. `scripts/make-headless-vbt.py` builds
the 70-byte file and checks it against the same conditions
`intel_bios_is_valid_vbt()` applies; `configs/macos/headless-vbt.bin` is its
committed output, and a test rebuilds it and compares. `vbt_firmware` is an
"unsafe" module parameter, so the kernel is tainted `U` — expected.

`snd_hda_core.gpu_bind=0` is not optional. Once the iGPU is visible,
`snd_hdac_i915_init()` waits for i915 to bind and defers the whole PCH
HD-audio controller — the speakers and mics go with it.

## Brightness

Two separate things, and the module can deliver the first without the second.

**Working brightness** comes from set_os alone. Omarchy's `omarchy-hw-display`
already picks `acpi_video0`, so the brightness keys and the OSD need no change.
Neither should KDE Plasma's: PowerDevil takes a `firmware`-type backlight
before any other, and `acpi_video0` is one. That is read from PowerDevil's
source and not yet confirmed on hardware.

**The full range** needs the firmware's ACPI table rewritten. Apple's `_BCL`
(named `ABCL` in the PEG0GFX0 SSDT) stops at level 80 while its own setter
`BSET(level)` scales `655 * level` onto the controller's 0..0xFFFF range, so
Linux's 100% is 52400 — 80% of what macOS drives. `scripts/make-bcl-table.py`
reads the machine's own table, rewrites only ABCL to levels 4..100, bumps the
OEM revision and compiles it for mkinitcpio's `acpi_override` hook. Apple's
table never leaves the machine. That hook puts the table in the uncompressed
early archive at the front of the initramfs, which the kernel searches however
the initramfs arrived. It works from GRUB's `initrd` line, microcode image
first included, exactly as from inside a UKI.

Nothing on the kernel command line can switch an initramfs ACPI override back
off, which makes a bad table the one failure in macOS mode with no boot-time
escape. Two checks stand in front of writing one:

- the disassembled table must have the exact shape this firmware is known to
  have (ABCL = 80 levels starting at `0x50`), and
- `iasl` must round-trip the **untouched** table: every definition in it has
  to come back identical through a disassemble–compile–disassemble cycle,
  before a modified table built the same way is trusted. Bytes are
  deliberately not compared. The disassembler adds `External` declarations for
  names defined in other tables, those are encoded into the AML at about ten
  bytes each, and the interpreter skips them — so a faithful rebuild of this
  machine's table is legitimately 124 bytes larger than the firmware's.

What finally gets installed is checked once more the same way: its
disassembly must differ from the original's by nothing but the ABCL package
and the OEM revision.

If either fails, or `iasl` is not installed, the module says so and installs no
table. Brightness still works; it just tops out where the firmware's own table
does. Nothing else about macOS mode changes, and the install counts as
complete — that is a supported end state, not a half-finished one.

To add the table later, install `acpica` and run `imac-patcher --apply macos`
again. An already-applied module is normally skipped; this one tops up the
brightness range instead, rebuilds the boot image and asks for a reboot. The
status listing says so too, but only when all of it is actually available.

Finally, `imac-backlight-nvram` writes the level to Apple's `backlight-level`
EFI variable at shutdown, so the firmware lights the panel at your level from
power-on instead of jumping mid-splash when systemd-backlight restores it. It
writes only when the value changed (firmware flash wear) and keeps only the
standard attribute bits, because efivarfs rejects Apple's vendor bit.

## Which GPU does what

DRM minors are handed out in probe order, and i915 now loads first from the
initramfs, so the HD 630 takes `renderD128`: anything that opens "the first
render node" gets Quick Sync with no configuration. Measured here, ffmpeg
with no device named reports *"Trying to use DRM render node for device 0"*
and loads `iHD_drv_video.so`.

There are two defaults, not one, and the difference is by design:

| A client that asks for | Gets |
|---|---|
| a DRM display with no device (`vainfo --display drm`, ffmpeg, anything opening a render node) | **Intel** |
| a Wayland display (`vainfo` with no arguments, clients going through the compositor) | **the Radeon** — libva opens the compositor's GPU there, which is what the pin makes it |

So "the iGPU is the default video device" is true of the DRM path and false
of the Wayland one, and no setting changes that: libva has no device-selection
variable (intel/libva#221 and #752, both open, no code), and
`LIBVA_DRIVER_NAME` is not one — it applies to every display and would break
VA-API on the Radeon. Upstream's measurements on
this hardware — identical sources, matched bitrate targets — put H.264 encode
at about 3.7× the Radeon's rate, reaching the same VMAF with a third fewer
bits, plus VP9 and 10-bit HEVC decode the Polaris card does not have.

The compositor must not follow. Hyprland/aquamarine opens every KMS device
unless told otherwise, so `imac-gpu.lua` sets
`AQ_DRM_DEVICES=/dev/dri/amd-card` — guarded, because an entry that does not
exist leaves aquamarine with no GPU at all. Wayland, GL and Vulkan clients
follow the compositor and stay on the Radeon.

What the HD 630 offers here, in full — `vainfo` reports 32 profile and
entrypoint pairs:

- **decode:** H.264 (Baseline, Main, High), HEVC Main and **Main10**, VP9
  Profile 0 and **Profile 2**, VP8, VC-1 (all three), MPEG-2, JPEG
- **encode:** H.264 (plus a low-power path), HEVC Main and **Main10**, VP8,
  MPEG-2, JPEG

Against the Radeon that adds VP9 and VP8 decode, VC-1 aside, and HEVC Main10
*encode*, none of which Polaris has. Kaby Lake has no AV1 at all and no VP9
encode, and tops out near 4096x2304, so 5K captures must be scaled before
encoding on either chip.

| Application | Device |
|---|---|
| ffmpeg, GStreamer, Strata | Intel by default; `-init_hw_device vaapi=amd:/dev/dri/amd-render` for the Radeon |
| gpu-screen-recorder | Always the Radeon: it encodes on the GPU it captures from |
| OBS, Kdenlive | Choose the VA-API device in their settings |
| Chromium | Its active GPU (the Radeon). Pointing it at Intel makes the HD 630 decode, but the Radeon cannot import the frames |
| Firefox | The compositor's GPU, the Radeon — measured: it holds `renderD129` and nothing else, and `about:support` lists hardware decoding for H.264 and HEVC but not VP9 |
| mpv | Intel by default, and VP9 with it: `--hwdec=vaapi-copy --vaapi-device=/dev/dri/intel-render` is confirmed working here |

### Why VP9 is still software-decoded in the browser

The chip decodes VP9 and the Radeon does not — `ffmpeg -hwaccel vaapi
-hwaccel_device /dev/dri/renderD128` decodes a VP9 file here, and the same
command on `renderD129` fails with *"hwaccel initialisation returned error"*.
mpv gets it too, in copy mode.

A browser does not, because it renders on the compositor's GPU and a frame
decoded on one GPU has to be imported by the other to be drawn. Firefox has
closed cross-GPU video decode as WONTFIX, and Chromium fails the import with
`eglCreateImage failed`. The only lever for Firefox is `MOZ_DRM_DEVICE`,
which moves **all** of its DMABuf use to the Intel chip rather than just
video — every window it draws would then be composited across the two GPUs.
It is worth an experiment on a throwaway profile, not a default:

```bash
MOZ_DRM_DEVICE=/dev/dri/intel-render firefox --new-instance --profile "$(mktemp -d)"
```

For YouTube specifically, an extension that forces H.264 gets hardware
decoding on either chip today. AV1 is absent from both, and that one is a
plain hardware limit.

### Except in a WebKit browser, where it works

Tested 2026-09-21 with Epiphany (WebKitGTK 6.0) and `gst-plugin-va`
installed: **VP9 decodes on the Intel chip and displays through the Radeon,
in a browser.** The `WebKitWebProcess` playing the video holds both
`/dev/dri/renderD128` and `/dev/dri/renderD129` at once, the Intel GT runs
10–12% busy instead of idle, and the picture is correct — none of the green
or corrupted output the Mozilla bug reports from cross-GPU attempts.

WebKit decodes through GStreamer, and GStreamer is the only stack here that
is multi-device by design. Its `va` plugin enumerates every render node and
names the extra ones after theirs, so on this machine the unprefixed
elements — the ones with default rank — are the Intel ones:

```
va:  vah264dec: VA-API H.264 Decoder in Intel(R) Gen Graphics
va:  vavp9dec:  VA-API VP9 Decoder in Intel(R) Gen Graphics
va:  varenderD129h264dec: VA-API H.264 Decoder in AMD Radeon Pro 580X in renderD129
```

`decodebin` picks `GstVaVp9Dec` on its own, so no configuration is needed at
all; `GST_PLUGIN_FEATURE_RANK=varenderD129h264dec:MAX` is how to send a codec
back to the Radeon if that is ever wanted. On Arch the plugin is its own
package, `gst-plugin-va` — it is **not** in `gst-plugins-bad`.

Cost, measured on one stream rather than a benchmark: the web process sat at
about a third of one core with everything included — decode, page rendering,
compositing, the cross-GPU copy and audio. Upstream measured 4K VP9 on the
CPU at about 1.1 cores, so the copy does not eat the saving. What has not
been measured is power, or how this scales to 4K60.

**Fullscreen is black.** Windowed playback is correct; going fullscreen
leaves a black picture with the audio still playing. Decoding is not what
breaks — sampled across the transition, the Intel GT stayed at 25% busy, the
web process at 41% of a core, and it kept both render nodes open, all
unchanged for 45 seconds. Every frame is still being decoded on the iGPU and
none of them reach the screen.

**Use the Flatpak build.** Arch's `epiphany` 50.6-1 goes black the moment it
enters fullscreen — with nothing playing at all, which is what rules out the
iGPU, the cross-GPU handoff and the decoder in one step.
`WEBKIT_GST_DMABUF_SINK_DISABLED=1` changes nothing, as expected once the
cause is known. (An earlier version of this section blamed the Radeon
failing to import Intel buffers on the fullscreen path. That was a guess
resting on the assumption that the iGPU was involved, and an empty window
disproved it.)

Flathub's `org.gnome.Epiphany` 51.0 — the same application, its own
WebKitGTK inside the Flatpak — has no such problem, and everything works
there: a web process holding `renderD128` and `renderD129` at once, the
Intel GT at 25% busy, correct picture, **fullscreen included**. Whether the
version or the bundled WebKit is what differs has not been pinned down.

Its runtime ships `libgstva.so` of its own, so the host's `gst-plugin-va` is
not needed for the browser — only for host GStreamer applications.

```bash
flatpak remote-add --if-not-exists flathub https://flathub.org/repo/flathub.flatpakrepo
flatpak install flathub org.gnome.Epiphany
```

Never set `LIBVA_DRIVER_NAME` globally: libva applies it to every display and
`iHD` everywhere would break VA-API on the Radeon. It already maps i915 → iHD
and amdgpu → radeonsi on its own.

## Suspend, which was the open question

The repository this comes from **masks sleep entirely** — its own notes list
i915 among the suspend suspects "now that macOS mode binds it". So macOS mode
had never run on a machine where suspend works, which on the iMac18,3 is
exactly what the `suspend` module delivers here.

**Tested on 2026-09-21 and it holds.** Two s2idle cycles in one boot with
macOS mode on: both entered and returned, tasks restarted cleanly, no device
failed to suspend and i915 said nothing at all on the way through. The second
cycle is the one that matters on this machine — before the XHC1 fix, the
first sleep of every boot worked and the second always reset it.

That is two cycles, not a fortnight. macOS mode still adds a second PCI
device with runtime PM to the sleep path, leaves `i2c_i801` unbound while a
udev rule force-enables `00:1f.4`, and swaps in a recompiled SSDT, so keep an
eye on sleep after applying it. If it ever regresses, `--remove macos` puts
it back.

## Recovery

- **The desktop does not come back.** At the Limine menu press `e` on the entry
  and append `module_blacklist=i915` to the command line. That boots with the
  iGPU ignored and everything else in place. On GRUB, press `e` on the entry,
  append it to the line that starts with `linux`, and boot with ctrl-x.
- **From a TTY (ctrl-alt-F2) or over SSH:** `imac-patcher --remove macos`
  undoes all of it and rebuilds the boot image.
- **The machine does not reach userspace at all** — the only way an ACPI table
  can fail, and the reason for the checks above. Boot the installer USB,
  `chroot` in, delete `/etc/mkinitcpio.conf.d/zz-imac-igpu.conf` and
  `/etc/initcpio/acpi_override/imac-bcl100.aml`, and run `limine-mkinitcpio`
  (`mkinitcpio -P` on GRUB).

Removing the module takes back every file, clears the drop-in, rebuilds the
UKI without the hook and verifies the parameters are gone. On GRUB it first
restores every edited `/boot/vmlinuz-*`, then removes the parameters from
`GRUB_CMDLINE_LINUX`, rebuilds the initramfs and checks the regenerated entry.

**GRUB snapshot entries** (grub-btrfs, with `/boot` inside the snapshotted
subvolume, as on CachyOS) boot the kernel and initramfs saved in the snapshot,
but with the command line from the current `/etc/default/grub`. After
`--remove macos`, a snapshot taken while macOS mode was on therefore starts an
edited kernel without its parameters. Boot such a snapshot with
`module_blacklist=i915` added as above.

## Not supported

- **iMacPro1,1** — permanently. Its Xeon W has no integrated graphics, so there
  is nothing for set_os to expose.
- **Other 5K models.** iMac15,1, 17,1, 19,1 and 20,x do have an iGPU (Haswell,
  Skylake, Coffee Lake, Comet Lake), but the VBT here is built for Kaby Lake,
  the udev rules key on this machine's PCI addresses, and the ACPI table shape
  is checked against this firmware. Each needs its own verification first.
- **Fedora.** Its kernel image is a signed file from the kernel package,
  installed by `kernel-install` rather than a mkinitcpio preset, and dracut has
  its own ACPI-override mechanism. (Apple's firmware on these iMacs has no
  Secure Boot, so the signature would only matter elsewhere.)
- **Arch layouts other than GRUB or Limine with mkinitcpio** — systemd-boot,
  dracut, UKI-only setups. The same boundaries as the rest of the
  [Arch/GRUB backend](arch-grub.md).
- **GRUB older than 2.12**, as installed on the ESP, and GRUB started by a shim
  without its loader protocol: both boot Linux past its EFI stub. The preflight
  catches the first.
