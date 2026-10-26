# Ubuntu support — 2026-10-26

The owner requested Ubuntu support and selected **Ubuntu 26.04 LTS** as the
priority. Development remains on Omarchy. No host package, boot file, loaded
module or desktop configuration was changed. The owner subsequently requested
publication to GitHub; the support is on `debian-backend`, with no new release.

## Implementation

`ubuntu-imac5k` and `debian-imac5k` are small distribution selectors. The
build/install/restore transaction now lives in `scripts/lib/apt-imac5k.sh`,
module overrides in `apt.sh`, and source/signing configuration in
`apt-platform.sh`. Debian retains its 6.12/7.1/7.2 policy and public CLI;
Ubuntu accepts 7.0/7.1/7.2 with official generic/HWE headers. Exact `ID=ubuntu`
is required; derivatives, OEM, cloud, lowlatency and mainline PPA sources do
not inherit a source backend through `ID_LIKE`.

Ubuntu's binary source name includes the full base version, for example
`linux-source-7.0.0=7.0.0-38.38` for `7.0.0-38-generic`. Both the source name
and version come from the installed ABI headers, including HWE suffixes.
Downloaded package name, version and source owner must match. APT validates
repository hashes, no deb-src is needed, and a missing exact version fails.
The builder handles Debian's XZ and Ubuntu's bzip2 source archives.

Ubuntu's installed Makefile reports `7.0.14` for `make kernelrelease`, while
`include/generated/utsrelease.h` specifies `7.0.0-38-generic`. The shared
check now validates the generated UTS_RELEASE, which Kbuild uses in module
vermagic; complete vermagic still has to match the packaged amdgpu module.

The consolidated `patches/imac5k-ubuntu-7.0.patch` carries the current thirteen
lean patches against the actual Ubuntu downstream tree. Its display code
already contains backports absent from upstream v7.0. Link-detection context
and DCE logging needed adaptation; the rest of the stack retains its existing
behavior, including PR #15's root-plane zero-width guard. Zero-fuzz application
and the complete module build pass on
`linux-source-7.0.0` **7.0.0-38.38**. The 7.1/7.2 patch list is unchanged.

Shared install/restore retains the stock module, exact-kernel initramfs hook,
image backup, depmod override and separate GRUB entry. Only the managed entry
gets the stitch parameter and loses the internal-panel mode override. Normal
root/encryption/microcode arguments and other kernels remain intact. Staged
image/menu writes, failed-reapply recovery, incomplete-recovery guards and
removal without a bound GPU retain the Debian transaction tests.

## Ubuntu audio and signing

The pinned CS8409 driver's Ubuntu pre-build path requires the packaged HDA
source tree. The Ubuntu module therefore installs the exact matching source
package plus bzip2. A guard copied into the prepared DKMS tree checks the
headers/source pair on every later rebuild; it refuses another ABI's source
and prints the required package version. The Ubuntu registration is
`0.2.imac5k1.ubuntu1`, distinct from the existing prepared driver version.
The vendored headset patch remains byte-identical.

Ubuntu DKMS normally signs with `/var/lib/shim-signed/mok/MOK.priv` and
`MOK.der`, verified from the installed Ubuntu DKMS code. The enrollment check
uses this certificate; Debian keeps `/var/lib/dkms/mok.pub`.
`IMAC5K_DKMS_CERT` supports a custom enrollment-check certificate without
changing DKMS configuration. Graphics retains IMAC5K_SIGN_KEY/CERT and checks
enrollment before installation under Secure Boot or kernel lockdown.

Audio and the USB sleep module explicitly install **zstd** on Ubuntu. An
initial real DKMS run in the minimal rootfs exposed the missing compressor:
DKMS emitted an error but continued with an uncompressed module. The final
check requires a signed `.ko.zst` and removal back to the stock module.

## Validation environment

Official amd64 `ubuntu:26.04` OCI manifest:
`sha256:42527649dbc4f9197a6073f426f488cbff0e9cc9f2afce32d91c383e4875634a`.
Layer hashes and package SHA-256 values from signed APT metadata were checked.
The filesystem is under `~/.cache/imac-ubuntu-validation/rootfs`, run in
bubblewrap user namespaces. This is Ubuntu userspace on the host's kernel,
not a booted Ubuntu VM.

