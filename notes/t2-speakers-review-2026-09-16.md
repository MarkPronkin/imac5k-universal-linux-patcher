# iMac Pro T2 speaker fixes — 2026-09-16

Reviewed and fixed the `t2speakers` module for `iMacPro1,1` in the working tree
based on `c57b129`. Scope is the T2 speaker path, its dependency declarations,
documentation and tests. Existing staged and unrelated changes were preserved.
Nothing was committed, pushed, installed on the host, or released.

## Fixes

1. **Select the correct device.** The previous suffix-only lookup could select
   an unrelated USB or HDMI Pro Audio output. Both the rule and helper now
   require the **Apple T2 Audio** card, playback stream, exact `pro-output-0`
   suffix and four channels. Missing or ambiguous targets stop application
   before the rule is changed. Headphones, loopback, capture nodes, other
   profiles and other channel counts are excluded. PCI addresses and mutable
   ALSA card IDs are not hardcoded.
2. **Make stereo reach all four channels.** A four-port map plus upmix settings
   on the sink left the second pair silent: ordinary clients had already
   expanded stereo into a four-channel stream containing two silent channels.
   The new rule explicitly exposes two stereo input ports and converts them
   to four hardware channels in the device adapter. Simple upmix copies the
   front signals to the second pair using PipeWire's standard rear-channel
   gain; it does not use ambient extraction or added rear delay.
3. **Verify effective state.** Status checks the installed rule, recovery
   record, device identity, advertised and active hardware formats, stereo
   input ports, actual port configuration and runtime mixer parameters.
   Requested node properties alone cannot produce `applied`. A failed device,
   missing ports, conflicting configuration or changed runtime mixer settings
   produces `partial`.
4. **Check compatibility and reload errors.** Require Python, PipeWire's
   `pw-dump`, WirePlumber 0.5+ and an active systemd user service before apply.
   Check version, command failures and timeouts. Restart only WirePlumber;
   verify the result with bounded polling. The module does not change the
   selected card profile, default sink or volume. It refuses root mutation
   and configuration-directory overrides that bypass its rule location.
   Missing Python remains a dependency failure on an applicable iMac Pro;
   it no longer makes an apply operation silently skip as N/A.
5. **Preserve user configuration.** Recognize only the exact current rule or
   the exact former generated rule. Refuse user edits, symlinks, nonregular
   files and invalid UTF-8 without replacing them. Migrate the original rule
   automatically. Honor absolute XDG config/state paths and preserve unrelated
   files and directories.
6. **Recover failed operations.** Use atomic rule replacement, a per-user
   operation lock and a recovery record written before mutation. On failed
   apply, restore the previous managed rule and its permissions, then reload.
   Recheck contents before replacement and deletion; preserve user edits made
   during preflight, writing, reloading or rollback. A failed rollback remains `partial` and
   directs the user to `--remove t2speakers` for recovery.
7. **Keep removal retryable.** Propagate unlink and reload failures. Retain
   pending state if reload fails after the rule has already been removed, so
   a second removal retries it. Removal does not require a target sink,
   `pw-dump`, PulseAudio or an active PipeWire server. An inactive WirePlumber
   service picks up the removed rule at its next start.
8. **Integrate dependencies and packaging.** Update the launcher audit and
   Arch/Fedora package mappings, ensure release archives contain the new
   helper, and document prerequisites, recovery and hardware limits.

## Files

- [T2 helper](../scripts/t2-speakers.py)
- [Module wrapper](../scripts/imac-patcher), [package mapping](../scripts/lib/platform.sh)
- [Lifecycle/selection tests](../tests/test_t2speakers.py)
- [Real audio conversion tests](../tests/test_t2speakers_audio.py)
- [Startup tests](../tests/test_startup.py), [archive tests](../tests/test_release.py)
- [README](../README.md), [dependencies](../DEPENDENCIES.md),
  [development guide](../docs/development.md)

## Source checks

The T2 driver sets its card name to `Apple T2 Audio` and assigns speaker PCM 0.
Its internal driver label `AppleT2` must not be confused with PipeWire's
`alsa.driver_name`, which is obtained from the kernel module symlink.
Sources: [apple-bce audio driver](https://github.com/t2linux/apple-bce-drv/blob/master/audio/audio.c),
[PipeWire ALSA properties](https://github.com/PipeWire/pipewire/blob/master/spa/plugins/alsa/acp/alsa-util.c).

PipeWire normally exposes a device's channels directly and performs remixing
in client streams. The corrected device adapter setup uses `node.param.PortConfig`
and WirePlumber's `item.features.no-format`; the latter is present in 0.5.0.
Sources: [PipeWire properties](https://docs.pipewire.org/page_man_pipewire-props_7.html),
[WirePlumber 0.5.0 adapter](https://github.com/PipeWire/wireplumber/blob/0.5.0/modules/module-si-audio-adapter.c).

## Validation and limits

```bash
IMAC5K_REQUIRE_STARTUP_TESTS=1 IMAC5K_REQUIRE_T2_AUDIO_TESTS=1 bash scripts/check.sh
git diff --check
```

**All 444 tests passed**, including the required isolated launcher and native
audio tests, with no skips. Bash syntax and diff checks passed. A comparison
with the pre-review snapshot confirmed that staged and unrelated changes were
preserved.

T2 coverage comprises **59 tests**: 55 selection/lifecycle/wrapper checks and
four real virtual-audio checks. The latter use private PipeWire and PulseAudio
sockets, a null sink and a WirePlumber policy with hardware monitors disabled.
Recorded device-output samples demonstrate:

- the old four-port setup leaves channels 3 and 4 silent;
- corrected native PipeWire stereo reaches all four channels, even when
  application upmix is disabled;
- corrected PulseAudio stereo reaches all four channels;
- mono reaches both pairs.

The test uses PipeWire 1.6.8 and WirePlumber 0.5.17. It parses the actual rule
with `pw-config`, uses its properties, and checks the same live state as the
runtime helper. These tests do not establish physical speaker order, loudness,
frequency response, driver stability or operation on every supported software
version. Those still require an iMac Pro hardware check. The host's audio
services and hardware configuration were not changed.

Full test log: `/tmp/imac-t2-check.log`.
Scope verification: `/tmp/imac-t2-final-scope.json`.
