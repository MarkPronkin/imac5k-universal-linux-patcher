# Dependencies

Everything `imac-patcher` and its helper scripts need, per module and distro.
Package names are given for **Arch/Omarchy/EndeavourOS/CachyOS** (pacman) and **Fedora** (dnf)
where they differ.

## Core (imac-patcher itself)

| Tool | Arch package | Fedora package | Notes |
|---|---|---|---|
| bash | bash | bash | Bash 4.4+; the status snapshot uses associative arrays |
| coreutils, grep, sed, awk, findutils | coreutils, grep, sed, gawk, findutils | same names | awk is used by the 5K helper scripts |
| sudo | sudo | sudo | package installation and system changes |
| gum | gum | — | optional; nicer interactive UI, plain prompts are the fallback |

`imac-patcher` checks this core set before status, menu, apply, and remove
operations and offers to install missing packages. `--help`, `--version`, and
`upgrade` bypass that gate; upgrading needs `curl` and the release installer's
tools. Invalid arguments also stop before the dependency check. `gum` is
optional; plain prompts are the fallback. The launcher itself needs `readlink`,
`dirname`, `cat`, and `uname` from coreutils even to locate an installed release;
if one is absent, it prints an explicit coreutils repair message before exiting.

Startup prints `Core dependencies: ready` when the required commands are
present. Otherwise it names the missing commands and packages and offers to
install them. Declining, reaching EOF, a failed package-manager command, or a
command still missing after installation stops startup with a nonzero status.
The confirmation is visible with terminal input and with piped input. Fedora
uses DNF even if pacman is also installed.

Before the menu, and during `--status`, the patcher also lists missing commands
and kernel development files for modules that are not fully applied. This
includes audio/PipeWire tools, KDE display tools, and graphics build tools;
missing `pactl` or Python can no longer hide behind an unexplained `n/a` status.
EQ plugin bundles are checked separately when EQ is available but not fully
applied.

The interactive run then offers to install everything that report named, as one
package list, using the same package manager and the same tool-to-package table
the modules use (`imac_tool_package()` in `scripts/lib/platform.sh`, mirroring
the tables below). Kernel headers are included by package name, since they carry
no command for the scan to find. Declining is not an error and does not stop
startup — some of those packages belong to patches that will never be chosen —
and `--status`, `--apply` and `--remove` never install from this report. Each
module's full apply/build preflight still checks its prerequisites, including
package and ABI requirements that command availability alone cannot establish.

## 5K module (boot tier)

### Arch/Omarchy (`scripts/patch-imac5k-amdgpu.sh`)

Preflight checks for these tools and offers to install missing ones:

| Tool | Package |
|---|---|
| gcc, make, ld, flex, bison, strip, objcopy | base-devel (pulls in binutils) |
| bc | bc |
| pahole | pahole |
| zstd | zstd |
| curl | curl |
| tar | tar |
| xz | xz |
| patch | patch |
| cpio | cpio |
| depmod, modinfo, lsmod | kmod |
| kernel headers for the running kernel | `<pkgbase>-headers` (`linux-headers`, `linux-cachyos-headers`, etc.) |
| limine-mkinitcpio (Limine backend) | limine-mkinitcpio-hook |
| mkinitcpio (GRUB backend) | mkinitcpio |
| grub-mkconfig (GRUB backend) | grub |
| clang, ld.lld, llvm-ar/nm/objcopy/objdump/readelf/strip (Clang-built GRUB kernels) | clang, lld, llvm |

Also: ~8 GB free disk and 20–40 min compile time. Kernel series 7.1.x/7.2.x only.

The headers package comes from `/usr/lib/modules/$(uname -r)/pkgbase`, so custom
kernels use their own headers. A package install must provide headers for the
exact running kernel; after a kernel update, reboot before patching. GRUB
builds use that installed Kbuild tree and its configuration, including Clang
when `CONFIG_CC_IS_CLANG=y`. Their boot layout must have matching
`/boot/vmlinuz-<pkgbase>` and `/boot/initramfs-<pkgbase>.img` files and a
mkinitcpio preset. Arch-family dracut/UKI-only layouts are refused.

The GRUB variants of `imac-alt-entry` and `imac-test-entry` also use `lsinitcpio`
(from mkinitcpio), libarchive’s `bsdtar`/`bsdcpio`, zstd, xz/gzip, kmod, and
coreutils. `imac-alt-entry add` needs rsync to stage its private module tree.
The helpers use the installed mkinitcpio configuration and explicitly include
amdgpu; they do not change bootloader selection. See [Arch/GRUB](docs/arch-grub.md).

