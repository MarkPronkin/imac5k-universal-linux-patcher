#!/usr/bin/env python3
"""Run one kernel pm_test stage, preserving masks and restoring debug settings.

This is a diagnostic, not a suspend fix. Even a staged test can hang a broken
driver. No 'none' stage or hibernation operation is accepted.
"""
import argparse
import errno
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import time


POWER = Path('/sys/power')
TARGETS = ('suspend.target', 'hibernate.target', 'hybrid-sleep.target',
           'suspend-then-hibernate.target')


def selected(path):
    value = path.read_text().strip()
    match = re.search(r'\[([^]]+)\]', value)
    return match[1] if match else value


def snapshot():
    return {p.name: p.read_text().strip() for p in sorted(POWER.glob('*'))
            if p.is_file() and p.name in ('state', 'mem_sleep', 'pm_test', 'pm_async',
                                         'pm_debug_messages', 'pm_print_times', 'pm_trace')}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=('freezer', 'devices', 'platform', 'processors', 'core'))
    parser.add_argument('--mode', choices=('deep', 's2idle'), default='deep')
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error('root is required for pm_test and kernel-log capture')
    if args.mode == 's2idle' and args.stage in ('processors', 'core'):
        parser.error('s2idle has no processors/core pm_test stages')
    if selected(POWER / 'pm_test') != 'none':
        parser.error('another pm_test mode is selected; inspect it first')
    if args.stage not in (POWER / 'pm_test').read_text().replace('[', '').replace(']', '').split():
        parser.error('this kernel does not support that test stage')
    if args.mode not in (POWER / 'mem_sleep').read_text().replace('[', '').replace(']', '').split():
        parser.error('this kernel does not support that sleep mode')
    for target in TARGETS:
        result = subprocess.run(['systemctl', 'is-enabled', target], text=True,
                                capture_output=True, timeout=10)
        if result.stdout.strip() != 'masked':
            parser.error(f'{target} must remain masked during diagnosis')
    out = Path(tempfile.mkdtemp(prefix=f'imac-pm-{args.stage}-', dir='/var/tmp'))
    out.chmod(0o755)

    def record(name, data):
        path = out / name
        path.write_text(data)
        path.chmod(0o644)

    def capture(name):
        result = subprocess.run(['dmesg', '--color=never'], text=True,
                                capture_output=True, timeout=10)
        if result.returncode:
            raise RuntimeError(result.stderr.strip())
        record(name, result.stdout)
        return result.stdout

    capture('dmesg-before.txt')
    record('before.json', json.dumps(snapshot(), indent=2) + '\n')
    record('cmdline.txt', Path('/proc/cmdline').read_text())
    saved = []
    outcome = {'stage': args.stage, 'mode': args.mode, 'kernel': os.uname().release,
               'kind': 'diagnostic only; not a real sleep cycle', 'restoration_errors': []}

    def interrupted(signum, _frame):
        raise InterruptedError(errno.EINTR, f'signal {signum}')

    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(sig, interrupted)
    try:
        for path, value in (
            (POWER / 'mem_sleep', args.mode),
            (POWER / 'pm_async', '0'),
            (POWER / 'pm_debug_messages', '1'),
            (POWER / 'pm_print_times', '1'),
            (Path('/sys/module/kernel/parameters/initcall_debug'), 'Y'),
            (Path('/sys/module/printk/parameters/console_suspend'), 'N'),
            (POWER / 'pm_test', args.stage),
        ):
            saved.append((path, selected(path)))
            path.write_text(value + '\n')
            if selected(path) != value:
                raise RuntimeError(f'{path}: requested value did not take effect')
        record('armed.json', json.dumps(snapshot(), indent=2) + '\n')
        print(f'Log directory: {out}', flush=True)
        print(f'Running {args.stage} diagnostic in {args.mode}; all kernel sleep targets remain masked.', flush=True)
        os.sync()
        started = time.clock_gettime(time.CLOCK_BOOTTIME)
        outcome['started_boottime'] = started
        # The printk clock runs behind CLOCK_BOOTTIME, so a kernel-log marker,
        # not a timestamp, separates this test's messages from earlier ones.
        outcome['kmsg_marker'] = f'imac-pm-stage: start {out.name}'
        Path('/dev/kmsg').write_text(outcome['kmsg_marker'] + '\n')
        record('started.json', json.dumps(outcome, indent=2) + '\n')
        os.sync()
        # mem respects pm_test. disk/hibernate and pm_test=none are never used.
        (POWER / 'state').write_text('mem\n')
        outcome['returned'] = True
        outcome['elapsed_seconds'] = time.clock_gettime(time.CLOCK_BOOTTIME) - started
    except (OSError, RuntimeError) as error:
        outcome['error'] = str(error)
        outcome['errno'] = getattr(error, 'errno', None)
    finally:
        for path, value in reversed(saved):
            try:
                path.write_text(value + '\n')
                if selected(path) != value:
                    raise RuntimeError('restored value does not match')
            except (OSError, RuntimeError) as error:
                outcome['restoration_errors'].append(f'{path}: {error}')
        after = capture('dmesg-after.txt').splitlines()
        marker = outcome.get('kmsg_marker')
        starts = [i for i, line in enumerate(after) if marker and line.endswith(marker)]
        lines = after[starts[-1] + 1:] if starts else []
        record('dmesg-test.txt', '\n'.join(lines) + '\n')
        outcome['reached_test_delay'] = any('suspend debug: Waiting for' in line for line in lines)
        outcome['stats'] = {p.name: p.read_text().strip() for p in (POWER / 'suspend_stats').iterdir()}
        record('after.json', json.dumps(snapshot(), indent=2) + '\n')
        record('result.json', json.dumps(outcome, indent=2) + '\n')
        os.sync()
        print(json.dumps(outcome, indent=2), flush=True)
        print(f'Logs: {out}', flush=True)
    return 0 if outcome.get('returned') and outcome['reached_test_delay'] and not outcome['restoration_errors'] else 1


if __name__ == '__main__':
    sys.exit(main())
