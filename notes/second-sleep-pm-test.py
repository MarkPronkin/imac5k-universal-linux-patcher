#!/usr/bin/env python3
"""Locate the second-suspend failure after a real first sleep, on this iMac.

    sudo python3 notes/second-sleep-pm-test.py devices --prime

Wake the first, real sleep with a key after about 30 seconds. The next attempt
uses pm_test=devices and returns automatically after a 70-second test delay.
It can still hang/reset if the failing path precedes actual sleep. Both cycles
use systemctl suspend, including logind and the installed sleep hooks.

If it returns, a later invocation can test another stage in the same boot:
    sudo python3 notes/second-sleep-pm-test.py platform --after-first

--prime requires untouched suspend counters. --after-first asserts that a real
first sleep already completed; simulated pm_test successes alone are not enough.
No boot settings or installed hooks are changed. Temporary settings are restored
on completion. If the machine resets, /run settings disappear at reboot and the
last started.json under /var/tmp/imac-second-sleep-* identifies the pending cycle.
With --persistent-trace, first start the validated recorder using
notes/second-sleep-trace.py start. The helper checks it before each cycle,
marks each attempt, and saves the trace after every completed cycle.
With --tb-removed, the whole Alpine Ridge chip (upstream bridge 05:00.0 and
every bridge, NHI and USB controller below it) is removed from the PCI bus
before the first cycle and rescanned from root port 00:1c.4 at the end.
Nothing may be plugged into the Thunderbolt ports. If the rescan does not
bring the chip back, a reboot does.
With --crumb (run through notes/second-sleep-crumb.py), the armed RTC
breadcrumb module must be loaded. Each attempt gets a marker, and the
breadcrumb log is saved after every completed cycle.
"""

import argparse
import fcntl
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
SLEEP_CONF = Path('/run/systemd/sleep.conf.d/zzzz-imac-second-sleep-test.conf')
SERVICE = 'systemd-suspend.service'
PROPERTIES = ('ActiveState', 'Result', 'ExecMainStatus', 'ExecMainStartTimestampMonotonic')
WIFI = Path('/sys/bus/pci/devices/0000:03:00.0')
WIFI_DRIVER = Path('/sys/bus/pci/drivers/brcmfmac')
PHY_DEBUG = Path('/sys/kernel/debug/ieee80211')
TRACE = Path('/sys/kernel/tracing/instances/imac_sleep')
TRACE_EVENTS = ('device_pm_callback_start', 'device_pm_callback_end', 'suspend_resume')
TB_ROOT_PORT = Path('/sys/bus/pci/devices/0000:00:1c.4')
TB_UPSTREAM = '0000:05:00.0'
TB_NHI = '0000:07:00.0'
CRUMB = Path('/sys/module/imac_pm_crumb/parameters')
CRUMB_DEBUG = Path('/sys/kernel/debug/imac_pm_crumb')
PCI_ADDRESS = re.compile(r'^[0-9a-f]{4}:[0-9a-f]{2}:[0-9a-f]{2}\.[0-7]$')
USB_DEVICE = re.compile(r'^\d+-\d+(\.\d+)*$')


def selected(path):
    value = path.read_text().strip()
    match = re.search(r'\[([^]]+)\]', value)
    return match[1] if match else value


def command(*args):
    return subprocess.run(args, text=True, capture_output=True, check=True, timeout=30).stdout


def service_state():
    return dict(line.split('=', 1) for line in command(
        'systemctl', 'show', SERVICE, *('-p' + p for p in PROPERTIES)
    ).splitlines() if '=' in line)


def completed(previous, current, before=None, after=None):
    """An inactive service before its new job starts is not a completed sleep."""
    start = current.get('ExecMainStartTimestampMonotonic', '')
    new_invocation = start not in ('', '0', previous.get('ExecMainStartTimestampMonotonic'))
    # systemd can unload the finished oneshot unit before this process is
    # thawed/polled. Its execution timestamps then read as zero again. Kernel
    # counters persist, and cannot advance just from asynchronously queuing a job.
    new_kernel_attempt = before is not None and after is not None and before != after
    return ((new_invocation or new_kernel_attempt)
            and current.get('ActiveState') in ('inactive', 'failed'))