### Fedora (`scripts/fedora-imac5k`, see docs/fedora-kde.md)

Checked by `fedora_deps()` in `scripts/lib/fedora.sh` — install with one command:

```
sudo dnf install kernel-devel-$(uname -r) gcc make binutils bc dwarves \
  flex bison patch xz curl tar rpm-build koji python3 python3-rpm-macros \
  elfutils-libelf-devel openssl-devel dracut grubby mokutil \
  perl-interpreter findutils diffutils git
```

`kernel-devel` must match the running kernel exactly; if it is unavailable,
update Fedora, reboot, and retry. Fedora Kinoite/Atomic is not supported.

## Audio module (safe tier)

| Tool | Arch package | Fedora package |
|---|---|---|
| dkms | dkms | dkms |
| kernel headers | `<pkgbase>-headers` | kernel-devel-$(uname -r) |
| wget | wget | wget |
| git | git | git |
| gcc, make, patch | base-devel | gcc, make, patch |
| tar, xz, modinfo, depmod | tar, xz, kmod | tar, xz, kmod |
| limine-mkinitcpio or mkinitcpio | limine / mkinitcpio | — |
| — | — | elfutils-libelf-devel, openssl-devel |
| mokutil (Secure Boot only) | — | mokutil |
| dracut | — | dracut |

Clones https://github.com/jackdanyell/imac18-3-cs8409-linux-audio into
`~/.cache/imac-patcher/`, exports commit
`be90113a7638eb264b2ff5acfe888cd72c8364c6` without changing the cached checkout,
and applies the bundled `cs8409-headset-capture.patch`. Requires iMac18,3,
the CS8409 codec, and Linux 6.17+. Both backends register the prepared source
as `snd_hda_macbookpro/0.2.imac5k1`; DKMS keeps a source copy under `/usr/src`.
The upstream DKMS build downloads kernel source with wget.

Arch builds all installed supported kernels with matching headers, including
a pending kernel update. Fedora targets the running kernel and requires its
exact `kernel-devel` package. Installation verifies the selected module has
the headset patch, refreshes the initramfs, and requires a reboot. A competing
CS8409 DKMS package must be removed through its package manager first.

## EQ module (safe tier)

| Tool | Arch package | Fedora package |
|---|---|---|
| pipewire (filter-chain built in) | pipewire | pipewire |
| pactl | libpulse | pulseaudio-utils |
| pw-cli | pipewire | pipewire-utils |
| wpctl | wireplumber | wireplumber |
| systemctl (user units) | systemd | systemd |
| LSP LV2 plugins | lsp-plugins-lv2 | lsp-plugins |
| bankstown LV2 | built from source | built from source |
| cargo, git (only to build bankstown) | rust, git | cargo, git |

The tuning graph runs as a PipeWire client of its own under
`imac-speaker-eq.service`, and `imac-audio-jack.service` swaps the built-in
output between it and the untuned jack output as headphones are used. Both are
**user** units, installed under `~/.config/systemd/user` and pulled in by
`pipewire.service`; neither needs root. A session without systemd user units
gets no headphone switching, and `--status` reports the module as `partial`.

The tuning unit waits, in `ExecStartPre`, for the four-channel device its chain
targets to exist before starting. `After=` the session manager only means
WirePlumber's unit has started, not that it has enumerated the card, and a
filter chain started before its target registers no sink and does not exit —
so nothing restarts it, and with the raw device hidden the session is left with
`auto_null` and an empty sound picker. The wait is bounded at 30 seconds and
uses `pw-cli`, since the hidden device is absent from `pactl`'s sink list. An
install predating the gate reports `partial` so that re-applying repairs it.

Both plugin sets are required, not optional: PipeWire drops a filter node whose
plugin is missing, and with it the whole graph, so the tuned sink simply never
appears. `bankstown` is in no distribution's repositories, so the module
**builds it from source**, after asking: it clones
https://github.com/chadmed/bankstown at the pinned `1.1.0` tag
(`e9829c9`, MIT) and runs `cargo build --release --locked`, installing the
three files into `~/.lv2/bankstown.lv2/`. That needs `cargo` and `git`, and no
root. **No AUR helper is required**, on Arch or anywhere else: the AUR package
does nothing but run the same cargo build. A distribution package or a copy
you built yourself is found first and nothing is built. `--remove eq` deletes
only a bundle this module built, never one that was already there.

