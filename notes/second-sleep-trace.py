#!/usr/bin/env python3
"""Persistent PM tracing for this iMac18,3 and its current Omarchy kernel.

    sudo python3 notes/second-sleep-trace.py arm
    # Restart normally to reserve the buffer, then:
    sudo python3 notes/second-sleep-trace.py mark
    # Restart normally again, then:
    sudo python3 notes/second-sleep-trace.py capture
    sudo python3 notes/second-sleep-trace.py start
    sudo python3 notes/second-sleep-pm-test.py platform --prime --mode s2idle \
        --delay 5 --wifi-unbound --serial --persistent-trace
    # After the return or reset, capture BEFORE starting tracing again:
    sudo python3 notes/second-sleep-trace.py capture
    # When the investigation is done:
    sudo python3 notes/second-sleep-trace.py disarm
    # Restart to release the reservation.

This never suspends or restarts the machine itself. Normal-reboot retention
is a prerequisite, not a guarantee of retention through the unexplained reset.
It uses only a dedicated trace instance. No boot events are specified: even
with traceoff, enabling boot events clears the previous boot's trace in 7.2.3.
"""

import argparse
from collections import Counter
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import tempfile


KERNEL = '7.2.3-arch1-3'
ADDRESS = 0x800000000
SIZE = 16 * 1024 * 1024
PARAMS = ('memmap=16M$0x800000000',
          'trace_instance=imac_sleep^traceoff@0x800000000:16M')
DROPIN = Path('/etc/limine-entry-tool.d/zz-imac-sleep-trace.conf')
# Written as data, never sourced as shell code ($ must reach the kernel literally).
CONFIG = ('# Temporary recorder: notes/second-sleep-trace.py disarm removes it.\n'
          'KERNEL_CMDLINE[default]+=" ' + ' '.join(PARAMS) + '"\n')
UKI = Path('/boot/EFI/Linux/omarchy_linux.efi')
TRACE = Path('/sys/kernel/tracing/instances/imac_sleep')
MARKER = Path('/var/tmp/imac-sleep-trace-marker.json')
VERIFIED = Path('/var/tmp/imac-sleep-trace-verified.json')
EVENTS = ('device_pm_callback_start', 'device_pm_callback_end', 'suspend_resume')


def command(*args):
    return subprocess.check_output(args, text=True, timeout=30).strip()


def write(path, data):
    path.write_text(data + '\n')


def record(path, data):
    with path.open('w') as stream:
        stream.write(data if isinstance(data, str) else json.dumps(data, indent=2) + '\n')
        stream.flush()
        os.fsync(stream.fileno())
    path.chmod(0o644)


def output_dir(prefix):
    out = Path(tempfile.mkdtemp(prefix=prefix, dir='/var/tmp'))
    out.chmod(0o755)
    print(f'Logs: {out}', flush=True)
    return out


def context():
    return {'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
            'kernel': os.uname().release, 'params': list(PARAMS),
            'cmdline': Path('/proc/cmdline').read_text().strip()}


def region_is(iomem, kind):
    """Require one containing top-level region, with no overlapping subresources."""
    containing = False
    for line in iomem.splitlines():
        match = re.fullmatch(r'(\s*)([0-9a-fA-F]+)-([0-9a-fA-F]+) : (.+)', line)
        if not match:
            continue
        indent, low, high, name = match.groups()
        low, high = int(low, 16), int(high, 16)
        if low > ADDRESS + SIZE - 1 or high < ADDRESS:
            continue
        if indent or name != kind or not (low <= ADDRESS and ADDRESS + SIZE - 1 <= high):
            return False
        containing = True
    return containing


def check_cmdline_change(before, after, arming):
    old, new, extra = Counter(before.split()), Counter(after.split()), Counter(PARAMS)
    if arming:
        if any(p.startswith(('memmap=', 'reserve_mem=', 'trace_instance=')) for p in old):
            raise RuntimeError('an existing memory reservation or boot trace needs review first')
        expected = old + extra
    else:
        if not extra <= old:
            raise RuntimeError('the recorder parameters are missing from the configured command line')
        expected = old - extra
    if new != expected:
        raise RuntimeError('command line changed beyond the two recorder parameters; refusing it')