def stats():
    return {name: int((POWER / 'suspend_stats' / name).read_text())
            for name in ('success', 'fail')}


def wifi_ready(device=WIFI, debug=PHY_DEBUG):
    # brcmfmac's bind returns before firmware loading and brcmf_bus_started.
    # The reset debugfs file is created only after INIT_WORK(bus_reset), later
    # than netdev registration. A net interface alone is not sufficient.
    return any((debug / phy.name / 'reset').exists()
               for phy in (device / 'ieee80211').glob('phy*'))


def wait_wifi_ready():
    if not (WIFI_DRIVER / WIFI.name).exists():
        return
    deadline = time.monotonic() + 30
    while not wifi_ready():
        if time.monotonic() >= deadline:
            raise RuntimeError('Wi-Fi initialization was not confirmed; refusing another detach/suspend')
        time.sleep(0.25)


def tb_subtree(port=TB_ROOT_PORT):
    """PCI functions below the root port, as {address: vendor:device}."""
    found = {}
    for root, dirs, _files in os.walk(port.resolve()):
        for name in dirs:
            if PCI_ADDRESS.match(name):
                device = Path(root) / name
                found[name] = ':'.join((device / f).read_text().strip() for f in ('vendor', 'device'))
    return dict(sorted(found.items()))


def tb_in_use(port=TB_ROOT_PORT):
    """Anything attached through the Thunderbolt ports that removal would yank."""
    users = []
    for root, dirs, _files in os.walk(port.resolve()):
        for name in dirs:
            path = Path(root) / name
            # Thunderbolt's own switches are also named N-M; USB devices carry idVendor.
            if USB_DEVICE.match(name) and (path / 'idVendor').exists():
                product = path / 'product'
                users.append(f'USB {name} ({product.read_text().strip() if product.exists() else "unknown"})')
            elif name in ('net', 'block'):
                users.extend(f'{name} {entry.name}' for entry in path.iterdir())
    return users


def tb_restored(port=TB_ROOT_PORT):
    driver = port / TB_UPSTREAM / 'driver'
    nhi = next((Path(root) / TB_NHI for root, dirs, _ in os.walk(port.resolve()) if TB_NHI in dirs), None)
    return driver.exists() and nhi is not None and (nhi / 'driver').resolve().name == 'thunderbolt'


def require_recording(trace=TRACE):
    """Do not risk another test with a paused or incomplete PM recorder."""
    if (trace / 'last_boot_info').read_text().strip() != '# Current':
        raise RuntimeError('capture the previous boot trace, then start the recorder first')
    if (trace / 'tracing_on').read_text().strip() != '1':
        raise RuntimeError('the persistent recorder is paused; refusing an unrecorded sleep test')
    if any((trace / 'events/power' / event / 'enable').read_text().strip() != '1'
           for event in TRACE_EVENTS):
        raise RuntimeError('the persistent recorder is missing required PM events')


def require_crumb(parameters=CRUMB, debug=CRUMB_DEBUG):
    """Never start an attempt the breadcrumb module would not record."""
    if not (parameters / 'armed').exists() or (parameters / 'armed').read_text().strip() != 'Y':
        raise RuntimeError('load notes/pm-crumb/imac_pm_crumb.ko with arm=1 first')
    if not (debug / 'log').exists():
        raise RuntimeError('the breadcrumb log is not available in debugfs')


def write_once(path, text):
    with path.open('wb', buffering=0) as stream:
        data = text.encode()
        if stream.write(data) != len(data):
            raise OSError(f'short write to {path}')


def s2idle_seconds(log):
    """Time the kernel spent in the s2idle loop, from printk's local_clock.

    That clock keeps counting through s2idle. CLOCK_BOOTTIME only learns the
    sleep from the RTC on this Mac, which the breadcrumb module makes unusable.
    """
    enter = re.findall(r'^\[\s*([0-9.]+)\] PM: suspend-to-idle$', log, re.M)
    leave = re.findall(r'^\[\s*([0-9.]+)\] PM: resume from suspend-to-idle$', log, re.M)
    if not enter or not leave or float(leave[-1]) < float(enter[0]):
        return 0.0
    return float(leave[-1]) - float(enter[0])


