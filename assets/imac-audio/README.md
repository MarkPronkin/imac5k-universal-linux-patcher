# Speaker tuning assets

These five files are **not this project's work**. They are the speaker tuning
from [taprobane99/iMac5KLinux](https://github.com/taprobane99/iMac5KLinux),
measured with a calibrated microphone: a PipeWire filter-chain that crosses the
four speaker channels over at 3.8 kHz, EQs each way, and convolves each with a
measured impulse response.

Vendored from commit
[`5069f81`](https://github.com/taprobane99/iMac5KLinux/tree/5069f81eeb4af129480604762f39f9eaec9898d7/Audio),
fetched 2026-09-09. They are byte-identical to that commit, so the checksums
below can be checked against it:

```
6acf1f8a7a1f27a35bb1c4fa810236252c373837bc0e3e163662c93701eb42ea  iMacAudio.conf
2ab97a0a967e40b4caa8ea433b633dc1fbd11603520f45ba26a2f936f8f4630f  Filters L Aug 14-MP.wav
fb4d218b36cccc3cc7932ef969add934df8c4f272a2c86cd6926718b0f168f6c  Filters R Aug 14-MP.wav
9d576f60bbe203c2ac430158ac5f80ae83684f13a81c26218f99b675202a9de7  Filters C2 Aug 16-MP.wav
2e34c67c70c27d25bc3c4821892de4333a8b4703a1ddfdc4c258d643ae86c508  Filters LFE Aug 16-MP.wav
```

They were previously downloaded at apply time from that project's `main`
branch. That made every install depend on whatever `main` happened to be:
`Audio/iMacAudio.conf` was rewritten three times within one hour on
2026-09-03, and a change to the graph reaches users as a tuning that sounds
different, or as a sink that does not load at all. They are vendored so that a
given release of this tool always installs the tuning it was tested with.

**Licence: the upstream project publishes none.** It carries no `LICENSE` file
and GitHub reports no licence for it, so no redistribution terms have been
granted. They are included here on the judgement of this repository's owner.
If you are taprobane99 and would rather these were not carried here, open an
issue and they will be removed.

`iMacAudioInstall.sh` from the same directory is deliberately not vendored:
this project installs the files its own way, into the user's home rather than
`/usr/share` with sudo.

## How they are used

`imac-patcher --apply eq` copies them out of here and rewrites two things in
`iMacAudio.conf` as it installs it:

- the impulse-response paths, from `/usr/share/imac-audio/` to the user's own
  `~/.local/share/imac-audio/`, so the module needs root for nothing;
- the name of the chain's own output node, so desktops do not list the tuning
  itself beside real applications.

The copies here keep upstream's paths and names, so they stay comparable with
the commit above.
