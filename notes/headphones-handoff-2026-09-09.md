# Headphone fixes — handoff, 2026-09-09

## Request and stopping point

Two rounds of work, both on 2026-09-09.

**First round.** "Can you add headphones fixes and better behaviour for this
version https://github.com/ahmadtv/omarchy-imac5k". Ported the headset driver
patch and an optional Omarchy audio-panel integration into this patcher.

**Second round (current).** The user tested on hardware: headphones work, the
panel module is not wanted, and the real problem is that plugging headphones in
left **iMac Speakers** selectable and routed the four-channel tuning into the
jack, which sounds wrong. Asked to remove the panel module and to hide the iMac
output while wired headphones are connected, exposing an untuned "aux audio
output" instead, switching back on unplug.

**Both are done and validated on the machine.** The panel module is gone. The
speaker tuning now runs as its own service and is stopped while the jack is in
use. The user confirmed the switching works in both directions; the jack output
was renamed after they reported it showing as "CS8409/CS42L83 Analog".

Suite: **155 tests, no failures or skips**. `--remove eq` and `--apply eq` were
both run for real on this machine and verified end to end.

Repository: `/home/markpronkin/imac5k-universal-linux-patcher`.
Branch: `main`; HEAD is still
`19f27723f2d0a0c71c6e005bc164a4ba14bb35af` — **nothing has been committed**.
The new runtime files are staged; other edits are unstaged. No push, release or
upstream submission was made.

## Source revisions

- Audio/panel source: `ahmadtv/omarchy-imac5k`, commit
  `da2e6c8d97ed250cdd3376decd075e596528c190`, fetched on 2026-09-09.
- Driver base: `jackdanyell/imac18-3-cs8409-linux-audio`, pinned to
  `be90113a7638eb264b2ff5acfe888cd72c8364c6`.
- New DKMS identity: **`snd_hda_macbookpro/0.2.imac5k1`**. Bump the version if
  the bundled driver changes so an old build cannot satisfy the new installer.
- `patches/cs8409-headset-capture.patch` is copied verbatim from the linked
  repository. SHA-256:
  `f732f7ae59ac7cb98de337a972bd5623574618b6388740c1699fe765c9d56b27`.
- The panel integration that revision also supplied was removed in the second
  round; only the driver patch is still used from it.

## Implemented behavior

### Driver and installation

The imported driver patch fixes headset microphone ADC selection; follows
plug/unplug events while a recording remains open; makes the internal mic's
mixer gain effective; raises headset capture gain; serializes jack events and
PCM setup with a mutex; and emits EarPods play/pause, volume-up and volume-down
keys. The patch adds the `headset_buttons` module parameter, enabled by default.

The universal installer retains the **iMac18,3 + CS8409 hardware gate**, and
requires **Linux 6.17+** because earlier kernels use a different HDA patch and
lack the added spec fields. `audio_prepare_source` exports the pinned Git
commit to a temporary directory, applies the headset patch with `--fuzz=0`,
and sets the distinct DKMS version. Cached checkout edits and untracked files
are preserved; there is no `git reset`, forced checkout, or `git clean`.

Both backends use shared DKMS add/build/install logic. The build completes
before replacing an older installed version for that kernel. Old `0.2`
registrations cannot cause the new patch to be skipped. A competing CS8409
DKMS package is reported and the install stops; it does not delete another
package's source or registration automatically. Download, patch, build,
install, verification and removal failures return nonzero instead of being
hidden by later successful commands.

On Arch/Omarchy, audio builds for every installed supported kernel with
matching headers, including a pending update whose headers replaced the
running kernel's headers. It refreshes the initramfs through
`limine-mkinitcpio` or `mkinitcpio -P`. Fedora still targets the running kernel,
requires its exact `kernel-devel`, checks the DKMS signing-key enrollment
before refreshing the initramfs, and uses dracut.

Status verifies the versioned DKMS registration and the module actually
resolved by `modinfo`, including the patch's `headset_buttons` parameter. The
loaded module is checked using its sysfs parameter and `srcversion` compared
with the installed file. An old loaded driver remains `partial` until reboot;
a missing pending-kernel build also remains `partial`. Removal handles old
and new versions, including registrations in the `added` state, and refreshes
the appropriate initramfs.

### Omarchy panel module — removed

The `panel` module and everything specific to it were deleted at the user's
request: `scripts/lib/audio-panel.sh`, `scripts/imac-audio-ports`,
`scripts/imac-audio-set-port`, `patches/omarchy-audio-ports.patch` and
`tests/test_audio_panel.py`, plus its registration in `imac-patcher`, its rows
in the docs, and the `jq` install steps the two CI workflows only needed for
its tests. `MODULES` is back to `audio eq color suspend boot 5k`. It had never
been applied on this machine — no state file, no helpers in `~/.local/bin`, no
Omarchy clone — so removal was repository-only.

