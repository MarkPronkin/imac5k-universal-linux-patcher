#!/usr/bin/env python3
"""Capture the overdue second suspend to small, dedicated EFI variables.

    make -C notes/pm-capture
    sudo python3 notes/second-sleep-efi-capture.py selftest
    sudo python3 notes/second-sleep-efi-capture.py run
    # After return/reset, collect BEFORE clearing or another test:
    sudo python3 notes/second-sleep-efi-capture.py collect
    # Clear only this diagnostic's records, after archiving them:
    sudo python3 notes/second-sleep-efi-capture.py clear

Selftest loads the temporary module, verifies an EFI nonvolatile variable by
writing, reading and deleting it, then unloads. Run repeats that check and
uses the existing recorded two-cycle PM test. Add --tb-removed to run with
the whole unused Thunderbolt PCI subtree removed throughout both cycles.
The timer only observes the
second transition; it does not panic, reboot or change a device's power state.
If firmware stops all CPUs, or EFI services hang, it may not save a snapshot.
"""

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import uuid


NOTES = Path(__file__).resolve().parent
KERNEL = '7.2.3-arch1-3'
MODULE = 'imac_pm_capture'
KO = NOTES / 'pm-capture' / (MODULE + '.ko')
PARAMETERS = Path('/sys/module') / MODULE / 'parameters'
GUID = '173f51a7-82a5-4e0a-92c4-38a4b849c5e1'
EFIVARS = Path('/sys/firmware/efi/efivars')
STATE = ('run_id', 'ready', 'storage_ready', 'test_result', 'seen_cycles',
         'timeout_seconds', 'armed', 'writes', 'capture_error', 'last_efi_status', 'test_attrs')


def command(*args):
    return subprocess.check_output(args, text=True, timeout=30).strip()


def save(path, data):
    with path.open('w') as stream:
        stream.write(data if isinstance(data, str) else json.dumps(data, indent=2) + '\n')
        stream.flush()
        os.fsync(stream.fileno())
    path.chmod(0o644)


def output_dir():
    out = Path(tempfile.mkdtemp(prefix='imac-efi-sleep-', dir='/var/tmp'))
    out.chmod(0o755)
    print(f'Logs: {out}', flush=True)
    return out


def module_state():
    return {key: (PARAMETERS / key).read_text().strip() for key in STATE}


def decode_variable(name, raw):
    match = re.fullmatch(r'ImacSleepCapture([0-3])-' + re.escape(GUID), name)
    # Apple adds its VSS data-checksum flag on read-back (UEFITool nvram.h).
    attrs = int.from_bytes(raw[:4], 'little')
    if not match or len(raw) < 5 or attrs not in (7, 0x80000007):
        raise ValueError('unexpected variable name or EFI attributes')
    text = raw[4:].decode('utf-8')
    header = re.match(r'IMAC_PM_CAPTURE v1 run=([0-9a-f]{32}) part=([0-3])\n', text)
    if not header or header[2] != match[1] or len(raw) > 1028:
        raise ValueError('unrecognized or inconsistent diagnostic record')
    return {'run_id': header[1], 'part': int(header[2]), 'attributes': attrs, 'text': text}