| Package | Version |
|---|---|
| linux-source-7.0.0, linux-headers-7.0.0-38-generic | 7.0.0-38.38 |
| gcc-15 | 15.2.0-16ubuntu1 |
| initramfs-tools | 0.151ubuntu1 |
| kmod | 34.2-2ubuntu2 |
| grub-common | 2.14-2ubuntu2.1 |
| dkms | 3.2.2-1ubuntu1 |
| zstd | 1.5.7+dfsg-3 |

The full graphics, pinned headset audio and XHC1 sleep modules compile and
link against Ubuntu's actual headers and symbols. All report stock vermagic:
`7.0.0-38-generic SMP preempt mod_unload modversions`.
XHC1 also builds with W=1. Kbuild reports the compiler program-name difference
(`gcc` versus `x86_64-linux-gnu-gcc`) with the same Ubuntu 15.2.0 compiler;
BTF generation is skipped without vmlinux. There are no C compilation errors.

Real graphics CLI `--check`, `--install` and `--restore` pass inside this
filesystem, with actual modinfo, depmod, XZ, mkinitramfs and lsinitramfs. The
built image contains the override; the stock backup compares byte-identical,
the named entry has its stitch argument, and removal selects stock again.
DMI/DRM, reported uname and GRUB generation are simulated: the rootfs owns no
boot device. No host GRUB tool ran and no module was loaded.

The real DKMS audio check uses the production pinned source preparation and
Ubuntu guard, builds/signs/installs for the target ABI, checks driver identity
and compression, then removes it and verifies stock selection. In this
single-UID namespace only, TAR_OPTIONS=--no-same-owner avoids archive-owner
IDs that cannot be mapped; this is a validation setting, not a runtime change.

SHA-256 values before stripping/signing:

- Ubuntu source archive: `1610ed026817da29c6be30c2d9c639287ea472d5b805a1f23e2d576be6be6222`
- amdgpu: `a0a37e5662247f0237e824a74f9b51161297ab0c767ae7ee07b6f9351d622f9d`
- XHC1: `54b6b6aea3c7e840f4bc4d38f7d69b842e4740cdfa725cb48cf61de3151658e9`
- direct CS8409 build: `5c7543e5dad94fcddfee77021f5dd00e1c94b7cff8c9f530dd20fb22a74f32f8`

Logs are in `~/.cache/imac-ubuntu-validation/`: `ubuntu-build.log`,
`ubuntu-xhci-build.log`, `ubuntu-audio-build.log`,
`ubuntu-install-restore.log` and `ubuntu-dkms-audio-final.log`. The source
port's pristine/patched trees and intermediate context logs are in `port-7.0`.

The full offline suite passes **657 tests, no skips**, including required
startup and both private audio integration subsets. This includes the Debian
transaction regression cases, Ubuntu source/flavour/signing checks, the real
launcher on Ubuntu identity, exact audio source installation and its retained
DKMS guard. Bash syntax and git diff --check pass.

```bash
IMAC5K_REQUIRE_STARTUP_TESTS=1 IMAC5K_REQUIRE_EQ_AUDIO_TESTS=1 \
  IMAC5K_REQUIRE_T2_AUDIO_TESTS=1 ./scripts/check.sh
```

Ubuntu hardware boot, active 5K, motion/genlock, Secure Boot module loading,
physical audio and repeated sleep remain untested. Other Ubuntu releases and
HWE ABIs were not compiled in this session. Existing model/desktop limits
remain: KDE Wayland colour, no GNOME colour integration, no Ubuntu firmware
brightness/iGPU path, no automatic T2 driver stack. User instructions:
[docs/ubuntu.md](../docs/ubuntu.md).

## Publication follow-up

On the owner's request, `debian-backend` is based on `main` after PR #15's
merge (`36721644e48f1605e9be3829d2290ee0827f15d5`). Its root-plane guard is
included in the shared 7.1/7.2 list and both consolidated ports. The final
Ubuntu port applies at zero fuzz to the exact Ubuntu 7.0.0-38.38 source;
its changed `amdgpu_dm.o` compiles against the real Ubuntu headers in isolated
Ubuntu userspace. The hashes above record the earlier full builds before
this guard. The final integrated branch passes **657 tests, no skips**, with
startup and both private audio subsets required, including release-archive
checks for the new APT files. Validation logs are retained under
`~/.cache/imac-apt-publication-2026-10-26/`. No new release was requested;
the hardware limits above still apply.
