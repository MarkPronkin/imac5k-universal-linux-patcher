# Dependencies

Everything `imac-patcher` and its helper scripts need, per module and distro.
Package names are given for **Arch/Omarchy** (pacman) and **Fedora** (dnf)
where they differ.

## Core (imac-patcher itself)

| Tool | Arch package | Fedora package | Notes |
|---|---|---|---|
| bash | bash | bash | |
| coreutils, grep, sed, awk, findutils | coreutils, grep, sed, gawk, findutils | same names | awk is used by the 5K helper scripts |
| sudo | sudo | sudo | every module needs root at some point |
| gum | gum | — | optional; nicer interactive UI, plain prompts are the fallback |

`imac-patcher` checks this core set on every run and offers to install what is
missing (pacman on Arch, DNF on Fedora) before it does anything else; when the
set is complete it says nothing and goes straight to the menu. `gum` is not
part of that gate — it is optional and the plain prompts are a real fallback.
Per-module dependencies stay with their module, checked when that module runs.

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

## Color module (safe tier)

- Hyprland: `hyprctl` (edits `~/.config/hypr/monitors.lua`, then reloads)
- KDE: `python3` + `kscreen-doctor` (via `scripts/kde-display.py`, stdlib only)

## Suspend module (safe tier)

- systemd (`systemctl`) only

## Boot module (boot tier, Omarchy only)

- limine (the package provides `/usr/share/limine/BOOTX64.EFI`)
- objcopy (binutils) — classifies the EFI fallback binary
- limine-mkinitcpio or mkinitcpio — rebuilds the initramfs/UKI
- N/A on Fedora (GRUB); detection returns n/a there

## scripts/verify.sh (optional probes)

Runs with whatever is present; each probe is skipped if the tool is missing:
`hyprctl` or `kscreen-doctor`, `glxinfo` (mesa-utils / mesa-demos), `wpctl`,
`dkms`, `boltctl`.
