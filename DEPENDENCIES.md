# Dependencies

Everything `imac-patcher` and its helper scripts need, per module and distro.
Package names are given for **Arch/Omarchy** (pacman) and **Fedora** (dnf)
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
applied. This report does not install optional module dependencies. Each
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
| kernel headers for the running kernel | linux-headers |
| limine-mkinitcpio (or mkinitcpio) | limine / mkinitcpio |

Also: ~8 GB free disk and 20–40 min compile time. Kernel series 7.1.x/7.2.x only.

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
| kernel headers | linux-headers | kernel-devel-$(uname -r) |
| wget | wget | wget |
| git | git | git |
| gcc, make, patch | base-devel | gcc, make, patch |
| — | — | elfutils-libelf-devel, openssl-devel |
| mokutil (Secure Boot only) | — | mokutil |
| dracut | — | dracut |

Clones https://github.com/jackdanyell/imac18-3-cs8409-linux-audio into
`~/.cache/imac-patcher/`; the upstream DKMS build downloads kernel source
with wget.

## EQ module (safe tier)

| Tool | Arch package | Fedora package |
|---|---|---|
| pipewire (filter-chain built in) | pipewire | pipewire |
| pactl | libpulse | pulseaudio-utils |
| pw-cli | pipewire | pipewire-utils |
| wpctl | wireplumber | wireplumber |
| curl | curl | curl |
| LSP LV2 plugins | lsp-plugins-lv2 | lsp-plugins |
| bankstown LV2 | bankstown (AUR) | — build from source |

Both plugin sets are required, not optional: PipeWire drops a filter node whose
plugin is missing, and with it the whole graph, so the tuned sink simply never
appears. `bankstown` is packaged only in the AUR — the module installs it with
`yay` or `paru` when one is present, and otherwise points at
https://github.com/chadmed/bankstown.

Downloads `Audio/iMacAudio.conf` and the four impulse-response WAVs from
https://github.com/taprobane99/iMac5KLinux at apply time into
`~/.cache/imac-patcher/`, then installs them under `~/.config/pipewire/` and
`~/.local/share/imac-audio/`. Nothing is written as root, and nothing from that
project other than those five files is used. A WirePlumber drop-in of this
project's own, `~/.config/wireplumber/wireplumber.conf.d/51-imac-hide-raw-speakers.conf`,
hides the raw 4.0 device from sound pickers for as long as the tuning is
installed.

Needs working built-in speakers with the
`output:analog-surround-40+input:analog-stereo` profile. On iMac18,3, install the
audio driver and reboot first. The other admitted models keep their existing
driver; the bundled audio installer supports only iMac18,3.

## Color module (safe tier)

- Hyprland: `hyprctl` (edits `~/.config/hypr/monitors.lua`, then reloads)
- KDE: `python3` + `kscreen-doctor` (via `scripts/kde-display.py`, stdlib only)

## Suspend module (safe tier; boot tier while retired `idle=poll` config remains)

- systemd (`systemctl`) — sleep target masks
- Omarchy: the Limine/mkinitcpio stack from the boot module, used only when
  cleaning up a leftover `idle=poll` drop-in (`limine-mkinitcpio`, `objcopy`
  for verification)
- Fedora: `grubby` — removes a leftover `idle=poll` argument from the current
  kernel's GRUB entry

## Boot module (boot tier, Omarchy only)

- limine (the package provides `/usr/share/limine/BOOTX64.EFI`)
- objcopy (binutils) — classifies the EFI fallback binary
- limine-mkinitcpio or mkinitcpio — rebuilds the initramfs/UKI
- N/A on Fedora (GRUB); detection returns n/a there

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
