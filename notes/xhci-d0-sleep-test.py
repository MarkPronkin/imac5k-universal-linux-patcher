#!/usr/bin/env python3
"""Validate the XHC1 fix (native D3hot, no Apple _PS3/_PS0) with several real sleeps.

    make -C modules/imac5k-xhci-d0
    sudo python3 notes/xhci-d0-sleep-test.py            # 3 sleeps
    sudo python3 notes/xhci-d0-sleep-test.py --cycles 5
    sudo python3 notes/xhci-d0-sleep-test.py --mode deep   # S3; needs acpi_sleep=nonvs
    # After `imac-patcher --apply suspend` and a reboot:
    sudo python3 notes/xhci-d0-sleep-test.py --require-boot-loaded --cycles 4 --long-seconds 600

Loads modules/imac5k-xhci-d0 (replacing an older build that held the
controller in D0 and so lost USB wake), then runs real s2idle sleeps back to
back through systemctl suspend with the installed sleep hooks. Wake each one
with the USB keyboard after about 30 seconds and answer whether it did. Every
cycle must sleep at least five seconds, wake from the keyboard, return with no
suspend failure or xHCI error, and bring back the same USB devices. Before the
fix the second sleep of every boot reset the machine.

The sleep mode (s2idle by default, or deep S3) is selected for the run through
a /run sleep.conf override. Deep S3 resets on wake here without acpi_sleep=nonvs,
so --mode deep requires it. In deep mode a missing keyboard wake or a Thunderbolt
controller that does not come back is reported as a warning, not a failure, so
the repeat-sleep result is still collected (wake with the power button). The module stays loaded after
the run; a reboot unloads it. Logs: /var/tmp/imac-xhci-d0-*.
"""

import argparse
import fcntl
import importlib.util
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import tempfile
import time

NOTES = Path(__file__).resolve().parent
ROOT = NOTES.parent
KO = ROOT / 'modules/imac5k-xhci-d0/imac5k_xhci_d0.ko'
PARAMETERS = Path('/sys/module/imac5k_xhci_d0/parameters')
ACTIVE = PARAMETERS / 'acpi_pm_skipped'
XHCI_ERRORS = ('xHCI host not responding', 'HC died', 'Host halt failed', 'xHCI host controller not responding',
               'Controller not ready', 'Host Controller Error', 'xhci_hcd 0000:00:14.0: WARN')
GPE_COUNTERS = ('gpe6D', 'ff_pwr_btn', 'sci')
TB_ERRORS = ('inaccessible', 'timeout resetting host router', 'thunderbolt 0000:07:00.0: failed')
TIMEKEEPING = re.compile(r'Timekeeping suspended for ([0-9.]+) seconds')
XHCI = Path('/sys/bus/pci/devices/0000:00:14.0')
SLEEP_CONF = Path('/run/systemd/sleep.conf.d/zzzz-imac-xhci-d0-test.conf')

_spec = importlib.util.spec_from_file_location('pm_test', NOTES / 'second-sleep-pm-test.py')
PM = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(PM)


def usb_devices(root=XHCI):
    """vendor:product of every USB device below the controller."""
    found = []
    for dirpath, _dirs, files in os.walk(root.resolve()):
        if 'idVendor' in files and 'idProduct' in files:
            path = Path(dirpath)
            found.append(f'{(path / "idVendor").read_text().strip()}:{(path / "idProduct").read_text().strip()}')
    return sorted(found)


def gpe_counts(root=Path('/sys/firmware/acpi/interrupts')):
    return {name: (root / name).read_text().split()[0] for name in GPE_COUNTERS if (root / name).exists()}


def timekeeping_seconds(log):
    return max((float(m) for m in TIMEKEEPING.findall(log)), default=0.0)


def cycle_warnings(mode, keyboard_woke, tb_back, log):
    """Deep-S3 shortcomings that do not by themselves mean repeated sleep is broken."""
    warnings = []
    if mode == 'deep' and not keyboard_woke:
        warnings.append('the USB keyboard did not wake it from S3')
    if not tb_back:
        warnings.append('Thunderbolt did not come back bound')
    tb_lines = [line for line in log.splitlines() if any(text in line for text in TB_ERRORS)]
    if tb_lines:
        warnings.append('Thunderbolt/PCI errors: ' + ' | '.join(tb_lines[:3]))
    return warnings


def long_sleep_problem(results, long_seconds):
    if long_seconds and not any(r['slept_seconds'] >= long_seconds for r in results):
        return f'no sleep lasted {long_seconds} s'
    return None


