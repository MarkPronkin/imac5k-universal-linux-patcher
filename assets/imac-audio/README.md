# Speaker tuning assets

The tuning is **taprobane99's work**, measured on an iMac17,1 with a calibrated
microphone in [iMac5KLinux](https://github.com/taprobane99/iMac5KLinux).
The retune from [issue #6](https://github.com/MarkPronkin/imac5k-universal-linux-patcher/issues/6)
is the default. Its four FIR responses now include the crossover and EQ;
the old graph's separate biquad stages are gone. Bankstown bass extension,
LSP loudness compensation and the woofer compressors remain.

Upstream reports ±4 dB from 100 Hz to 17 kHz. This is the author's measurement
on an iMac17,1, not an acoustic validation on every supported model.

## Current tuning

Vendored byte-for-byte from commit
[`d82e423`](https://github.com/taprobane99/iMac5KLinux/tree/d82e423a9a97a2cf2f0f8d4664025241d91ce3c2/Audio),
fetched 2026-09-21. The four responses are mono, 48 kHz, 32-bit IEEE float,
2048 frames each. No other rates are shipped yet.

```
bf4cb2d02a3583461c9945b008d409479cf09977b4184cd554fc48a14400e708  iMacAudio.conf
1f251101260119fa37554f5e66d4e263d9b1e31196722f19820a5e75f1e6ccff  Filters C2 Aug 16-MP-48k.wav
f0caac56fdcfd87a31e7a0851f0441449907795081ff679ab87ad92f62b47e0f  Filters L Aug 14-MP-48k.wav
9efe24947ea47e6ee0d14e575e510cfac509c81ae1d2e22ad56d41bbc9caaa78  Filters LFE Aug 16-MP-48k.wav
9a198769dd0ee05c477abeb58d225cae054496a3de9ca0c633fa4b3fc5c23de1  Filters R Aug 14-MP-48k.wav
```

## Previous tuning

Preserved byte-for-byte from commit
[`5069f81`](https://github.com/taprobane99/iMac5KLinux/tree/5069f81eeb4af129480604762f39f9eaec9898d7/Audio).
Only the config's filename changed, from `iMacAudio.conf` to
`iMacAudio-legacy.conf`. Its separate 3.8 kHz crossover and EQ stages and
original responses remain available for listening comparisons:

```
6acf1f8a7a1f27a35bb1c4fa810236252c373837bc0e3e163662c93701eb42ea  iMacAudio-legacy.conf
9d576f60bbe203c2ac430158ac5f80ae83684f13a81c26218f99b675202a9de7  Filters C2 Aug 16-MP.wav
2ab97a0a967e40b4caa8ea433b633dc1fbd11603520f45ba26a2f936f8f4630f  Filters L Aug 14-MP.wav
2e34c67c70c27d25bc3c4821892de4333a8b4703a1ddfdc4c258d643ae86c508  Filters LFE Aug 16-MP.wav
fb4d218b36cccc3cc7932ef969add934df8c4f272a2c86cd6926718b0f168f6c  Filters R Aug 14-MP.wav
```

From a checkout, apply the current tuning with:

```bash
./scripts/imac-patcher --apply eq
```

To compare the previous tuning, with the same headphone switching and routing:

```bash
IMAC5K_EQ_TUNING=legacy ./scripts/imac-patcher --apply eq
IMAC5K_EQ_TUNING=legacy ./scripts/imac-patcher --status
```

A normal apply selects the current tuning again. Status without the legacy
selection reports the old tuning as `partial`, indicating the available update.
Reapplying retains the original hardware-volume and profile restore records.

## Installation and provenance

All bundled `*.wav` files are installed together into
`~/.local/share/imac-audio/` (or `$XDG_DATA_HOME/imac-audio/`). Additional rates
can be vendored without changing a filename list. Every response referenced by
the selected config must be present and nonempty before installation starts.
Removal uses the bundled filenames plus a record of previously installed
responses; it preserves unrelated WAV files in the same directory.

Tuning is pinned in each patcher release, never fetched from upstream `main`
at apply time. That preserves reproducible installs and allows review before
an upstream graph change reaches users. Upstream's installer is not used.

The stored configs retain upstream's names and paths. Apply rewrites only the
integration settings:

- paths into the user's data directory;
- the stable `audio_effect.iMac-convolver` sink name and `iMac Speakers` label,
  which the headphone switcher and saved routes rely on;
- the DSP output name so Omarchy's audio panel omits it from applications;
- a single `target.object` for the detected four-channel speaker device,
  `node.dont-move=true` and `node.dont-fallback=true`, replacing the new
  upstream config's fixed PCI target and permissive fallback;
- `node.virtual=false` so desktop sound pickers expose the tuned speakers.

**Licence: MIT, copyright (c) 2026 taprobane99.** Upstream's `LICENSE` is
carried verbatim beside the assets. It covers both tuning versions; this
project's root licence does not replace that notice.
