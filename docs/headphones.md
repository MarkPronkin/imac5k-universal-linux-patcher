# Headphones and headset microphones

On an iMac18,3 with a CS8409 codec and Linux 6.17 or later:

```bash
./scripts/imac-patcher --apply audio
# Reboot, then check:
./scripts/imac-patcher --status
```

This also upgrades an existing audio installation. A driver replaced on disk
does not change the one already loaded; status remains `partial` until the
patched driver is running. On Arch, installed kernels with matching headers
are built too, so a pending kernel update can boot with the fixes. Fedora
builds for the running kernel and checks DKMS's Secure Boot key before
refreshing its initramfs.

The patch fixes headset microphone capture, reroutes an open recording when
the jack changes, lets the internal microphone mixer control its actual gain,
raises headset capture gain, and serializes jack events against stream setup.
Apple EarPods inline buttons emit play/pause, volume up and volume down keys;
your desktop handles those keys. Headphones without a microphone retain the
internal microphone. USB and Bluetooth devices use their own drivers.

## Switching between the speakers and the jack

With the speaker tuning installed (`--apply eq`), plugging headphones into
the iMac's jack hides **iMac Speakers** and exposes **Aux Audio Output** —
the jack itself, with no tuning applied. Unplugging brings the speakers back.
Whatever is playing follows in both directions.

The headphone port exists only in the card's stereo profiles, so plugging in
moves the card off Analog Surround 4.0 on its own. What does not happen on
its own is the tuning going away: it is a filter graph rather than a device,
so it survives the profile change, stays selectable, and its four channels
get folded into the two the jack has. That fold is the crossover summed back
together, over headphones the tuning was never measured for.

So the graph runs as its own service, `imac-speaker-eq.service`, and
`imac-audio-jack.service` stops it while the jack is in use. Both are user
units pulled in by `pipewire.service`. The jack is followed through
PipeWire's own port availability — event-driven, and needing neither root
nor membership of the `input` group.

An output you selected yourself is left alone: audio sent to Bluetooth or
HDMI is not pulled back to the jack, and only streams on the sink being
taken away are carried across.

The tuning's own output is a playback stream, so it would otherwise appear in
the panel's application list as "iMac Speakers DSP Out" whenever the speakers
play. Omarchy already skips a tuning's output but recognises it by node name,
so the installer renames that node into its convention.

With the tuning stopped and headphones out, the only built-in output is the
hidden 4.0 device. If `imac-speaker-eq.service` fails to start you therefore
get silence rather than untuned speakers; `--status` reports `partial` and
`journalctl --user -u imac-speaker-eq` says why.

Applying or repairing speaker EQ refuses to raise the hardware output while
the card reports connected headphones. Unplug them before applying speaker
tuning; that level is for the internal drivers.

## Verify on the machine

After reboot, test at a comfortable volume:

1. Play audio through the internal speakers, then plug in and unplug headphones.
2. Keep a recording open while plugging in a headset with a microphone and
   unplugging it again. Capture should follow the jack without going silent.
3. Try headphones without a microphone; the internal microphone should remain
   usable.
4. Check each EarPods inline button. Play/pause needs an application that
   handles the media key.
5. With `eq` applied, plug in while music plays: **iMac Speakers** should
   leave the output picker, **Aux Audio Output** should take over, and the
   music should keep playing untuned. Unplug and it should switch straight
   back. `journalctl --user -u imac-audio-jack -f` follows the decisions.

The source patch was tested upstream on iMac18,3 with kernel 7.1.9-arch1-2.
The patched driver also compiles against this machine's 7.2.3-arch1-3 headers.
The universal installer and its removal paths have offline regression tests;
these do not establish physical headphone behavior on Fedora or other kernels.
Upstream still reports a loud high-pitched artifact at the instant a headset
is plugged in. Its cause remains unresolved; this port carries that limitation.

## Undo

```bash
./scripts/imac-patcher --remove audio # remove DKMS audio versions; reboot
```

Removing the driver returns to the kernel's stock CS8409 driver, which lacks
working speakers on this board.

## Source

The driver patch comes from
[ahmadtv/omarchy-imac5k at da2e6c8](https://github.com/ahmadtv/omarchy-imac5k/tree/da2e6c8d97ed250cdd3376decd075e596528c190),
under the MIT license. The driver base is
[jackdanyell's be90113](https://github.com/jackdanyell/imac18-3-cs8409-linux-audio/tree/be90113a7638eb264b2ff5acfe888cd72c8364c6).
The original driver patch is retained verbatim, including its hardware notes.