### Headphone switching (the second round's real work)

**What was actually wrong.** WirePlumber already does the hardware half
correctly: the headphone port exists only in the card's stereo profiles, so
plugging in moves the card off `output:analog-surround-40+input:analog-stereo`
and unplugging moves it back. Verified by capturing both transitions. What it
cannot do is take the tuning away — the chain is a filter graph, not a device,
so it survived the profile change, stayed the default, and its four channels
were folded into the jack's two. That fold is the crossover summed back
together. The "separate cs8409 output that sounds ok" the user described was
the raw `alsa_output.pci-0000_00_1f.3.analog-stereo` sink.

**Design.** The graph moved out of the session daemon into a PipeWire client of
its own, because a module loaded by the daemon lives as long as the daemon
does and could not be hidden at runtime. `EQ_CONF` moved from
`~/.config/pipewire/pipewire.conf.d/imac-audio.conf` to
`~/.config/pipewire/imac-speaker-eq.conf.d/imac-audio.conf`, with a base config
beside it modelled on `/usr/share/pipewire/filter-chain.conf`. The downloaded
graph stays byte-identical to upstream's; only the base config is ours. Apply
deletes the old in-daemon file, or the chain would load twice.

Two user units, both `WantedBy=pipewire.service` and `BindsTo=` it, so they
follow a restart of the audio stack:

- `imac-speaker-eq.service` — `pipewire -c imac-speaker-eq.conf`.
- `imac-audio-jack.service` — `~/.local/bin/imac-audio-jack-switch`.

The switcher follows the jack through `pactl subscribe` on card events, then
reads headphone port availability. Event-driven, no polling. Deliberately not
evdev: `/dev/input/event22` is the `SW_HEADPHONE_INSERT` switch but is
`root:input` and **the user is not in the `input` group**.

On plug it waits for the flat sink, stops the tuning unit, claims the default
and carries streams over; on unplug it waits for the 4.0 profile, starts the
tuning unit, and carries them back. It reconciles once at startup, so a jack
already in use at login or across a PipeWire restart is handled. An output the
user chose themselves (Bluetooth, HDMI) is never taken over: the default is
only claimed from the tuned sink or `auto_null`, and only streams on the
departing sink are moved.

The WirePlumber drop-in gained a second rule naming the jack output **"Aux
Audio Output"** with a headphones icon. It sets **both** `node.description` and
`node.nick`: the first attempt set only the description and Omarchy's panel
still showed "CS8409/CS42L83 Analog", which is `node.nick` from ALSA. Matched
by exact node name derived from the detected card, not by pattern — the user
has an AudioQuest DragonFly whose sink is also an `analog-stereo` one.

**The tuning's own output.** The user then reported seeing "iMac Speakers DSP
Out" listed while the speakers played. That is `playback.props` of the filter
chain: a `Stream/Output/Audio` node, so panels list it beside applications.
There is **no** hide property for this — `node.hidden`/`stream.hidden` and the
like do not exist in PipeWire or WirePlumber (checked by `strings` over both
libraries), and `object.register = false` is already set upstream and does not
help. What does exist is a convention in Omarchy's own panel, which skips any
playback stream whose `node.name` starts with `omarchy_speaker_tuning`
(`/usr/share/omarchy/shell/plugins/panels/audio/Panel.qml`, `candidateStreams`).
So apply renames that node to `omarchy_speaker_tuning_imac5k_output` with a
`sed`, alongside the impulse-response path rewrite it already did. The rename
is cosmetic, so a config that no longer carries upstream's name warns rather
than failing the apply. Do not rename the *sink*, `audio_effect.iMac-convolver`
— everything else refers to it by that name.

`mod_eq_detect` had to learn the headphone case: with the jack in use the
tuning is *meant* to be stopped and the card *meant* to be on stereo, so
looking for the tuned sink and the 4.0 profile would report a working install
as broken. It checks for the flat jack output instead. It also weighs the two
units and the installed helper.

**Known consequence, documented in README and `docs/headphones.md`:** with the
tuning stopped and headphones out, the only built-in output is the hidden 4.0
device, so a failed `imac-speaker-eq.service` means silence rather than untuned
speakers. This is not new — the hide rule always had that property — but the
service is one more thing that can fail. `Restart=on-failure` is set and
`--status` reports `partial`.

### Vendoring the tuning (third round)

The user asked for the EQ assets to come from this repository instead of being
downloaded, because upstream could push breaking changes. The concern is real
and current: `EQ_UPSTREAM` pointed at taprobane99/iMac5KLinux **`main`**, and
`Audio/iMacAudio.conf` was rewritten three times inside one hour on 2026-09-03.