def section(name):
    # An explicit output avoids objcopy's default of overwriting the input file.
    return command('objcopy', '-O', 'binary', '--only-section=' + name,
                   str(UKI), '/dev/stdout').rstrip('\0')


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def configure(arming):
    if not UKI.is_file() or section('.uname') != KERNEL:
        raise RuntimeError('the installed Omarchy UKI is not the expected running kernel')
    if not Path('/boot/limine.conf').is_file():
        raise RuntimeError('expected /boot/limine.conf is missing')
    if command('findmnt', '-no', 'FSTYPE', '/boot') != 'vfat':
        raise RuntimeError('/boot must be the mounted EFI partition')
    if shutil.disk_usage('/boot').free < UKI.stat().st_size * 2:
        raise RuntimeError('insufficient free EFI partition space for rebuilding')
    if arming:
        if DROPIN.exists():
            raise RuntimeError(f'{DROPIN} already exists; inspect it before making changes')
        if not region_is(Path('/proc/iomem').read_text(), 'System RAM'):
            raise RuntimeError('the chosen 16 MiB region is not unencumbered System RAM')
        config = Path('/usr/lib/modules') / KERNEL / 'build/.config'
        settings = config.read_text().splitlines()
        if 'CONFIG_FTRACE=y' not in settings or 'CONFIG_RESET_ATTACK_MITIGATION=y' in settings:
            raise RuntimeError('kernel tracing/memory-retention configuration is unsuitable')
    elif not DROPIN.exists() or DROPIN.read_text() != CONFIG:
        raise RuntimeError('refusing to remove a missing or modified recorder drop-in')

    before = command('limine-entry-tool', '--get-cmdline', 'linux')
    out = output_dir('imac-sleep-trace-setup-')
    record(out / 'context.json', {**context(), 'action': 'arm' if arming else 'disarm'})
    record(out / 'iomem-before.txt', Path('/proc/iomem').read_text())
    record(out / 'cmdline-before.txt', before)
    # Preserve the current boot files for immediate rollback if rebuilding fails.
    # The loader's random seeds are not part of a kernel rebuild.
    backup = out / 'boot-backup'
    backup.mkdir(mode=0o700)
    paths = [p for p in Path('/boot').rglob('*')
             if p.is_file() and p.relative_to('/boot').parts[0] != 'loader']
    if shutil.disk_usage(out).free < sum(p.stat().st_size for p in paths) + 256 * 1024 * 1024:
        raise RuntimeError('insufficient room for a boot backup')
    for path in paths:
        dest = backup / path.relative_to('/boot')
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest)
    record(out / 'backup-sha256.json', {str(p): digest(p) for p in paths})
    os.sync()
    changed = False
    build_started = False
    try:
        if arming:
            with DROPIN.open('x') as stream:
                stream.write(CONFIG)
            DROPIN.chmod(0o644)
        else:
            DROPIN.unlink()
        changed = True
        after = command('limine-entry-tool', '--get-cmdline', 'linux')
        check_cmdline_change(before, after, arming)
        record(out / 'cmdline-after.txt', after)
        build_started = True
        print('Rebuilding the existing linux boot image; backup is saved.', flush=True)
        with (out / 'rebuild.log').open('w') as stream:
            subprocess.run(['limine-mkinitcpio', 'linux'], stdout=stream,
                           stderr=subprocess.STDOUT, check=True, timeout=600)
        # Check the actual embedded data, not just the source drop-in.
        embedded = section('.cmdline')
        if Counter(embedded.split()) != Counter(after.split()) or section('.uname') != KERNEL:
            raise RuntimeError('rebuilt UKI does not contain the verified command line/kernel')
        record(out / 'embedded-cmdline.txt', embedded)
        boot_config = Path('/boot/limine.conf').read_text()
        if arming and not all(p in boot_config for p in PARAMS):
            raise RuntimeError('the boot menu is missing the recorder command line')
        record(out / 'limine.conf.after', boot_config)
        record(out / 'result.json', {'success': True, 'action': 'arm' if arming else 'disarm'})
        os.sync()
    except BaseException as exc:
        if changed:
            if arming and DROPIN.exists() and DROPIN.read_text() == CONFIG:
                DROPIN.unlink()
            elif not arming and not DROPIN.exists():
                write(DROPIN, CONFIG.rstrip('\n'))
            if build_started:
                for path in paths:
                    shutil.copy2(backup / path.relative_to('/boot'), path)
            os.sync()
        record(out / 'result.json', {'success': False, 'error': str(exc),
                                    'boot_backup_restored': changed and build_started})
        raise
    print('Recorder armed. Restart normally, then run mark.' if arming else
          'Recorder removed from the boot configuration. Restart to release its RAM.', flush=True)


