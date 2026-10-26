# Debian support — 2026-10-26

The owner requested Debian support while the development host remains Omarchy.
The owner subsequently requested publication to GitHub; the support is on
`debian-backend`, without a new release or changes to host boot files, packages,
loaded modules or desktop settings.

## Scope

- Debian 13 amd64 with GRUB and initramfs-tools. Exact `ID=debian`; Ubuntu
  and other `ID_LIKE` derivatives are not silently assigned Debian kernels.
- APT dependency mapping and startup installation, matching ABI headers,
  DKMS audio/USB sleep fix, PipeWire/LV2 paths, KScreen on Plasma Wayland.
- Graphics: Debian 6.12 plus the existing 7.1/7.2 lean stack. The consolidated
  `patches/imac5k-debian-6.12.patch` ports core wake, stitching, link health,
  shutdown, suspend and iMac Pro timing fixes. The 7.x patches are unchanged.
- Stock 6.12 cannot use the pinned 6.17+ CS8409 audio source. It reports `n/a`
  unless there are removable leftovers. No kernel upgrade or alternate audio
  driver is installed automatically. Firmware brightness/iGPU and HDR keep
  their existing boot/desktop restrictions.

Runtime entry points are `scripts/debian-imac5k` and `scripts/lib/debian.sh`.
User instructions: [docs/debian.md](../docs/debian.md).

## Source and boot behavior