**The licence problem was raised before doing it.** That project has no
`LICENSE` file and the GitHub API reports `license: None`, so no redistribution
terms have been granted — which is exactly why the first round fetched rather
than vendored. The user was offered pinning-plus-checksums (fixes the stated
reliability problem, redistributes nothing), vendoring, or pinning now and
asking upstream for a licence. **The user chose to vendor.** That is the
repository owner's call and it was made with the licence position stated
plainly; do not silently revert it, and do not re-litigate it.

Five files now live in `assets/imac-audio/`, byte-identical to upstream commit
`5069f81eeb4af129480604762f39f9eaec9898d7`, with `assets/imac-audio/README.md`
recording provenance, the SHA-256 of each file, why they are vendored, the
absent licence, and an offer to remove them if the author objects. They are
kept byte-identical *on purpose*: it is what makes the checksums checkable
against upstream. Apply still rewrites the IR paths and the output node name at
install time rather than in the stored copies.

`eq_fetch` is gone, replaced by `eq_assets_present`, which refuses before
anything is installed if a file is missing — otherwise the graph installs with
convolvers pointing at absent files and the sink never appears. `curl` is no
longer an `eq` dependency. `assets` was added to `make-release.sh`'s `PATHS`.

`tests/test_eq.py` gained a `VendoredTuningTests` class that checks the files
are present, match the checksums recorded beside them, and still carry the two
things apply rewrites — so a future update to the vendored files cannot
silently change the tuning or silently stop a rewrite from applying.

One test had to change for an unrelated reason: the release test that builds
from an annotated tag tagged `HEAD`, which predates `assets/`, and `git archive`
is a hard error when a pathspec matches nothing. It now tags the same worktree
ref the other release tests build from.

### Removing the AUR requirement (fourth round)

The user asked that the patcher work on Arch without the AUR. The only AUR
dependency was **bankstown**, the psychoacoustic bass extension the chain starts
with; `eq_plugins` used to shell out to `yay`/`paru`, and refused if neither was
present. On Fedora it refused always, telling the user to build it by hand.

The AUR PKGBUILD turned out to be nothing but `cargo build --release` plus an
install of three files, so `eq_build_bankstown` now does exactly that: clones
`chadmed/bankstown` pinned to tag **1.1.0** (`e9829c9bccf5ed73768135c0ddd506f5a6690f9e`),
exports it to a temp dir rather than building in the cached clone, runs
`cargo build --release --locked`, and installs `bankstown.so` plus the two TTLs
into `~/.lv2/bankstown.lv2/`. No root, no AUR helper, and the same code path
fixes Fedora. bankstown is **MIT licensed** — unlike the tuning — and upstream
has not changed since 2023-12-29, so this raised no redistribution question.
Nothing is built when `eq_have_lv2` already finds a bundle, so a distribution
package or the user's own copy wins.

Removal deletes the bundle **only** if `${LOGDIR}/eq-bankstown` records that
this module built it. A packaged or hand-built bankstown is left alone.

Verified by building it for real on this machine into a scratch prefix: the
TTL files came out byte-identical to the installed AUR package's, and a
PipeWire instance run with `LV2_PATH` pointing at *only* the freshly built
bundle plus the system lsp-plugins loaded the whole filter chain and produced
the sink. That is the real proof, since this machine has the AUR package
installed and would otherwise have satisfied the plugin from there.

`cargo` and `git` are reported as `eq` dependencies only when bankstown is
actually missing, so a machine that already has it needs no Rust toolchain.

### Speaker EQ guard

Kept this fork's measured four-channel EQ and `eq_headphones_present`, which
reads headphone availability from the specific speaker card even when its raw
sink is hidden. Applying EQ or repairing its hardware volume still refuses
while that card reports headphones connected.

## Exact files changed by this work

New runtime/documentation files:

- `assets/imac-audio/` (staged) — the vendored tuning plus its provenance
  README. Not this project's work; see the licence note above.
- `patches/cs8409-headset-capture.patch` (staged)
- `scripts/imac-audio-jack-switch` (staged, executable)
- `docs/headphones.md` (staged)

New tests:

- `tests/test_audio.py` (staged) — 17 tests covering pin/export preservation,
  upgrades, pending kernels, reboot-aware detection, conflicts, failures,
  removal, Fedora integration and Secure Boot handling.
- `tests/test_audio_jack.py` (staged) — 12 tests covering card identification,
  jack availability, which streams follow the jack, not overriding a user's own
  output choice, and both switching transitions.

Deleted (second round): `scripts/lib/audio-panel.sh`, `scripts/imac-audio-ports`,
`scripts/imac-audio-set-port`, `patches/omarchy-audio-ports.patch`,
`tests/test_audio_panel.py`.

Modified files:

- `scripts/imac-patcher` — audio implementation; EQ reworked onto its own
  service plus jack switching; new detect, apply and remove paths; panel
  registration removed.
