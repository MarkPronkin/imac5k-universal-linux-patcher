# Speaker retune review — issue #6, 2026-09-21

Requested: review the new tuning in
[issue #6](https://github.com/MarkPronkin/imac5k-universal-linux-patcher/issues/6)
and add it to `test`. The owner explicitly chose **commit locally only**;
`test` already had 13 unpublished macOS/video commits before this work.
No push, release, GitHub comment or live audio apply is part of this change.

## Reviewed source

- Current: taprobane99/iMac5KLinux
  [`d82e423a9a97a2cf2f0f8d4664025241d91ce3c2`](https://github.com/taprobane99/iMac5KLinux/tree/d82e423a9a97a2cf2f0f8d4664025241d91ce3c2/Audio).
- Previous: `5069f81eeb4af129480604762f39f9eaec9898d7`.
- The new config and every WAV in the pinned `Audio/` directory are vendored
  byte-for-byte. Upstream's installer is not run or bundled.
- The existing MIT notice matches the current upstream licence byte-for-byte.
  Asset checksums and attribution are in `assets/imac-audio/README.md`.

## DSP review

The new four mono WAVs are 48 kHz, 32-bit IEEE float, 2048 frames each.
Their `-48k` filenames replace the older unsuffixed names. The graph removes
all separate crossover and peaking-filter stages: the new FIRs contain the
crossover and EQ. Keeping the old graph with the new FIRs would apply both
sets of filtering. Bankstown controls, woofer compressor settings, woofer
convolver gain (0.4), volume mapping and FL/FR tweeter + RL/RR woofer channel
order are retained. The LSP loudness controls now initialize at -20 dB.

The author reports ±4 dB from 100 Hz to 17 kHz and an Asahi-inspired method.
Those are upstream's claims about measurements on an iMac17,1, not local
measurements or validation on every supported iMac. Local testing establishes
that the graph loads, processes audio and routes all four outputs correctly;
listening and acoustic validation on the owner's iMac18,3 remain pending.

## Integration corrections

Upstream renamed both nodes to include `iMac 17,1`, changed the display label,
added a fixed `00:1f.3` playback target, and set `node.dont-fallback=false`.
A direct copy would break this patcher's sink lookup and headphone switching;
inserting another target key could let the fixed target override detection.

At install time the patcher keeps `audio_effect.iMac-convolver`, the
`iMac Speakers` label and the hidden DSP stream name. It replaces upstream's
target with exactly one detected four-channel speaker target, and sets both
`node.dont-move` and `node.dont-fallback` true. The stored source is unchanged.
Headphone switching, hardware/profile restore records and the T2 exclusions
are retained.

Installation discovers all bundled WAVs, including future rates, while
checking every path referenced by the graph before writing files. It records
installed filenames for removal after subsequent updates and keeps unrelated
user WAVs. A digest covers the selected graph and the bundled responses, so
updates with unchanged filenames still report `partial` until reapplied.

The previous WAVs remain at their original names, and their config is kept
as `iMacAudio-legacy.conf`. Both versions use the same installation guards:

```bash
./scripts/imac-patcher --apply eq
IMAC5K_EQ_TUNING=legacy ./scripts/imac-patcher --apply eq
```

The first selects the current version, the second the previous one. Normal
status compares against current tuning; pass `IMAC5K_EQ_TUNING=legacy` when
checking a deliberately selected legacy installation.

## Validation

- Vendored bytes compared to the pinned upstream archive; preserved config
  compared to the pre-change Git version; checksums verified by the suite.
- Installer regression tests cover the real retuned graph, different PCI
  addresses, stable names, all-rate install/removal, missing/empty responses,
  old-version detection, unchanged-name retunes, legacy selection, and
  preserving unrelated files during removal.
- `IMAC5K_REQUIRE_EQ_AUDIO_TESTS=1 python3 -m unittest discover -s tests -p
  test_eq_audio.py -v` passes. Both graphs run with real LSP/bankstown plugins
  on a private PipeWire server with hardware monitors disabled. All four
  channels produce finite, non-silent samples; all four DSP links terminate
  at the intended virtual speaker sink. No desktop audio service is used.
- `IMAC5K_REQUIRE_EQ_AUDIO_TESTS=1 ./scripts/check.sh`: **516 tests pass,
  no failures or skips**. Includes release archive/install/upgrade checks and
  the isolated startup tests. Log: `/tmp/imac-issue6-check.log`.

The sandbox blocks private sockets and writing temporary Git objects used by
release tests. Validation runs outside it as a normal user; no system patches
are applied. The first private DSP run needed its JSON test-server config
formatted for PipeWire's parser; both tuning versions passed after that fix.