The driver reads the source version from the exact installed headers package
(not the signed image's `linux-signed-amd64` source), downloads
`linux-source-<series>=<version>` with APT, extracts a fresh tree and applies
the selected stack with `--fuzz=0`. Builds use the installed configuration and
`Module.symvers`. Full vermagic, module name and the stitch parameter are
validated before installation.

The packaged module is preserved; a per-kernel depmod override selects
`updates/imac5k/amdgpu.ko.xz`. The current image is backed up before rebuilding.
A per-kernel initramfs hook explicitly adds amdgpu, including on minimal
Debian installations whose default image omits graphics. `+` in the hook
filename becomes `_`: initramfs-tools silently skips a hook named after
Debian's unmodified `6.12.113+deb13-amd64` release. The hook tests the original
exact release and skips other kernels.

The new `09_imac5k-<kernel>` GRUB generator clones the normal kernel entry's
root/encryption/microcode paths. Only that entry gets the patched-only stitch
argument and loses the internal-panel mode override. A global stitch argument
would prevent a stock fallback kernel from loading amdgpu. The user selects
the named iMac 5K entry, and reapplies after kernel or boot-setting changes.
Reapply explicitly excludes prior managed entries when reading the normal
entry, so it does not keep cloning stale settings from itself.

Image and generated menu writes are staged. Failure restores the prior
installation, including a previously working patched installation on reapply.
Interrupted/incomplete recovery blocks installation and remains removable.
Removal restores the stock image first, removes the override and hooks, then
rebuilds without build/source/signing prerequisites. It also works when the
GPU driver cannot bind.

## The 6.12 port

The APIs needed more than patch-context changes:

- Use 6.12's `drm_fbdev_ttm_setup` and client header for the early tile commit.
- Retain 6.12's raw, sink-owned connector EDID; allocate/free `drm_edid` only
  at the property-update boundary. Synthetic properties must not replace or
  free the sink's cached EDID.
- Adapt scaling, cursor and display logging sites to the older interfaces.
- 6.12 has no DM per-IP `.complete` callback. Call the port's resume-complete
  helper from `amdgpu_pmops_complete`, after `in_suspend` clears, so the
  resume commit still arms timing sync and link health. It does nothing
  without a DC device; failed resumes keep the existing in-suspend guard.

Zero-fuzz application passed on Linux **6.12.38** (Debian 13's original base)
and **6.12.113**, including the complete actual Debian 6.12.113 source tree.

## Validation environment and results

Official Debian `trixie-slim` amd64 OCI image:
`sha256:4876fdea29cac1a33a3195f1eb1952feb1fca7dd6dd00be3e2f1879cf20d34d2`.
Layer hashes and Debian package downloads were verified. It was unpacked under
`~/.cache/imac-debian-validation/rootfs` and run with bubblewrap user namespaces.
This is Debian userspace on the Omarchy kernel, not a booted Debian VM.

Packages used:

| Package | Version |
|---|---|
| linux-source-6.12, linux-headers-6.12.113+deb13-amd64 | 6.12.113-1 |
| gcc-14 | 14.2.0-19 |
| initramfs-tools | 0.148.4 |
| kmod | 34.2-2 |
| grub-common | 2.12-9+deb13u2 |
| dkms | 3.2.2-1~deb13u1 |

The full graphics module compiled and linked with Debian's compiler, headers
and symbols, without compiler warnings. Its full vermagic matches stock:
`6.12.113+deb13-amd64 SMP preempt mod_unload modversions`.
The XHC1 module also built with `W=1`, without warnings, for the same ABI.

Actual install/remove ran inside this filesystem through the driver's CLI,
using real `depmod`, `modinfo`, XZ, `mkinitramfs` and `lsinitramfs`. The image
contained `usr/lib/modules/6.12.113+deb13-amd64/updates/imac5k/amdgpu.ko.xz`;
the original image backup compared byte-identical, and removal selected the
packaged module again and removed the managed entry. `uname -r`, DMI/DRM
identity and GRUB generation were simulated: this filesystem owns no boot
device. No module was loaded and no host GRUB tool was run.

Artifacts/logs are in `~/.cache/imac-debian-validation/`:
`debian-build.log`, `debian-xhci-build.log`, `debian-install-restore.log`, and
the two patch-application logs under `port-6.12/`.

SHA-256:

- Debian source tarball: `ded797683f4161cfb8839b281b97f5be3fec02dc517ecea999798815ebeece33`
- Built amdgpu (before stripping): `fd00d0be3f618c6e4c0905a947aff4dd93559aa7e1ab912628454660d4d0e2dd`

Offline tests cover startup/APT precedence, exact source metadata, ABI and
enrollment guards, entry argument/path preservation, repair, removal,
initramfs-hook scope, and initramfs/GRUB failures. The full check is run with
startup and both private audio integration subsets required: **625 passed,
no skips**. Bash syntax and `git diff --check` also pass.

```bash
IMAC5K_REQUIRE_STARTUP_TESTS=1 IMAC5K_REQUIRE_EQ_AUDIO_TESTS=1 \
  IMAC5K_REQUIRE_T2_AUDIO_TESTS=1 ./scripts/check.sh
```

Debian hardware boot, active 5K, motion/genlock, Secure Boot loading, physical
audio and repeated suspend remain unvalidated. Debian's 7.x path shares the
previously tested patch stack, but this session compiled only Debian 6.12.


## Ubuntu follow-up

The subsequent Ubuntu 26.04 work moved the implementation into shared APT
libraries while keeping the Debian CLI and kernel policy. The complete
regression suite now passes 657 tests with no skips, including the Debian
transaction cases. The generated UTS_RELEASE header supplies the ABI check
on both systems. See [the Ubuntu record](ubuntu-support-2026-10-26.md).

## Publication follow-up

The owner requested merging PR #15 and publishing the Debian/Ubuntu work.
PR #15 merged into `main` as `36721644e48f1605e9be3829d2290ee0827f15d5`;
`debian-backend` is based on that merge. The shared 7.1/7.2 stack and both
consolidated ports now include its root-plane zero-width guard.

The final Debian port applies at zero fuzz to both 6.12.38 and 6.12.113.
Its changed `amdgpu_dm.o` compiles against the real Debian headers in isolated
Debian userspace. The module hash above records the earlier full build before
this guard. The final integrated branch passes **657 tests, no skips**, with
startup and both private audio subsets required. Release coverage also checks
that both APT selectors, shared libraries, ports and guides ship in the archive.
Publication validation logs are in `~/.cache/imac-apt-publication-2026-10-26/`.
There is no new release; hardware validation remains pending.