def check_cycle(before, after, log, sleep_seconds, devices_before, devices_after, service, keyboard_woke=True,
                mode='s2idle'):
    problems = []
    if mode == 's2idle' and not keyboard_woke:
        problems.append('the USB keyboard did not wake it')
    if mode == 'deep' and 'Waking up from system sleep state S3' not in log \
            and 'ACPI: PM: Low-level resume complete' not in log:
        problems.append('no evidence in the kernel log of an actual S3 resume')
    errors = [line for line in log.splitlines() if any(text in line for text in XHCI_ERRORS)]
    if errors:
        problems.append('xHCI errors after resume: ' + ' | '.join(errors[:3]))
    if after['success'] != before['success'] + 1 or after['fail'] != before['fail']:
        problems.append(f'suspend counters {before} -> {after}: not exactly one successful suspend')
    if f'PM: suspend entry ({mode})' not in log or 'PM: suspend exit' not in log:
        problems.append(f'no {mode} entry/exit in the kernel log')
    if sleep_seconds < 5:
        problems.append(f'slept only {sleep_seconds:.1f} s; wake it after about 30 s')
    if 'Some devices failed to suspend' in log or 'Failed to put system to sleep' in log:
        problems.append('a device refused to suspend')
    if devices_after != devices_before:
        problems.append(f'USB devices changed: {devices_before} -> {devices_after}')
    if service.get('Result') != 'success':
        problems.append('systemd-suspend.service did not succeed')
    return problems


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--cycles', type=int, default=3)
    parser.add_argument('--mode', choices=('s2idle', 'deep'), default='s2idle')
    parser.add_argument('--require-boot-loaded', action='store_true',
                        help='fail unless the installed module was already loaded at boot')
    parser.add_argument('--long-seconds', type=int, default=0, metavar='N',
                        help='the last sleep must last at least N seconds')
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error('run with sudo')
    if Path('/sys/class/dmi/id/product_name').read_text().strip() != 'iMac18,3':
        parser.error('validated only on the iMac18,3')
    if not 2 <= args.cycles <= 10:
        parser.error('--cycles must be 2..10')
    if PM.selected(Path('/sys/power/pm_test')) != 'none':
        parser.error('pm_test must be none')
    if args.mode not in Path('/sys/power/mem_sleep').read_text().replace('[', '').replace(']', '').split():
        parser.error(f'the kernel does not offer {args.mode}')
    if args.mode == 'deep' and 'acpi_sleep=nonvs' not in Path('/proc/cmdline').read_text().split():
        parser.error('deep S3 resets on wake here without acpi_sleep=nonvs (notes/s3-nonvs-test.sh arm, reboot)')
    for name in ('imac-tb-sleep-hook', 'imac-wifi-sleep-hook'):
        if not os.access(Path('/usr/lib/systemd/system-sleep') / name, os.X_OK):
            parser.error(f'the installed {name} is required')
    lock = open('/run/imac-xhci-d0-test.lock', 'w')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)

    out = Path(tempfile.mkdtemp(prefix='imac-xhci-d0-', dir='/var/tmp'))
    out.chmod(0o755)

    def record(name, data):
        path = out / name
        with path.open('w') as stream:
            stream.write(data if isinstance(data, str) else json.dumps(data, indent=2) + '\n')
            stream.flush()
            os.fsync(stream.fileno())
        path.chmod(0o644)

    print(f'Logs: {out}', flush=True)
    loaded_at_start = ACTIVE.exists()
    if args.require_boot_loaded and not loaded_at_start:
        raise RuntimeError('imac5k_xhci_d0 was not loaded at boot (check /etc/modules-load.d and dkms status)')
    if PARAMETERS.exists() and not ACTIVE.exists():
        # The first build held 00:14.0 in D0, which stopped USB wake.
        subprocess.run(['rmmod', 'imac5k_xhci_d0'], check=True)
        print('Unloaded the older D0-holding build of imac5k_xhci_d0.', flush=True)
    if not PARAMETERS.exists():
        # Prefer the DKMS-installed module; fall back to a development build.
        if subprocess.run(['modprobe', 'imac5k_xhci_d0']).returncode != 0:
            subprocess.run(['insmod', str(KO)], check=True)
    if ACTIVE.read_text().strip() != 'Y':
        raise RuntimeError('imac5k_xhci_d0 is loaded but not holding the controller')
    record('context.json', {'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                           'kernel': os.uname().release, 'cmdline': Path('/proc/cmdline').read_text().strip(),
                           'stats': PM.stats(), 'xhci_power_state': (XHCI / 'power_state').read_text().strip(),
                           'mode': args.mode, 'loaded_at_start': loaded_at_start,
                           'module_path': subprocess.run(['modinfo', '-n', 'imac5k_xhci_d0'], text=True,
                                                         capture_output=True).stdout.strip()})
    debug = Path('/sys/power/pm_debug_messages')
    debug_before = debug.read_text().strip()
    debug.write_text('1\n')   # prints the suspend-to-idle lines that time the sleep
    SLEEP_CONF.parent.mkdir(parents=True, exist_ok=True)
    SLEEP_CONF.write_text(f'[Sleep]\nSuspendState=\nSuspendState=mem\nMemorySleepMode=\nMemorySleepMode={args.mode}\n')
    results, pending = [], False
    try:
        for cycle in range(1, args.cycles + 1):
            PM.wait_wifi_ready()
            devices_before = usb_devices()
            marker = f'imac-xhci-d0-test: {out.name} sleep {cycle}'
            Path('/dev/kmsg').write_text(marker + '\n')
            before, previous, gpes_before = PM.stats(), PM.service_state(), gpe_counts()
            boot_start, mono_start = time.clock_gettime(time.CLOCK_BOOTTIME), time.monotonic()
            wait = (f'at least {args.long_seconds} seconds ({args.long_seconds / 60:.0f} min)'
                    if args.long_seconds and cycle == args.cycles else 'about 30 seconds')
            print(f'SLEEP {cycle}/{args.cycles} ({args.mode}): wake it with the USB keyboard after {wait}'
                  + (' (if that does nothing within ~10 s, use the power button).' if args.mode == 'deep' else '.'),
                  flush=True)
            PM.command('journalctl', '--sync')
            os.sync()
            pending = True
            PM.command('systemctl', 'suspend')
            start = time.monotonic()
            while not PM.completed(previous, current := PM.service_state(), before, PM.stats()):
                if time.monotonic() - start > 900:
                    raise RuntimeError('suspend did not complete within 15 minutes')
                time.sleep(1)
            pending = False
            deadline = time.monotonic() + 20   # let USB and Thunderbolt come back after resume
            while ((devices_after := usb_devices()) != devices_before or not PM.tb_restored()) \
                    and time.monotonic() < deadline:
                time.sleep(1)
            tb_back = PM.tb_restored()
            lines = PM.command('dmesg', '--color=never').splitlines()
            starts = [i for i, line in enumerate(lines) if line.endswith(marker)]
            log = '\n'.join(lines[starts[-1] + 1:]) + '\n' if starts else ''
            boot_sleep = (time.clock_gettime(time.CLOCK_BOOTTIME) - boot_start) - (time.monotonic() - mono_start)
            sleep_seconds = max(PM.s2idle_seconds(log), timekeeping_seconds(log), boot_sleep)
            answer = input(f'Sleep {cycle}: did the USB keyboard wake it (not the power button)? [y/n] ')
            keyboard_woke = answer.strip().lower().startswith('y')
            problems = check_cycle(before, PM.stats(), log, sleep_seconds, devices_before, devices_after, current,
                                   keyboard_woke, args.mode)
            warnings = cycle_warnings(args.mode, keyboard_woke, tb_back, log)
            result = {'cycle': cycle, 'mode': args.mode, 'slept_seconds': round(sleep_seconds, 1),
                      'problems': problems, 'warnings': warnings,
                      'keyboard_woke': keyboard_woke, 'gpe_before': gpes_before, 'gpe_after': gpe_counts(),
                      'wake': [line for line in log.splitlines() if 'wakeup' in line.lower()][:3]}
            record(f'{cycle}-dmesg.txt', log)
            record(f'{cycle}-result.json', result)
            results.append(result)
            print(f'sleep {cycle}: {"PASS" if not problems else "FAIL: " + "; ".join(problems)} '
                  f'(asleep {sleep_seconds:.1f} s)' + ''.join(f'\n  WARNING: {w}' for w in warnings), flush=True)
            if problems:
                break
            time.sleep(10)
    finally:
        if not pending:
            SLEEP_CONF.unlink(missing_ok=True)
            debug.write_text(debug_before + '\n')
        record('summary.json', {'results': results, 'override_left_in_place': pending})
        os.sync()
    long_problem = long_sleep_problem(results, args.long_seconds) if len(results) == args.cycles else None
    if long_problem:
        print(f'FAIL: {long_problem}', flush=True)
    passed = len(results) == args.cycles and not any(r['problems'] for r in results) and not long_problem
    print(f'{"ALL PASS" if passed else "NOT VALIDATED"}: {len(results)} of {args.cycles} sleeps checked. Logs: {out}',
          flush=True)
    return 0 if passed else 1


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        print(f'Stopped: {error}', file=sys.stderr)
        sys.exit(1)