- `scripts/lib/fedora.sh` — shared patched driver path, running-kernel
  targeting, dependencies and shared removal.
- `tests/test_eq.py` — a `systemctl` stub with unit state, a trace file for
  ordering, and tests for the headphone detect case, the pre-service config
  migration and the stop/restart/profile/start order. 24 tests.
- `tests/test_models.py` — supply the repository path to the audio harness.
- `tests/test_release.py` — require the driver patch, the switching helper and
  the headphone guide in the release archive.
- `README.md`, `DEPENDENCIES.md`, `docs/development.md`,
  `docs/fedora-kde.md`, `patches/README.md` — usage, the headphone behaviour,
  dependencies, provenance and limitations.
- `.github/workflows/check.yml`, `.github/workflows/release.yml` — reverted to
  their committed state; the `jq` step existed only for the panel tests.

## Validation completed

1. The imported headset patch applied to the exact pinned driver with
   `--batch --forward --fuzz=0`, and the file is still byte-identical to
   upstream (SHA-256 above re-verified).
2. The headset driver compiled successfully against the installed
   `7.2.3-arch1-3` headers using the cached 7.2.3 HDA source. Unprivileged
   compile, without loading or installing the module. (First round.)
3. Both jack transitions were captured on the real machine before any code was
   written, confirming WirePlumber's own profile switching and the fold of the
   four-channel chain into the jack.
4. The standalone `pipewire -c` instance was verified to produce the same sink
   and the same four links as the in-daemon graph; stop/start makes the sink
   disappear and reappear; both units survive `systemctl --user restart
   pipewire` and come back through `WantedBy=pipewire.service`.
5. The downloaded graph was diffed against upstream's `iMacAudio.conf` with the
   IR paths rewritten: identical, so re-applying destroys no local tuning.
6. **`--remove eq` and `--apply eq` were run for real on this machine.** Removal
   left no file, unit or enablement behind; apply produced enabled and active
   units, the tuned sink alone, the 4.0 profile, eight links, the naming rule
   with the correct card-derived node name, and the hardware output at 100%.
7. The user confirmed on hardware that plugging in hides iMac Speakers and
   exposes the untuned jack output, and that unplugging switches back.
8. `tests/test_audio_jack.py` was mutation-checked: breaking `claim_default`'s
   ownership test and removing the wait for the jack output each failed exactly
   the test written for it.
9. The output-node rename was verified live: the node is
   `omarchy_speaker_tuning_imac5k_output`, the sink keeps its name, and all
   eight links survive.
10. After vendoring, `--remove eq` and `--apply eq` were run again: the
    installed graph is byte-identical to the validated one, with no network
    access, and a release archive was built and extracted to confirm
    `assets/` lands beside `scripts/` so `EQ_ASSETS` resolves.
11. Final `./scripts/check.sh`: **150 tests passed, no failures or skips**,
   including release packaging/install/upgrade and the isolated startup tests.
   `git diff --check` is clean for every file this work touched; the warnings it
   prints for `patches/cs8409-headset-capture.patch` and
   `assets/imac-audio/iMacAudio.conf` are upstream's own whitespace in files
   that are byte-identical on purpose, and must not be "fixed". The tuning's
   checksum test fails if they are.

## Other working-tree changes

The following deletions appeared during the work and **were not made by this
task**. They were left untouched and excluded from the validation clone's
task edits. Do not restore them or include them in an audio commit by accident:

- `notes/issue-4455-reply-3-lean.html`
- `notes/issue-4455-reply-3-lean.md`
- `notes/issue-4455-reply-4-rebootpci.html`
- `notes/issue-4455-reply-4-rebootpci.md`

## Remaining work if the user continues

Nothing is unfinished and no command is pending. **Nothing has been committed**
— the obvious next step is a commit, if the user wants one.

Not yet exercised on hardware, from the first round's driver work: recording
held open across unplug/replug, headphones without a microphone, and the
EarPods inline buttons.

**Known unresolved issue:** upstream reports a loud high-pitched artifact
at headset insertion. This port carries it; do not claim it is fixed.
Upstream's physical headset validation was on iMac18,3, `7.1.9-arch1-2`.

Behaviour worth knowing before changing anything here:

- With the tuning stopped and headphones out, the only built-in output is the
  hidden 4.0 device, so a failed `imac-speaker-eq.service` is silence, not
  untuned speakers.
- The naming rule matches one exact node name. If the card's PCI path ever
  changes, re-apply `eq` to rewrite it.
- If the user manually selects the stereo profile with headphones out, the
  sink is still called "Aux Audio Output" while actually driving the speakers.

If committing or preparing a release later, stage only the intended files.
The release allowlist already includes `scripts`, `patches` and `docs`, so it
picks up the new runtime files now that they are tracked. The handoff under
`notes/` and the root `AGENTS.md` are not part of release archives.