def collect(clear=False):
    out = output_dir()
    records = []
    paths = sorted(EFIVARS.glob('ImacSleepCapture[0-3]-' + GUID))
    if clear and PARAMETERS.exists():
        raise RuntimeError('unload the diagnostic before clearing its stored records')
    for path in paths:
        raw = path.read_bytes()
        target = out / path.name
        with target.open('wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        target.chmod(0o644)
        record = {'name': path.name, 'sha256': hashlib.sha256(raw).hexdigest()}
        try:
            record.update(decode_variable(path.name, raw))
            print(record['text'], flush=True)
        except (ValueError, UnicodeError) as error:
            record['error'] = str(error)
        records.append(record)
    save(out / 'records.json', records)
    save(out / 'dmesg.txt', command('dmesg', '--color=never'))
    os.sync()
    if clear:
        if any('error' in record for record in records):
            raise RuntimeError('archived a malformed record; refusing to delete it automatically')
        for path, record in zip(paths, records):
            if hashlib.sha256(path.read_bytes()).hexdigest() != record['sha256']:
                raise RuntimeError('EFI record changed after archival; refusing deletion')
            # efivarfs marks unknown vendor variables immutable by default.
            # Restrict this to the validated, already-archived diagnostic keys.
            command('chattr', '-i', str(path))
            path.unlink()
        save(out / 'cleared.json', [p.name for p in paths])
    print(f'Archived {len(records)} EFI snapshot part(s).', flush=True)


def load_and_test(out, run_id):
    if PARAMETERS.exists():
        raise RuntimeError('the diagnostic module is already loaded; inspect it first')
    if not KO.is_file() or not command('modinfo', '-F', 'vermagic', str(KO)).startswith(KERNEL + ' '):
        raise RuntimeError('build notes/pm-capture against the running kernel first')
    with KO.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    save(out / 'context.json', {
        'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
        'kernel': os.uname().release, 'run_id': run_id, 'module_sha256': digest,
        'cmdline': Path('/proc/cmdline').read_text().strip(),
    })
    command('insmod', str(KO), 'run_id=' + run_id, 'timeout_seconds=20')
    try:
        # A buffered TextIO close can retry a failed sysfs action. Issue it once.
        with (PARAMETERS / 'storage_test').open('wb', buffering=0) as stream:
            if stream.write(b'1\n') != 2:
                raise OSError('short write to the EFI selftest control')
    except OSError as error:
        state = module_state()
        save(out / 'selftest.json', state)
        raise RuntimeError('EFI selftest failed: ' + state['test_result']) from error
    state = module_state()
    save(out / 'selftest.json', state)
    if (state['storage_ready'] != 'Y' or state['seen_cycles'] != '0'
            or state['test_result'] != f'IMAC_PM_CAPTURE selftest run={run_id}'):
        raise RuntimeError('EFI write/read/delete selftest did not validate')
    print('PASS: EFI nonvolatile record written, read back, and deleted; no sleep occurred.', flush=True)


def experiment(run, tb_removed=False):
    if run:
        stats = {p: int((Path('/sys/power/suspend_stats') / p).read_text())
                 for p in ('success', 'fail')}
        if stats != {'success': 0, 'fail': 0}:
            raise RuntimeError('the two-cycle experiment requires a boot with no earlier sleeps')
    out = output_dir()
    run_id = uuid.uuid4().hex
    test_started = False
    test_succeeded = False
    # Do not unload a module left by a different invocation if preflight fails.
    already_loaded = PARAMETERS.exists()
    try:
        load_and_test(out, run_id)
        if run:
            test_command = [sys.executable, str(NOTES / 'recorded-second-sleep.py')]
            if tb_removed:
                test_command.append('--tb-removed')
            save(out / 'test-started.json', {'command': test_command})
            os.sync()
            test_started = True
            subprocess.run(test_command, check=True)
            test_succeeded = True
    finally:
        if not already_loaded and PARAMETERS.exists():
            save(out / 'module-final.json', module_state())
            if not test_started or test_succeeded:
                command('rmmod', MODULE)
                save(out / 'cleanup.json', {'module_unloaded': True})
            else:
                save(out / 'cleanup.json', {'module_unloaded': False,
                    'reason': 'sleep test failed; inspect PM job completion before unloading'})
        save(out / 'dmesg.txt', command('dmesg', '--color=never'))
        os.sync()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('action', choices=('selftest', 'run', 'collect', 'clear'))
    parser.add_argument('--tb-removed', action='store_true', help='run with the full Thunderbolt subtree removed')
    args = parser.parse_args()
    if args.tb_removed and args.action != 'run':
        parser.error('--tb-removed applies only to run')
    if os.geteuid() != 0:
        parser.error('run with sudo or pkexec')
    if Path('/sys/class/dmi/id/product_name').read_text().strip() != 'iMac18,3':
        parser.error('this diagnostic is scoped to the investigated iMac18,3')
    if args.action in ('selftest', 'run') and os.uname().release != KERNEL:
        parser.error('the module requires kernel ' + KERNEL)
    with open('/run/imac-efi-sleep.lock', 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.action in ('collect', 'clear'):
            collect(args.action == 'clear')
        else:
            experiment(args.action == 'run', args.tb_removed)


if __name__ == '__main__':
    try:
        main()
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        print(f'Stopped: {error}', file=sys.stderr)
        sys.exit(1)
