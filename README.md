# 🖥️ Retina 5K iMac Linux Patcher

![Retina 5K iMac Linux Patcher — display, audio, colour and boot fixes, applied module by module](.github/social-preview.png)

**A Linux patch manager for every Retina 5K iMac model, including iMac Pro.**

Choose display, audio and colour fixes for your hardware, one module at a time. The patches were developed and hardware-tested on the 2017 iMac18,3; accepting other models does not mean every patch has been validated on them. Hardware-specific modules retain their compatibility checks.

```bash
curl -fsSL https://raw.githubusercontent.com/MarkPronkin/imac5k-universal-linux-patcher/main/install.sh | bash
imac-patcher
```

That fetches the latest release (including prereleases), checks it against the published SHA-256, unpacks it under `~/.local/share/imac5k-patcher/`, and links `imac-patcher` into `~/.local/bin`. It installs the tool and stops there — nothing is patched until you run it and choose.

Prefer to read before you run, or want to work on the patches themselves? Clone instead — the patcher runs the same either way:

```bash
git clone https://github.com/MarkPronkin/imac5k-universal-linux-patcher
cd imac5k-universal-linux-patcher
./scripts/imac-patcher
```

> This is an independent continuation of
> [ahmadtv/omarchy-imac18-3-patch](https://github.com/ahmadtv/omarchy-imac18-3-patch),
> not a drop-in replacement for it. It adds the Fedora KDE backend and the
> post-commit DP link recovery described below. See [Credits](#-credits).

The interactive menu shows each module's state and lets you select changes.
Direct `--apply` and `--remove` commands request those changes immediately;
individual modules may also prompt for dependencies or a graphics build.

## Using the patcher

Run as your **desktop user**, inside your desktop session. The patcher invokes
`sudo` for system changes. In a clone, use `./scripts/imac-patcher` wherever the
examples below use `imac-patcher`.

```bash
imac-patcher --help             # commands, module IDs and exit codes
imac-patcher --status           # inspect all modules
imac-patcher                   # choose patches interactively
imac-patcher --apply eq color   # apply named modules in this order
imac-patcher --remove eq        # undo one module
```

| Status | Meaning |
|---|---|
| `applied` | The module's current checks pass |
| `not-applied` | The module does not detect its changes |
| `partial` | Some changes are present, but a required file, running driver, or setting is missing; a reboot or re-apply may be needed |
| `n/a` | The module is unavailable for the detected hardware, desktop, or platform; the command skips it |

The module IDs are `audio`, `eq`, `color`, `suspend`, `boot`, and `5k`.
`--apply safe` and `--remove safe` select the modules currently in the `safe`
tier. Use `safe` by itself. It can include **`suspend`, which disables sleep**;
select individual modules if sleep works on your machine. Suspend moves to the
`boot` tier while cleanup of an old `idle=poll` setting is needed.

Commands check all arguments before running any module. Exit status is `0` for
success or a skipped operation, `1` for a failed operation, and `2` for invalid
arguments. A batch continues after a module fails and returns `1` if any failed.
Successful installation can still require a reboot; check `--status` afterwards.

`--force` can appear before or after a command. It bypasses the launcher model
gate only; each module still checks its own compatibility. `--help` and
`--version` are available on any machine without creating runtime directories
or checking package dependencies.

For prerequisites, see [Dependencies](DEPENDENCIES.md). For changes to the
project itself, see the [development guide](docs/development.md).

Startup confirms `Core dependencies: ready` or offers to install missing core
tools. The interactive run then lists missing module prerequisites, including
audio and graphics build tools, and offers to install them all in one go before
the menu. Declining is fine: each module offers its own again when you choose
it, and `--status` only reports. Prompts remain visible when input is piped.

## Compatibility

Read both tables together: a patch needs a compatible model **and** distribution setup.

- ✅ **Verified** — hardware-tested by this project on iMac18,3, running Omarchy (Limine + Hyprland) and CachyOS (GRUB + KDE Plasma Wayland). Native 5K module hardware-tested on iMacPro1,1 (Radeon Pro Vega 64X), running Omarchy (Limine + Hyprland) on the `linux-t2` kernel 7.1.8.
- ⚪ **Build-tested** — build, install and restore checks passed, without confirming the result on hardware.
- ⚪ **Conditional** — additional setup is required and that combination is untested.
- ⚪ **Untested** — an implementation exists but hardware behaviour is unconfirmed.
- 🔴 **Unsupported** — the patcher does not provide that installation path; it does not mean the hardware cannot work under Linux.
- ➖ **N/A** — the module does not apply to that model or distribution.

Grey marks are all one thing: nobody has confirmed it on hardware yet.

### Models and module availability

All models below pass the model gate. Years and identifiers follow [Apple's model list](https://support.apple.com/en-us/108054). The columns cover the six hardware/system modules. The suspend module **disables sleep**, rather than repairing it.

| Model | Release | Identifier | Native 5K (`5k`) | Audio driver (`audio`) | Speaker EQ (`eq`) | Colour (`color`) | Block sleep (`suspend`) | Boot repair (`boot`) |
|---|---|---|---|---|---|---|---|---|
| iMac Retina 5K, 27-inch | Late 2014 | `iMac15,1` | ⚪ Untested | 🔴 Unsupported | ⚪ Untested | ⚪ KDE untested; ➖ P3 preset N/A | ⚪ Untested; optional | ⚪ Untested; Limine only |
| iMac Retina 5K, 27-inch | Mid 2015 | `iMac15,1` | ⚪ Untested | 🔴 Unsupported | ⚪ Untested | ⚪ KDE untested; ➖ P3 preset N/A | ⚪ Untested; optional | ⚪ Untested; Limine only |
| iMac Retina 5K, 27-inch | Late 2015 | `iMac17,1` | ⚪ Untested | 🔴 Unsupported | ⚪ Upstream-measured; locally untested | ⚪ Untested | ⚪ Untested; optional | ⚪ Untested; Limine only |
| iMac Retina 5K, 27-inch | 2017 | `iMac18,3` | ✅ **Verified** | ✅ **Verified** | ✅ **Verified** | ✅ **Verified** | ✅ **Verified workaround** | ✅ **Verified** |
| iMac Pro, 27-inch | 2017 | `iMacPro1,1` | ✅ **Verified** | ➖ N/A: T2 audio | ➖ N/A: T2 audio | ⚪ Untested | ⚪ Untested; optional | ⚪ Untested; Limine only |
| iMac Retina 5K, 27-inch | 2019 | `iMac19,1` | ⚪ Untested | 🔴 Unsupported | ⚪ Untested | ⚪ Untested | ⚪ Untested; optional | ⚪ Untested; Limine only |
| iMac Retina 5K, 27-inch | 2020 | `iMac20,1` | ⚪ Untested | 🔴 Unsupported | ⚪ Untested | ⚪ Untested | ⚪ Untested; optional | ⚪ Untested; Limine only |
| iMac Retina 5K, 27-inch | 2020 | `iMac20,2` | ⚪ Untested | 🔴 Unsupported | ⚪ Untested | ⚪ Untested | ⚪ Untested; optional | ⚪ Untested; Limine only |

The 5K patch requires `amdgpu` and kernel **7.1.x or 7.2.x**; its panel-ID checks still apply. On the iMac Pro it additionally needs the four iMac Pro patches and Hyprland at the panel's 10 bpc. The bundled audio driver is specific to `iMac18,3`; other models keep their existing driver. EQ requires working four-channel speakers, and its tuning was measured upstream on `iMac17,1`. KDE colour uses EDID; the Hyprland Display P3 preset excludes `iMac15,1`. Boot repair requires the Omarchy/Limine layout. Leave block-sleep unselected if suspend works on your model.

### 🐧 Distributions

Distribution status assumes compatible hardware from the table above. Arch and Omarchy are separate rows because the boot and Hyprland integrations depend on Omarchy's configuration, not just on the package manager.

| Distribution | Native 5K (`5k`) | Audio driver (`audio`) | Speaker EQ (`eq`) | Colour (`color`) | Block sleep (`suspend`) | Boot repair (`boot`) |
|---|---|---|---|---|---|---|
| **Arch Linux** | ⚪ Untested: GRUB backend verified on CachyOS; Omarchy/Limine also supported | ⚪ Untested: pacman backend | ⚪ Untested: PipeWire + plugins | ⚪ Conditional: KDE or Omarchy Hyprland config | ⚪ Untested: systemd | ⚪ Conditional: Omarchy/Limine layout |
| **CachyOS** | ✅ **Verified: GRUB + mkinitcpio** | ✅ **Verified** | ✅ **Verified** | ✅ **Verified: KDE** | ✅ **Verified workaround** | ➖ N/A on GRUB |
| **EndeavourOS** | ⚪ Untested: same GRUB backend as CachyOS | ⚪ Untested: pacman backend | ⚪ Untested: PipeWire + plugins | ⚪ Conditional: KDE or Omarchy Hyprland config | ⚪ Untested: systemd | ➖ N/A on GRUB |
| **Omarchy** | ✅ **Verified** | ✅ **Verified** | ✅ **Verified** | ✅ **Verified: Hyprland** | ✅ **Verified workaround** | ✅ **Verified** |
| **Fedora** | ⚪ **Build-tested: GRUB/dracut** | ⚪ Untested: DNF/DKMS backend | ⚪ Conditional: Bankstown built manually | ⚪ Untested: KDE Wayland | ⚪ Untested: systemd | ➖ N/A: GRUB backend |
| **Debian** | 🔴 Unsupported: no kernel backend | 🔴 Unsupported: no APT installer | ⚪ Conditional: manual dependencies | ⚪ Conditional: KDE Wayland | ⚪ Untested: systemd | 🔴 Unsupported |
| **Ubuntu** | 🔴 Unsupported: no kernel backend | 🔴 Unsupported: no APT installer | ⚪ Conditional: manual dependencies | ⚪ Conditional: KDE Wayland | ⚪ Untested: systemd | 🔴 Unsupported |

Omarchy uses pacman, kernel.org sources, Limine and mkinitcpio. Arch-family GRUB support also covers distributions whose `ID_LIKE` includes `arch`, including EndeavourOS and CachyOS. It uses matching installed kernel headers, the kernel’s compiler toolchain (including Clang), `/etc/default/grub`, `grub-mkconfig`, and mkinitcpio presets. The install-and-boot path is hardware-validated on CachyOS; the staged test entries and promotion are implemented and covered offline, but have not been exercised on hardware. Dracut and UKI-only Arch layouts are not supported by this backend. See the [Arch/GRUB guide](docs/arch-grub.md). Fedora uses DNF, matching Fedora kernel source RPMs, GRUB/BLS and dracut. Debian and Ubuntu have no dedicated backend or automatic APT dependency installation: the conditional entries cover reusable modules with prerequisites installed manually, not full distribution support. Colour on their default GNOME desktops is not implemented.

Fedora specifics — dependencies, Secure Boot signing, recovery, and how the backend is wired in — are in the **[Fedora KDE guide](docs/fedora-kde.md)**. Fedora Kinoite/Atomic is not supported.

---

## 🔧 What it fixes

| | Problem on stock Linux | Status |
|---|---|---|
| 🖥️ **Display** | Panel is two 2560×2880 tiles; stock `amdgpu` drives one and stretches it. No native 5K. | ✅ Native 5120×2880, genlocked |
| 🔊 **Speakers / mic** | CS8409 codec: kernel finds no speaker output at all. Silent machine. | ✅ Hardware-gated DKMS driver |
| 🎚️ **Speaker tone** | Codec does zero DSP and the woofers and tweeters are driven as one stereo pair; macOS does all of it in software. | ✅ Measured 4.0 crossover, EQ and convolution |
| 🎨 **Colour** | Wide-gamut (P3) panel rendered as sRGB — everything oversaturated. | ✅ Correct gamut mapping |
| 😴 **Suspend** | Hard-hangs the machine every time (Apple firmware ACPI issue). | ⚠️ Masked off — see below |
| ⚡ **Thunderbolt / 10GbE** | Adapter detected but never authorised. | ✅ Persistent enrolment |

---

## 🖥️ The headline: native 5K

The internal panel is a genuine dual-tile display — two 2560×2880 halves on separate physical links, which Apple's firmware leaves half-asleep for non-Apple operating systems. Stock `amdgpu` only ever lights one tile and lets the panel stretch it.

The patch stack fixes this in three layers, all inside the `amdgpu` module:

1. ⚡ **Wake** — a vendor DPCD write (`0x4F1`) powers up the dormant second link
2. 🧵 **Stitch** — both tiles are presented to userspace as one 5120×2880 output, so compositors work unmodified
3. 🔒 **Genlock** — per-frame CRTC sync so the two halves scan in lockstep (mainline has this as a literal `TODO`; filling it is this project's own contribution, submitted upstream)

Install it without a second kernel — only the `amdgpu` module is rebuilt for your running kernel, with the stock module backed up:

```bash
./scripts/imac-patcher            # menu-driven
./scripts/imac-patcher --apply 5k  # or direct
./scripts/imac-patcher --remove 5k # full undo, any time
```

**Read [`patches/README.md`](patches/README.md) first.** The patch is verified against kernel **7.1.x and 7.2.x only** and the installer refuses anything else, because a mis-applied patch means a broken GPU module.

You don't need to supply source files — the patch ships in this repo. On
Omarchy, the installer downloads the matching kernel source from kernel.org;
Fedora uses its matching source RPM.

The dependency and boot notes below describe **Omarchy/Arch**. Fedora builds against its matching source RPM and `kernel-devel` instead, and needs more disk — follow the [Fedora guide](docs/fedora-kde.md).

- 🛠️ **Build tools and kernel headers** — `base-devel bc pahole` plus the running kernel’s headers (`linux-headers`, `linux-lts-headers`, `linux-cachyos-headers`, etc., selected from its `pkgbase`). Clang-built GRUB kernels also need `clang llvm lld`. The patcher checks for these up front and offers to install anything missing, rather than failing part-way through a compile.
- 💾 **About 8 GB of disk** for the kernel source tree.
- ⏱️ **20–40 minutes** for the first build. Re-runs (e.g. after a kernel update) reuse the tree and are much faster.

Re-run it after any kernel update — the patched module is built for one specific kernel version and a new kernel reverts you to stock (which the patcher will report as `partial`).

---

## 🔊 Audio

On iMac18,3, the CS8409 codec needs an out-of-tree driver — the in-kernel one
doesn't recognise a speaker output on this board. Install it through the patcher
so it selects the distribution backend and checks the prerequisites:

```bash
./scripts/imac-patcher --apply audio
# Reboot before testing audio or applying speaker tuning.
```

The audio module now includes the [headset fixes from ahmadtv's Omarchy
patcher](https://github.com/ahmadtv/omarchy-imac5k): internal/headset microphone
switching even during recording, usable microphone gain, serialized jack and
stream setup, and EarPods play/pause and volume buttons. Re-run the command
above to upgrade an older audio install. It uses a pinned source revision and
a separate DKMS version, so the old `0.2` build cannot be mistaken for the fix.
Linux **6.17+** is required; the headset changes were tested upstream on
iMac18,3 with 7.1.9, and the driver has been compile-tested here on 7.2.3.
This fork's integration has offline tests; physical
headset validation on its other kernels and Fedora remains outstanding.

Upstream reports an unresolved high-pitched sound on jack insertion.
See [headphone setup and checks](docs/headphones.md).

Then, optionally, the speaker tuning:

```bash
./scripts/imac-patcher --apply eq
```

The four speakers are two woofers and two tweeters, which the driver presents as a 4-channel card and everything else drives as a plain stereo pair. This switches the card to its **Analog Surround 4.0** profile and inserts a PipeWire filter-chain that crosses over at 3.8 kHz, EQs the two ways separately and convolves each with a measured impulse response — [taprobane99](https://github.com/taprobane99/iMac5KLinux)'s tuning, measured with a calibrated microphone. Only that project's `Audio/` files are used; its kernel, display and GRUB work is not touched.

It needs two LV2 plugin sets. `lsp-plugins-lv2` comes from your distribution's repositories; `bankstown` is in nobody's repositories, so the module offers to build it from source with `cargo` into `~/.lv2` — **no AUR helper needed**, on Arch or anywhere else, since the AUR package does nothing but run the same build. If either is already installed, it is used as-is. The tuning itself ships in this repository under `assets/imac-audio/`, so applying it needs no network and a given release always installs the tuning it was tested with. It used to be downloaded from upstream's `main` at apply time, which meant every install depended on whatever `main` happened to be — that file was rewritten three times inside one hour on 2026-09-03. See [`assets/imac-audio/README.md`](assets/imac-audio/README.md) for provenance, checksums and licence. Everything lands in your home directory: `~/.config/pipewire/imac-speaker-eq.conf.d/imac-audio.conf` and `~/.local/share/imac-audio/`, with nothing written as root.

While the tuning is installed, the raw 4.0 device is hidden from sound pickers (a WirePlumber rule marks it internal, so the chain still feeds it but nothing offers it): selected directly it plays the tweeter half of the crossover and sounds thin. `--remove eq` puts the card profile, the default sink and that device back.

The chain's own output is a playback stream, so desktops otherwise list it next to real applications while the speakers play. Omarchy's audio panel already skips a tuning's output but recognises it by name, so the installer renames that node into its convention; on other desktops it is a node name nothing reads.

That output is pinned to the hidden 4.0 speaker device, so plugging in or choosing another output — a USB DAC, Bluetooth, HDMI — cannot pull the speaker tuning onto it. Installs from before the pin followed the default device instead, and played the folded crossover through whatever was plugged in. `--status` reports such an install as `partial`; re-run `./scripts/imac-patcher --apply eq` to fix it. Re-applying leaves a default output you chose yourself alone.

### Headphones

Plug headphones into the iMac's jack and **iMac Speakers disappears**, replaced by **Aux Audio Output** — the jack, with no tuning applied. Unplug and the speakers come straight back. Whatever was playing follows in both directions.

This is necessary rather than cosmetic. The headphone port exists only in the card's stereo profiles, so plugging in moves the card off Analog Surround 4.0. The tuning is a filter graph rather than a device, so it survives that move, stays selectable, and its four channels get folded into the two the jack has — the crossover summed back together, over headphones it was never measured for.

So the tuning runs as its own service, `imac-speaker-eq.service`, and `imac-audio-jack.service` stops it while the jack is in use. Both follow `pipewire.service`. Detection is event-driven, through PipeWire's own port availability — no polling, no root, and no `input` group membership needed.

An output you chose yourself is left alone: if you have sent audio to Bluetooth or HDMI, the jack does not steal it back. Only streams on the sink being taken away are carried across.

One consequence worth knowing: with the tuning stopped and headphones out, the only built-in output is the hidden 4.0 device, so if `imac-speaker-eq.service` fails to start you get silence rather than untuned speakers. `--status` reports that as `partial`; `journalctl --user -u imac-speaker-eq` says why.

**On loudness.** The hidden hardware output is set to **100% (0 dB)**; use **iMac Speakers** to control listening volume. Before raising the hardware level, the installer lowers the visible slider to 45% if it is higher, preserving quieter settings. WirePlumber remembers the hardware level, and `--remove eq` restores the level saved on first apply. Re-applying with the hardware already at 100% leaves the visible slider alone.

Unplug headphones before applying or repairing speaker tuning. The patcher
refuses to raise the speaker hardware level while the card reports connected
headphones — that level is for the internal drivers.

Older installs could leave the hidden output at 40% (about −24 dB), making the speakers much too quiet even with the visible EQ slider at 100%. Re-run `./scripts/imac-patcher --apply eq` to correct that. The tuning itself still includes woofer attenuation, compression, limiting and frequency correction, so equal slider positions need not match the loudness of an untuned output.

The tuning was measured on an iMac17,1 (2015), which has the same 4.0 speaker layout; if it sounds inverted — treble from the woofers — the channel mapping on your board differs and `--remove eq` restores it.

If it ever sounds thin and far too quiet, the card has fallen back to its stereo profile: the chain still produces four channels, but the two woofer ones link to nothing and you are hearing the tweeter half of a crossover. `--status` reports that as `partial` rather than `applied`; `pactl list cards | grep 'Active Profile'` confirms it, and re-applying selects the 4.0 profile again.

---

## 🎨 Colour

On KDE Plasma Wayland, `./scripts/imac-patcher --apply color` selects the panel's EDID colour profile through KScreen, and `--remove color` puts your previous selection back. The setting below is the Hyprland equivalent.

The panel is wide-gamut Display P3. Hyprland's default `srgb` mode doesn't gamut-map for it, so everything looks oversaturated. In `~/.config/hypr/monitors.lua`:

```lua
hl.monitor({ output = "", mode = "preferred", position = "auto", scale = 2, cm = "dp3" })
```

---

## 😴 Suspend — read this before you try it

Suspend and hibernate **hard-hang this machine, every time**. This is an Apple firmware ACPI issue, not something a kernel parameter fixes; sleep mode, the display override, GPU power states and `idle=poll` were each ruled out by testing. Recovery is a hard power-cycle.

The patcher masks the sleep targets so nothing triggers them by accident:

```bash
sudo systemctl mask suspend.target hibernate.target hybrid-sleep.target suspend-then-hibernate.target
```

An earlier release tried `idle=poll` instead; it hung the same way. Applying or removing the module also deletes that leftover — the `/etc/limine-entry-tool.d/imac5k-no-cstates.conf` drop-in on Omarchy (rebuilding the boot image), the grubby kernel argument on Fedora.

---

## 🚧 Known rough edges

- 🌗 **Skewed Apple logo on *warm* reboots** with 5K active — root-caused: the display was never turned off at reboot, so Apple's firmware inherited a live dual-tile panel. **Fixed and shipped** (`patches/5k-latch-clear.patch`): the display is shut down properly at reboot, every register the stitch wrote into the second tile is undone, and the panel is powered off before the handoff. Confirmed on hardware with a captured teardown. A follow-up (`patches/5k-latch-clear-going-down-only.patch`) limits that teardown to the reboot path — as first shipped it also ran on every ordinary stream-off and caused repeated black flashes on the second tile (see below). What remains: the warm-reboot logo is straight but slightly soft, because the firmware draws it on one tile after the handoff; a cold boot is crisp. Cosmetic.
- 🪞 **Sheared seam after login** — two causes, both **fixed and shipped**: the driver's master pick left the slave tile out of the hardware sync group (`patches/5k-genlock-deterministic.patch`), and on a full modeset the one-shot alignment ran before the re-trained tile was up (`patches/5k-genlock-settle-resync.patch`, a re-sync 250 ms after each tiled commit). The black flashes on the second tile after the disk password, and the brief skew as the session exits before a reboot, were a regression from the first logo fix (its latch clear ran on every stream-off and each write toggled the tile's hotplug line, forcing a full re-detect and re-train on the next commit — 30–40 re-detects per boot instead of 4). Fixed and shipped: `patches/5k-latch-clear-going-down-only.patch`.
- 🎬 **Video encode (VCE)** hangs the GPU on certain transcodes, taking the session down. Under investigation.
- 📺 **YouTube 4K is CPU-decoded** — Polaris has no VP9/AV1 silicon. Hardware limit, not fixable.

---

## 📋 Requirements

- A Retina 5K iMac from the [model table](#models-and-module-availability). Other Macs, including 21.5-inch 4K and 24-inch 4.5K iMacs, remain outside the normal model gate.
- Kernel 7.1.x or 7.2.x for the 5K patch (everything else is version-independent)
- Omarchy (Limine + Hyprland), Arch/EndeavourOS/CachyOS with GRUB + mkinitcpio, or Fedora KDE (GRUB/dracut + Plasma Wayland) — see [Distributions](#-distributions) above. The audio, tuning and colour pieces are largely distribution-agnostic; the boot-related pieces are not, and each backend refuses to touch the other's bootloader.
- Nothing to install by hand: on startup the patcher checks the handful of basics it needs (`grep`, `sed`, `awk`, `findutils`, `coreutils`, `sudo`) and offers to install any that are missing. Each patch checks its own heavier dependencies when you run it. The full list is in [DEPENDENCIES.md](DEPENDENCIES.md).

## 📦 Updating and removing the tool

The tool updates itself:

```bash
imac-patcher upgrade
```

It checks for a newer release, installs it if there is one, and says so if there isn't. The previous two versions stay under `~/.local/share/imac5k-patcher/versions/`, so a rollback is one symlink. Re-running the install command does the same thing. (A git checkout is upgraded with `git pull` — `upgrade` will tell you so rather than overwrite it.)

Upgrading replaces the tool, not the patches: whatever you had applied stays applied. If a release changes a patch you're running, re-apply it to pick the new one up — `imac-patcher --status` shows where you stand.

Pin a specific release, or take the tool back off the machine:

```bash
curl -fsSL https://raw.githubusercontent.com/MarkPronkin/imac5k-universal-linux-patcher/main/install.sh | bash -s -- --version v0.1.0-alpha
curl -fsSL https://raw.githubusercontent.com/MarkPronkin/imac5k-universal-linux-patcher/main/install.sh | bash -s -- --uninstall
```

Uninstalling removes the tool, **not the patches** — those outlive it, so reverse anything you want gone with `imac-patcher --remove <id>` first. `imac-patcher --status` lists what is applied.

## 🛟 Safety

On Fedora, follow the [Fedora restore and recovery instructions](docs/fedora-kde.md#restore-and-recovery). On Arch-family GRUB systems, use the [Arch/GRUB guide](docs/arch-grub.md#restore-and-recovery). The Limine recovery steps below apply to Omarchy.

Use `--remove` to reverse an applied module, following its recovery instructions
where manual steps are needed. Boot-related changes print their recovery steps
*before* running. A new `amdgpu` build can be tried through
`scripts/imac-alt-entry add <name> <module>`, which boots it from its own
hash-pinned Limine entry or a separate GRUB initramfs entry while preserving the default (see
[`patches/README.md`](patches/README.md)). If a boot change goes wrong, boot the
Limine snapshot entry, restore `/etc/default/limine.backup`, re-run
`limine-mkinitcpio`, and reboot.

## 🧭 How this was worked out

Start with the [development guide](docs/development.md) for the code layout,
offline checks, module contract, and release workflow. Open items, root causes
and rejected approaches are tracked in
[`TODO.md`](https://github.com/MarkPronkin/imac5k-universal-linux-patcher/blob/main/TODO.md),
which is included in repository checkouts, but omitted from release installs.

## 🙏 Credits

This project began as a fork of **[ahmadtv/omarchy-imac18-3-patch](https://github.com/ahmadtv/omarchy-imac18-3-patch)** by Ahmad Al-Awadi, which is where the patcher, the 5K stitch work and the original Omarchy backend come from. It is MIT licensed, and that copyright is retained in [`LICENSE`](LICENSE) alongside the one for the changes made here. The full commit history of the original is preserved in this repository, so `git log` attributes every one of those commits to its author.

Carried on separately rather than as a pull request because the changes here — a second distribution backend, and a driver change whose cause is still open — are larger and less settled than a fork should carry back upstream. Nothing here is endorsed by the original author.

Native 5K builds on community work from [drm/amd#4455](https://gitlab.freedesktop.org/drm/amd/-/issues/4455) — mforce2 (tile wake), erik2 (stitch), taprobane99 (7.2.2 port), with guidance from AMD's Alex Deucher. The genlock fix and the first verified iMac18,3 result came from this project. Audio driver by [jackdanyell](https://github.com/jackdanyell/imac18-3-cs8409-linux-audio). The speaker tuning the `eq` module installs is [taprobane99](https://github.com/taprobane99/iMac5KLinux)'s, measured on an iMac17,1, and is carried here under `assets/imac-audio/` byte-identical to [commit `5069f81`](https://github.com/taprobane99/iMac5KLinux/tree/5069f81eeb4af129480604762f39f9eaec9898d7/Audio). That project publishes no licence; if you are its author and would rather it were not carried here, open an issue and it will be removed.

### Contributors

- **Mark Pronkin** ([@MarkPronkin](https://github.com/MarkPronkin)) — maintainer of this fork: the genlock and warm-reboot latch-clear fixes, the first verified iMac18,3 5K result, the Fedora KDE backend, and the module-based patcher, installer and releases.
- **Ahmad Al-Awadi** ([@ahmadtv](https://github.com/ahmadtv)) — the original patcher, the 5K stitch work and the first Omarchy backend, carried forward here.

The upstream display, audio and tuning work this builds on is credited above; `git log` and the [contributors graph](https://github.com/MarkPronkin/imac5k-universal-linux-patcher/graphs/contributors) carry the full record.
