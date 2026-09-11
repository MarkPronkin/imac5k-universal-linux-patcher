# Wi-Fi (brcmfmac) suspend abort — handoff 2026-09-11

User request (2026-09-11, after the 0.2.0-alpha release): find out what can be
done about suspend aborting in brcmfmac; then "remember where you stopped
exactly". Investigation only: no code, boot, driver or power settings were
changed, and no suspend or pm_test was run.

## Stopping point (2026-09-11 15:27 CEST)

- Diagnosis done (below) and options presented to the owner. Waiting for the
  owner to run the staged test, which needs root (the agent has no
  passwordless sudo):

      sudo bash notes/wifi-d3-test.sh

  Three `pm_test=devices` runs in s2idle mode (Wi-Fi up, Wi-Fi down as
  NetworkManager leaves it, card unbound), about 30 s, self-restoring.
  Expected: up PASS, down FAIL, unbound PASS. Ask for its output first.
- Not done yet: the hook change, the real suspend test, and correcting the
  README and 0.2.0-alpha notes (see "Record to correct").
- Also unanswered from the 0.2.0-alpha summary: guard suspend against a
  pre-0.1.91 5K driver? Fast-forward `test` (`b4b0a61`) to `main`?

## Machine and repo state at the stop

- iMac18,3, Omarchy, 7.2.3-arch1-3, same boot since 2026-09-10 19:48:53,
  running the 0.1.92-alpha 5K driver build. Installed patcher: 0.1.92-alpha.
- suspend.target static (unmasked), hibernate family masked, Thunderbolt hook
  and `/etc/systemd/sleep.conf.d/imac5k-s2idle.conf` installed, mem_sleep
  `[s2idle] deep`, no `mem_sleep_default` on the cmdline.
- Wi-Fi unused: `wlp3s0` down and disconnected; NetworkManager and
  wpa_supplicant active (not iwd); default route over Ethernet `enp4s0f0`
  (tg3), plus USB Ethernet `enp0s20f0u4u2i4`. WoWLAN disabled. Unbinding the
  card cannot cut the network here.
- Repo: `main` = `origin/main` = `da90c1b` (v0.2.0-alpha) before this
  checkpoint; `origin/test` = `b4b0a61`.

## Findings

- Chip: BCM43602 `14e4:43ba` rev 01, Apple subsystem `106b:016f`, at
  `0000:03:00.0`. Firmware `brcm/brcmfmac43602-pcie` 7.35.177.61 of
  2015-11-10 (linux-firmware-broadcom 20260810-2), the only one Linux has; no
  clm_blob. The kernel has CONFIG_BRCMDBG=y and CONFIG_BRCM_TRACING=y.
- The only suspend attempts in the retained journal (2026-09-10 19:51 and
  19:52, boot `4f73600e`) all aborted: `brcmf_pcie_pm_enter_D3: Timeout on
  response for entering D3 substate`, `pci_pm_suspend ... returns -5`, "Some
  devices failed to suspend", then systemd's "Failed to put system to sleep.
  System resumed again: Input/output error". Each attempt shows two s2idle
  entries (systemd falling back through its SuspendState list). The
  Thunderbolt hook ran fine; the display recovered with link-health PASS.
- Driver (7.2.3 `brcmfmac/pcie.c` 2636-2663): enter_D3 sends
  `H2D_HOST_D3_INFORM` through the shared-memory mailbox and waits 2 s
  (`BRCMF_PCIE_MBDATA_TIMEOUT`) for `D2H_DEV_D3_ACK`; a timeout returns -EIO,
  which aborts the system suspend. leave_D3 (2666-2705) already re-probes a
  card that lost its state. brcmfmac acks the device's deep-sleep request
  (`DS_ENTER_REQ`) but has no step that wakes it before sending D3_INFORM.
- Kernel timestamps: attempt 1 took 3.0 s from console suspend to the
  timeout, attempt 2 took 3.9 s. The extra second matches
  `brcmf_pcie_send_mb_data` waiting on a mailbox word still pending: the
  firmware never consumed the first D3_INFORM. No other brcmfmac error all
  boot while NetworkManager kept the radio on, so the normal command path
  works; only the mailbox handshake goes unanswered.
- Trigger: within 0.5 s of logind's "The system will suspend now!",
  NetworkManager ("sleep requested") moves `wlp3s0` from disconnected to
  unmanaged, resets its MAC and has wpa_supplicant deinit it; only then does
  systemd-sleep run. With the interface down, `brcmf_cfg80211_suspend`
  (cfg80211.c 4268) returns at `!check_vif_up`, skipping the scan abort, the
  link-down with its 500 ms settle, and MPC, before the PCI handshake. The
  earlier passing `pm_test=devices` run (TODO.md: "wiphy suspend 504 ms", "no
  brcmfmac errors") bypassed NetworkManager, so that handler ran in full; the
  direct `echo mem > /sys/power/state` deep test also slept for real.
  Hypothesis: firmware left down stops servicing the mailbox. Test 2 checks
  it.
- Community practice: unload brcmfmac around sleep (Arch forum, BCM43602 on
  a Dell XPS: `modprobe -r brcmfmac_wcc brcmfmac` pre, `modprobe brcmfmac`
  post). Omarchy's Mac guidance (discussion #4695): unload the Broadcom chips
  that abort in enter_D3 (BCM4377b), keep BCM4364 bound.

## Record to correct once test 2 fails as expected

The 2026-09-10 17:13 "validated" s2idle cycle (TODO.md around line 275; the
suspend handoff's Validation, item 2) went through `systemctl suspend`, so
through NetworkManager's sleep, and was judged on signs the aborted attempts
share (entry/exit lines, hook unbind/rebind, SATA recovery). Its journal is
gone. `3f07ab5` (2026-09-08) had already found brcmfmac rejections posing as
successes. So a real s2idle sleep has probably never completed here. The
README suspend section ("hardware-verified ... resumed cleanly") and the
0.2.0-alpha release notes ("The clean s2idle resume recorded earlier ...")
need correcting. A real success shows systemd's "System returned from sleep"
and no brcmf errors.

## Options given to the owner

1. Recommended: detach the card around sleep, as the Thunderbolt hook does:
   unbind/rebind brcmfmac devices with ID `14e4:43ba` only, leaving the iMac
   Pro's BCM4364 bound. Cost: Wi-Fi reconnects after wake.
2. Driver fix (wake the firmware before D3_INFORM, or don't fail suspend on
   the timeout): proper and upstreamable, but a second patched module.
3. Newer firmware: none for Linux.
4. This machine only, today: `blacklist brcmfmac` (Wi-Fi unused).

Warned: once Wi-Fi no longer aborts it, the next real suspend is probably the
first real s2idle sleep on this machine and can still hang (power-cycle).

## Next steps (in order)

1. Get the output of `sudo bash notes/wifi-d3-test.sh`.
2. If up PASS, down FAIL, unbound PASS: add the `14e4:43ba` unbind to the
   suspend module's sleep hook (base and Fedora backends; detect, apply and
   remove; tests next to `tests/test_tb_sleep_hook.py`; README, DEPENDENCIES,
   docs). If "down" also passes, the NetworkManager explanation is wrong, but
   an "unbound" PASS still supports the fix.
3. With the owner's go-ahead: one real `systemctl suspend`, wake by key, then
   check `journalctl -b -u systemd-suspend.service` and the kernel log.
4. Correct the records above; release 0.2.1-alpha from `main`.