**No network access.** `iMacAudio.conf` and the four impulse-response WAVs are
vendored in this repository under `assets/imac-audio/` and installed from the
checkout into `~/.config/pipewire/imac-speaker-eq.conf.d/` and
`~/.local/share/imac-audio/`. They were previously downloaded from
https://github.com/taprobane99/iMac5KLinux at apply time, which tied every
install to that project's `main` branch. See `assets/imac-audio/README.md` for
provenance, checksums and licence.
Three things are rewritten in the vendored graph: the impulse-response paths,
the name of the chain's own output node, which desktops would otherwise list
beside real applications, and `node.virtual`, which upstream ships as `true`.
That property makes pipewire-pulse withhold the sink's PulseAudio `HARDWARE`
flag, and desktop pickers list only hardware sinks — so with the raw 4.0 device
hidden, KDE's sound settings showed no output device at all while the speakers
were playing through this very chain. Apply sets it `false` and refuses if it
cannot, since a sink no picker will show is invisible to everything except the
ear. An install predating that reports `partial` so re-applying repairs it. The base config beside it, which makes it a
standalone PipeWire client, is this project's own.
Nothing is written as root, and nothing from that project other than those
five files is used. A WirePlumber drop-in of this project's own,
`~/.config/wireplumber/wireplumber.conf.d/51-imac-hide-raw-speakers.conf`,
hides the raw 4.0 device from sound pickers and names the jack output
**Aux Audio Output**, for as long as the tuning is installed. The switching
helper is installed as `~/.local/bin/imac-audio-jack-switch`.

Needs working built-in speakers with the
`output:analog-surround-40+input:analog-stereo` profile. On iMac18,3, install the
audio driver and reboot first. The other admitted models keep their existing
driver; the bundled audio installer supports only iMac18,3.

## Color module (safe tier)

- Hyprland: `hyprctl` (edits `~/.config/hypr/monitors.lua`, then reloads)
- KDE: `python3` + `kscreen-doctor` (via `scripts/kde-display.py`, stdlib only)

On KDE the setting belongs to the panel's EDID hash, not to the connector name,
so the 5K stitch invalidates it: apply `color` after the stitch reboot. The
module refuses while the stitch is configured but not yet active, `--apply 5k`
says the same at the point it asks for the reboot, and the saved selection in
`~/.local/state/imac-patcher/kde-color.json` records the panel identity it was
taken from so `--remove` never restores one panel's setting onto another.

## Suspend module (boot tier while its boot config needs changing; safe tier after)

- systemd (`systemctl`) — sleep target masks; runs the Thunderbolt sleep hook
  the module installs in `/usr/lib/systemd/system-sleep/`
- Omarchy: the Limine/mkinitcpio stack from the boot module
  (`limine-mkinitcpio`, `objcopy` for verification) — writes the
  `mem_sleep_default=s2idle` drop-in and cleans up a leftover `idle=poll` one
- Arch-family GRUB: `grub-mkconfig` (package `grub`) — adds
  `mem_sleep_default=s2idle` to `/etc/default/grub`, removes a leftover
  `idle=poll`, and verifies the generated kernel entry
- Fedora: `grubby` — adds `mem_sleep_default=s2idle` to the current kernel's
  GRUB entry and removes a leftover `idle=poll` argument

## Boot module (boot tier, Omarchy only)

- limine (the package provides `/usr/share/limine/BOOTX64.EFI`)
- objcopy (binutils) — classifies the EFI fallback binary
- limine-mkinitcpio or mkinitcpio — rebuilds the initramfs/UKI
- N/A on Fedora and Arch-family GRUB; detection returns n/a there

## scripts/verify.sh (optional probes)

The baseline probes use `lspci`, `modinfo`, `nmcli`, and `ip`, alongside standard
shell tools. Optional probes check for `hyprctl` or `kscreen-doctor`, `glxinfo`,
`wpctl`, `pactl`, `dkms`, and `boltctl` before running them. This script inspects
the running machine; it is separate from the offline development checks.

## Development checks

Run `./scripts/check.sh` from a repository checkout. It needs Bash, Python 3
(standard library only), Git, curl, and the GNU archive/core utilities used by
the release tests. It does not need kernel headers, a compiler, a display or
audio session, or root. The additional isolated startup tests need `bubblewrap`
and working Linux user namespaces. See the [development guide](docs/development.md).