def live_trace():
    if not set(PARAMS) <= set(Path('/proc/cmdline').read_text().split()):
        raise RuntimeError('recorder boot parameters are not active; restart after arming')
    if not region_is(Path('/proc/iomem').read_text(), 'Reserved'):
        raise RuntimeError('the trace region is not reserved as expected')
    if not (TRACE / 'last_boot_info').is_file():
        raise RuntimeError('the persistent trace instance was not created by the kernel')


def marker_survived(marker, current, trace):
    return (marker.get('kernel') == current['kernel']
            and marker.get('params') == current['params']
            and bool(marker.get('boot_id')) and marker['boot_id'] != current['boot_id']
            and bool(marker.get('marker')) and marker['marker'] in trace)


def capture():
    live_trace()
    out = output_dir('imac-sleep-trace-capture-')
    current = context()
    record(out / 'context.json', current)
    # Reading trace is non-consuming. Save before enabling anything, which clears it.
    for name in ('last_boot_info', 'tracing_on', 'trace_clock', 'current_tracer'):
        record(out / (name + '.txt'), (TRACE / name).read_text())
    trace = (TRACE / 'trace').read_text()
    record(out / 'trace.txt', trace)
    record(out / 'cpu-stats.json', {p.parent.name: p.read_text()
                                   for p in (TRACE / 'per_cpu').glob('cpu*/stats')})
    record(out / 'dmesg.txt', command('dmesg', '--color=never'))
    if MARKER.exists():
        marker = json.loads(MARKER.read_text())
        survived = marker_survived(marker, current, trace)
        record(out / 'marker-check.json', {'survived': survived, 'expected': marker})
        if survived:
            record(VERIFIED, {**current, 'marker_boot_id': marker['boot_id'], 'capture': str(out)})
            print('PASS: the marker survived a reboot on this kernel and memory reservation.', flush=True)
        else:
            print('This capture does not prove that the marker survived a reboot.', flush=True)
    return out


def begin(mark_only):
    live_trace()
    if (TRACE / 'tracing_on').read_text().strip() != '0':
        raise RuntimeError('the dedicated recorder is already running; stop/capture it first')
    out = capture()
    if not mark_only:
        verified = json.loads(VERIFIED.read_text()) if VERIFIED.exists() else {}
        if verified.get('kernel') != KERNEL or verified.get('params') != list(PARAMS):
            raise RuntimeError('first verify a marker across a normal reboot (mark, reboot, capture)')
    write(TRACE / 'events/enable', '0')
    write(TRACE / 'trace_clock', 'global')
    write(TRACE / 'trace', '')
    if not mark_only:
        for event in EVENTS:
            write(TRACE / 'events/power' / event / 'enable', '1')
    marker = f'imac-sleep-trace:{context()["boot_id"]}:{out.name}'
    write(TRACE / 'tracing_on', '1')
    try:
        write(TRACE / 'trace_marker', marker)
    finally:
        if mark_only:
            write(TRACE / 'tracing_on', '0')
    if marker not in (TRACE / 'trace').read_text():
        write(TRACE / 'tracing_on', '0')
        raise RuntimeError('the marker was not recorded')
    if mark_only:
        record(MARKER, {**context(), 'marker': marker})
        print('Marker saved; tracing is paused. Restart normally, then run capture.', flush=True)
    else:
        record(out / 'started.json', {**context(), 'marker': marker, 'events': EVENTS})
        print('Recording PM callbacks. Run the prepared sleep test, then capture after return/reset.', flush=True)
    os.sync()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('action', choices=('arm', 'disarm', 'mark', 'capture', 'start', 'stop'))
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error('run with sudo or pkexec')
    if Path('/sys/class/dmi/id/product_name').read_text().strip() != 'iMac18,3' or os.uname().release != KERNEL:
        parser.error('this diagnostic requires the investigated iMac18,3 and kernel ' + KERNEL)
    with open('/run/imac-sleep-trace.lock', 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.action in ('arm', 'disarm'):
            # Finish the boot transaction even if the requesting terminal closes.
            for sig in (signal.SIGHUP, signal.SIGINT, signal.SIGTERM):
                signal.signal(sig, lambda *_: print('Finishing the boot configuration transaction.', flush=True))
            configure(args.action == 'arm')
        elif args.action in ('mark', 'start'):
            begin(args.action == 'mark')
        else:
            if args.action == 'stop':
                live_trace()
                write(TRACE / 'tracing_on', '0')
            capture()


if __name__ == '__main__':
    main()