def assess(stage, mode, before, after, log, elapsed, sleep_seconds, delay):
    if after['fail'] != before['fail'] or after['success'] != before['success'] + 1:
        return 'FAIL: expected exactly one successful kernel suspend and no failures'
    if f'PM: suspend entry ({mode})' not in log or 'PM: suspend exit' not in log:
        return 'INCONCLUSIVE: missing entry/exit evidence for the requested sleep mode'
    if stage == 'none':
        if mode == 's2idle':
            sleep_seconds = max(sleep_seconds, s2idle_seconds(log))
        if 'suspend debug: Waiting for' in log or sleep_seconds < 5:
            return 'INCONCLUSIVE: a real first sleep lasting at least five seconds was not verified'
    elif f'suspend debug: Waiting for {delay} second(s).' not in log:
        return 'INCONCLUSIVE: the kernel did not reach the requested pm_test delay'
    elif elapsed < delay:
        return 'INCONCLUSIVE: the attempt returned before the requested test interval elapsed'
    return 'PASS'


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('stage', choices=('freezer', 'devices', 'platform', 'processors', 'core'))
    first = parser.add_mutually_exclusive_group(required=True)
    first.add_argument('--prime', action='store_true', help='take one real first sleep on a fresh boot')
    first.add_argument('--after-first', action='store_true', help='a real first sleep has already completed')
    parser.add_argument('--mode', choices=('deep', 's2idle'), help='default: current /sys/power/mem_sleep selection')
    parser.add_argument('--delay', type=int, help='default: 70 seconds; processors/core use 5 seconds')
    parser.add_argument('--wifi-unbound', action='store_true',
                        help='keep the unused BCM43602 detached throughout both cycles; rebind on exit')
    parser.add_argument('--serial', action='store_true',
                        help='temporarily set pm_async=0 to run device callbacks sequentially')
    parser.add_argument('--persistent-trace', action='store_true',
                        help='require the running imac_sleep recorder; save a trace after each completed cycle')
    parser.add_argument('--tb-removed', action='store_true',
                        help='remove the whole Thunderbolt chip from the PCI bus for both cycles; rescan on exit')
    parser.add_argument('--crumb', action='store_true',
                        help='require the armed RTC breadcrumb module; mark and save its log for each cycle')
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error('run with sudo; kernel settings and kernel-log capture require root')
    if Path('/sys/class/dmi/id/product_name').read_text().strip() != 'iMac18,3':
        parser.error('this diagnostic is scoped to the investigated iMac18,3')
    if selected(POWER / 'pm_test') != 'none' or selected(POWER / 'pm_trace') != '0':
        parser.error('pm_test must be none and pm_trace must be 0 before starting')
    mode = args.mode or selected(POWER / 'mem_sleep')
    if mode == 's2idle' and args.stage in ('processors', 'core'):
        parser.error('s2idle supports only freezer/devices/platform tests')
    delay = args.delay if args.delay is not None else (5 if args.stage in ('processors', 'core') else 70)
    if not 1 <= delay <= 120 or (args.stage in ('processors', 'core') and delay > 5):
        parser.error('delay must be 1..120 seconds; processors/core are limited to 5 seconds')
    for path, item in ((POWER / 'pm_test', args.stage), (POWER / 'mem_sleep', mode)):
        if item not in path.read_text().replace('[', '').replace(']', '').split():
            parser.error(f'{path} does not support {item}')
    initial = stats()
    if args.prime and initial != {'success': 0, 'fail': 0}:
        parser.error('--prime requires a fresh boot with no earlier suspend attempts')
    if args.after_first and initial['success'] == 0:
        parser.error('--after-first requires an earlier successful real sleep')
    if args.persistent_trace:
        require_recording()
    if args.crumb:
        require_crumb()
    service = service_state()
    if not all(key in service for key in PROPERTIES):
        parser.error('systemd does not expose the service properties needed to wait for completion')
    if service.get('ActiveState') not in ('inactive', 'failed'):
        parser.error('a suspend service is already running')
    for name in ('imac-tb-sleep-hook', 'imac-wifi-sleep-hook'):
        if not os.access(Path('/usr/lib/systemd/system-sleep') / name, os.X_OK):
            parser.error(f'the existing {name} must be installed and executable')
    wait_wifi_ready()
    if args.wifi_unbound:
        if (WIFI / 'vendor').read_text().strip() != '0x14e4' or (WIFI / 'device').read_text().strip() != '0x43ba':
            parser.error('--wifi-unbound requires the BCM43602 at 0000:03:00.0')
        wifi_interfaces = {p.name for p in (WIFI / 'net').glob('*')}
        routes = json.loads(command('ip', '-j', 'route', 'show', 'default'))
        routes += json.loads(command('ip', '-j', '-6', 'route', 'show', 'default'))
        if any(route.get('dev') in wifi_interfaces for route in routes):
            parser.error('the default network route uses Wi-Fi; refusing to detach it')
        if any((WIFI / 'net' / name / 'operstate').read_text().strip() == 'up' for name in wifi_interfaces):
            parser.error('Wi-Fi is connected; --wifi-unbound is only for the unused card')
    if args.tb_removed:
        upstream = TB_ROOT_PORT / TB_UPSTREAM
        if not upstream.exists() or (upstream / 'vendor').read_text().strip() != '0x8086' \
                or (upstream / 'device').read_text().strip() != '0x1578':
            parser.error('--tb-removed requires the Alpine Ridge upstream bridge 05:00.0 below 00:1c.4')
        if not tb_restored():
            parser.error('--tb-removed requires Thunderbolt to be present and bound before the run')
        users = tb_in_use()
        if users:
            parser.error('unplug everything from the Thunderbolt ports first: ' + ', '.join(users))

    lock = open('/run/imac-second-sleep-pm-test.lock', 'w')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    out = Path(tempfile.mkdtemp(prefix='imac-second-sleep-', dir='/var/tmp'))
    out.chmod(0o755)

    def record(name, data):
        path = out / name
        with path.open('w') as stream:
            stream.write(data if isinstance(data, str) else json.dumps(data, indent=2) + '\n')
            stream.flush()
            os.fsync(stream.fileno())
        path.chmod(0o644)

    record('context.json', {'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                           'kernel': os.uname().release, 'cmdline': Path('/proc/cmdline').read_text().strip(),
                           'args': vars(args), 'mode': mode, 'delay': delay, 'initial_stats': initial})
    record('dmesg-before.txt', command('dmesg', '--color=never'))
    if args.persistent_trace:
        record('trace-context.json', {name: (TRACE / name).read_text()
                                     for name in ('last_boot_info', 'trace_clock', 'current_tracer')})
    if args.crumb:
        record('crumb-methods.txt', (CRUMB_DEBUG / 'methods').read_text())
        record('crumb-rtc-before.txt', (CRUMB_DEBUG / 'rtc').read_text())
    tables = out / 'acpi-tables'
    tables.mkdir(mode=0o755)
    for table in sorted(Path('/sys/firmware/acpi/tables').iterdir()):
        if table.is_file() and (table.name.startswith('SSDT') or table.name in ('DSDT', 'FACP', 'ECDT')):
            dest = tables / table.name
            dest.write_bytes(table.read_bytes())
            dest.chmod(0o644)

    saved = []
    pending = False
    conf_created = False
    wifi_detached = False
    tb_removed = False
    interrupted = False
    results = []

    def on_signal(signum, _frame):
        nonlocal interrupted
        interrupted = True
        print(f'Signal {signum}: stopping after the current suspend job finishes, then restoring settings.', flush=True)

    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, on_signal)

    def change(path, value):
        saved.append((path, selected(path)))
        record('saved-settings.json', {str(p): v for p, v in saved})
        path.write_text(value + '\n')
        if selected(path) != value:
            raise RuntimeError(f'{path}: requested setting {value} did not take effect')

    print(f'Logs: {out}', flush=True)
    try:
        # Systemd writes mem_sleep before every cycle; its temporary override is
        # needed even if sysfs already selects the desired mode.
        saved.append((POWER / 'mem_sleep', selected(POWER / 'mem_sleep')))
        SLEEP_CONF.parent.mkdir(parents=True, exist_ok=True)
        with SLEEP_CONF.open('x') as stream:
            conf_created = True
            stream.write(f'[Sleep]\nSuspendState=\nSuspendState=mem\nMemorySleepMode=\nMemorySleepMode={mode}\n')
        for path, value in (
            (POWER / 'pm_print_times', '1'), (POWER / 'pm_debug_messages', '1'),
            (Path('/sys/module/kernel/parameters/initcall_debug'), 'Y'),
            (Path('/sys/module/suspend/parameters/pm_test_delay'), str(delay)),
        ):
            change(path, value)
        if args.serial:
            change(POWER / 'pm_async', '0')
        # console_suspend remains unchanged. pm_async changes only with --serial.
        saved.append((POWER / 'pm_test', 'none'))
        record('saved-settings.json', {str(p): v for p, v in saved})
        if args.wifi_unbound and (WIFI_DRIVER / WIFI.name).exists():
            record('wifi.json', {'device': WIFI.name, 'originally_bound': True,
                                'action': 'keep detached across the entire diagnostic'})
            wifi_detached = True
            (WIFI_DRIVER / 'unbind').write_text(WIFI.name + '\n')
            if (WIFI_DRIVER / WIFI.name).exists():
                raise RuntimeError('Wi-Fi detach did not take effect')
            print('Wi-Fi detached for the entire run; the installed Wi-Fi hook has no bound card to cycle.', flush=True)
        if args.tb_removed:
            record('thunderbolt.json', {'root_port': TB_ROOT_PORT.name, 'removed': tb_subtree(),
                                        'action': 'remove from the PCI bus for the entire diagnostic'})
            tb_removed = True
            (TB_ROOT_PORT / TB_UPSTREAM / 'remove').write_text('1\n')
            if tb_subtree():
                raise RuntimeError('Thunderbolt removal did not take effect')
            print('Thunderbolt removed from the PCI bus for the entire run; the Thunderbolt hook has nothing to unbind.',
                  flush=True)

        for index, stage in enumerate((['none'] if args.prime else []) + [args.stage], 1):
            if interrupted:
                raise RuntimeError('interrupted before the next cycle')
            wait_wifi_ready()
            if tb_removed and tb_subtree():
                raise RuntimeError('Thunderbolt reappeared on the PCI bus; this run no longer tests its absence')
            (POWER / 'pm_test').write_text(stage + '\n')
            if selected(POWER / 'pm_test') != stage:
                raise RuntimeError('pm_test selection did not take effect')
            if stage == 'none':
                print(f'FIRST REAL SLEEP ({mode}): wake with a key after about 30 seconds.', flush=True)
            else:
                print(f'TEST {stage} ({mode}): returns automatically after a {delay}s test delay. Leave it alone.', flush=True)
            marker = f'imac-second-sleep: {out.name} {index}-{stage}'
            Path('/dev/kmsg').write_text(marker + '\n')
            if args.persistent_trace:
                require_recording()
                (TRACE / 'trace_marker').write_text(marker + '\n')
            if args.crumb:
                require_crumb()
                write_once(CRUMB / 'marker', f'{index}\n')
            before = stats()
            previous = service_state()
            record('started.json', {'cycle': index, 'stage': stage, 'mode': mode, 'before': before,
                                    'time': time.strftime('%Y-%m-%d %H:%M:%S%z'), 'marker': marker})
            command('journalctl', '--sync')
            os.sync()
            boot_start = time.clock_gettime(time.CLOCK_BOOTTIME)
            mono_start = time.monotonic()
            # systemctl suspend is asynchronous. Never reset pm_test merely
            # because that command returns or the old service is still inactive.
            pending = True
            command('systemctl', 'suspend')
            while True:
                current = service_state()
                if completed(previous, current, before, stats()):
                    break
                if time.monotonic() - mono_start > 600:
                    raise RuntimeError('suspend service did not confirm completion within ten minutes')
                time.sleep(1)
            pending = False
            elapsed = time.clock_gettime(time.CLOCK_BOOTTIME) - boot_start
            sleep_seconds = max(0, elapsed - (time.monotonic() - mono_start))
            log = command('dmesg', '--color=never')
            lines = log.splitlines()
            starts = [i for i, line in enumerate(lines) if line.endswith(marker)]
            cycle_log = '\n'.join(lines[starts[-1] + 1:]) + '\n' if starts else ''
            after = stats()
            verdict = assess(stage, mode, before, after, cycle_log, elapsed, sleep_seconds, delay)
            if mode == 's2idle':
                sleep_seconds = max(sleep_seconds, s2idle_seconds(cycle_log))
            if current.get('Result') != 'success' or current.get('ExecMainStatus') != '0':
                verdict = 'FAIL: systemd-suspend.service did not complete successfully'
            result = {'stage': stage, 'verdict': verdict, 'before': before, 'after': after,
                      'elapsed_seconds': elapsed, 'time_in_real_sleep_seconds': sleep_seconds,
                      'service': current}
            record(f'{index}-{stage}-dmesg.txt', cycle_log)
            record(f'{index}-{stage}-result.json', result)
            if args.persistent_trace:
                record(f'{index}-{stage}-trace.txt', (TRACE / 'trace').read_text())
                record(f'{index}-{stage}-trace-stats.json', {
                    p.parent.name: p.read_text() for p in (TRACE / 'per_cpu').glob('cpu*/stats')})
            if args.crumb:
                record(f'{index}-{stage}-crumb.txt', (CRUMB_DEBUG / 'log').read_text())
            record(f'{index}-{stage}-service.txt', command('journalctl', '-b', '-u', SERVICE, '--no-pager', '-o', 'short-precise'))
            results.append(result)
            print(f'{stage}: {verdict}; elapsed {elapsed:.1f}s, real sleep {sleep_seconds:.1f}s', flush=True)
            if verdict != 'PASS':
                raise RuntimeError('stopping: the cycle did not validate; inspect the saved logs')
    finally:
        restoration_errors = []
        if pending:
            # A queued pm_test must never become a real sleep during cleanup.
            restoration_errors.append('Sleep job completion is unknown: temporary settings left in place. '
                                      'Reboot clears them; do not set pm_test=none while a job may be pending.')
        else:
            for path, value in reversed(saved):
                try:
                    path.write_text(value + '\n')
                    if selected(path) != value:
                        raise RuntimeError('restored value does not match')
                except (OSError, RuntimeError) as error:
                    restoration_errors.append(f'{path}: {error}')
            if conf_created:
                try:
                    SLEEP_CONF.unlink()
                except OSError as error:
                    restoration_errors.append(f'{SLEEP_CONF}: {error}')
            if wifi_detached and not (WIFI_DRIVER / WIFI.name).exists():
                try:
                    (WIFI_DRIVER / 'bind').write_text(WIFI.name + '\n')
                    wait_wifi_ready()
                except (OSError, RuntimeError) as error:
                    restoration_errors.append(f'Wi-Fi rebind: {error}')
            if tb_removed and not tb_restored():
                try:
                    (TB_ROOT_PORT / 'rescan').write_text('1\n')
                    deadline = time.monotonic() + 20
                    while not tb_restored():
                        if time.monotonic() >= deadline:
                            raise RuntimeError('chip not back and bound after a rescan; a reboot restores it')
                        time.sleep(0.5)
                    record('thunderbolt-restored.json', tb_subtree())
                except (OSError, RuntimeError) as error:
                    restoration_errors.append(f'Thunderbolt rescan: {error}')
        record('summary.json', {'results': results, 'restoration_errors': restoration_errors})
        os.sync()
        for error in restoration_errors:
            print(error, file=sys.stderr)
        print(f'Logs: {out}', flush=True)
    return 1 if restoration_errors or interrupted else 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        print(f'Stopped: {error}', file=sys.stderr)
        sys.exit(1)
