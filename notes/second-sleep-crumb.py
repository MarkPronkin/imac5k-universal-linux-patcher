#!/usr/bin/env python3
"""Find the exact step where the second suspend resets this iMac, via the RTC.

    make -C notes/pm-crumb
    sudo python3 notes/second-sleep-crumb.py run --tb-removed
    # Or, when this boot's real first sleep was already recorded by run:
    sudo python3 notes/second-sleep-crumb.py run --after-first --tb-removed
    # After the reset, first thing, before any other sleep test:
    sudo python3 notes/second-sleep-crumb.py collect
    # Offline re-decode of a saved collection (no root):
    python3 notes/second-sleep-crumb.py decode /var/tmp/imac-crumb-collect-XXXXXXXX

Run loads notes/pm-crumb/imac_pm_crumb.ko, proves on this boot without
sleeping that it writes the RTC and sees ACPI methods and region accesses,
then runs the known reproducer: a real first s2idle sleep (wake it with a key
after about 30 seconds) and a 5-second platform test (leave it alone). The
breadcrumb log of every completed cycle is saved next to the PM test's logs.

--xhci-d0-from 2 is the causality test for the located reset: the first
attempt runs normally, and from the second on the PCH xHCI stays in D0, so
Apple's XHC1._PS3/_PS0 never run. Nothing else changes.

--after-first skips the first sleep. It needs a run of this boot whose real
first sleep completed and saved 1-none-crumb.txt; it replaces a module left
loaded by that run (when no suspend job is pending) and goes straight to the
platform test.

The module overwrites the RTC date/time with the last PM step. Unloading it
writes the system time back. While loaded, real sleep time is not added to
the system clock (this Mac measures s2idle with the RTC). After a reset the clock boots in 2000-2024 until
time sync corrects it; collect reads the kernel's "PM: RTC time" line and the
RTC alarm bytes, then maps them onto the first cycle's log.
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


NOTES = Path(__file__).resolve().parent
KERNEL = '7.2.3-arch1-3'
MODULE = 'imac_pm_crumb'
KO = NOTES / 'pm-crumb' / (MODULE + '.ko')
PARAMETERS = Path('/sys/module') / MODULE / 'parameters'
DEBUGFS = Path('/sys/kernel/debug') / MODULE
STATE = ('armed', 'cycle', 'log_count', 'log_dropped', 'rtc_writes', 'rtc_busy',
         'alarm_skipped', 'bad_objects', 'last_value', 'xhci_d0_from', 'xhci_d0_active')
XHCI = Path('/sys/bus/pci/devices/0000:00:14.0')

DEVHASH = 1021
NPHASE = 16
NCYCLE = 3
PH_MISC = 15
MISC_MARKER = 16
MISC = {1000: 'console_resume_all', 1001: 'acpi_suspend', 1002: 'CPU_OFF', 1003: 'CPU_ON',
        1004: 'other suspend_resume event'}
PHASES = ('none', 'suspend_enter', 'sync_filesystems', 'freeze_processes', 'dpm_prepare',
          'dpm_suspend', 'dpm_suspend_late', 'dpm_suspend_noirq', 'machine_suspend',
          'timekeeping_freeze', 'dpm_resume_noirq', 'dpm_resume_early', 'dpm_resume',
          'dpm_complete', 'thaw_processes', 'misc')
KINDS = ('CB_START', 'CB_END', 'PHASE_BEGIN', 'PHASE_END')
NOTIFIERS = {1: 'PM_HIBERNATION_PREPARE', 2: 'PM_POST_HIBERNATION', 3: 'PM_SUSPEND_PREPARE',
             4: 'PM_POST_SUSPEND', 5: 'PM_RESTORE_PREPARE', 6: 'PM_POST_RESTORE'}
ACPI_KINDS = ('METHOD', 'METHOD_END', 'REGION')
SELFTEST_MARKER = 5
SELFTEST_DEVICE = Path('/sys/bus/pci/devices/0000:00:17.0/firmware_node')
SELFTEST_METHOD = 'PCI0.SATA._STA'
SELFTEST_REGION = 0xE00B8094
RTC_LINE = re.compile(r'PM: RTC time: (\d\d):(\d\d):(\d\d), date: (\d{4})-(\d\d)-(\d\d)')


def hash_string(seed, text, mod):
    """The module's sdbm hash, with C unsigned-int wraparound."""
    for char in text.encode():
        seed = ((seed << 16) + (seed << 6) - seed + char) & 0xFFFFFFFF
    return seed % mod


def device_hash(name):
    return hash_string(7919, name, DEVHASH)


def method_hash(path):
    return hash_string(31, path, 255) + 1


def encode(cycle, kind, phase, code):
    return code % DEVHASH + DEVHASH * (phase + NPHASE * (min(cycle, NCYCLE - 1) + NCYCLE * kind))


def value_to_date(value):
    """(year, month, day, hour) exactly as the module writes them."""
    hour, value = value % 24, value // 24
    day, value = value % 28 + 1, value // 28
    month, year = value % 12 + 1, value // 12
    return 2000 + year, month, day, hour


def date_to_value(year, month, day, hour):
    if not (2000 <= year <= 2024 and 1 <= month <= 12 and 1 <= day <= 28 and 0 <= hour <= 23):
        raise ValueError(f'{year:04}-{month:02}-{day:02} {hour:02}h is not a breadcrumb date')
    return hour + 24 * ((day - 1) + 28 * ((month - 1) + 12 * (year - 2000)))


def decode_value(value):
    code, rest = value % DEVHASH, value // DEVHASH
    phase, rest = rest % NPHASE, rest // NPHASE
    cycle, kind = rest % NCYCLE, rest // NCYCLE
    if kind >= len(KINDS):
        raise ValueError(f'breadcrumb value {value} is out of range')
    result = {'value': value, 'cycle': cycle, 'kind': KINDS[kind], 'phase': PHASES[phase], 'code': code}
    if phase != PH_MISC:
        result['meaning'] = (f'{KINDS[kind]} {PHASES[phase]}' if kind >= 2 else
                             f'{KINDS[kind]} of a device callback in {PHASES[phase]}, device hash {code}')
    elif kind >= 2:
        result['meaning'] = f'{KINDS[kind]} {MISC.get(code, f"misc {code}")}'
    elif code < MISC_MARKER:
        result['meaning'] = f'PM notifier {NOTIFIERS.get(code, code)}'
    else:
        result['meaning'] = f'helper marker {code - MISC_MARKER}'
    # The cycle counter advances when a suspend begins, so a step between two
    # attempts (such as the marker before the second) still carries the first.
    result['cycle_meaning'] = ('before the first suspend began' if cycle == 0 else
                               'first attempt, or before the second began' if cycle == 1 else
                               'second (or later) attempt')
    return result


def bcd(value):
    return (value >> 4) * 10 + (value & 0x0F)


def parse_rtc_debugfs(text):
    registers = {int(m[1], 16): int(m[2], 16) for m in re.finditer(r'^reg([0-9a-f]{2})=([0-9a-f]{2})$', text, re.M)}
    saved = re.search(r'^saved_alarms=([0-9a-f]{2}),([0-9a-f]{2}),([0-9a-f]{2}) valid=1', text, re.M)
    return registers, (tuple(int(x, 16) for x in saved.groups()) if saved else None)


def registers_value(registers):
    """Breadcrumb value currently in the RTC date/time registers (BCD mode)."""
    if not registers[0x0B] & 0x02:
        raise ValueError('RTC is not in 24-hour mode')
    convert = (lambda x: x) if registers[0x0B] & 0x04 else bcd
    return date_to_value(2000 + convert(registers[0x09]), convert(registers[0x08]),
                         convert(registers[0x07]), convert(registers[0x04]))


def parse_rtc_line(text):
    matches = RTC_LINE.findall(text)
    if not matches:
        raise ValueError('no "PM: RTC time" line in this boot\'s kernel log')
    hour, minute, second, year, month, day = map(int, matches[0])
    return {'year': year, 'month': month, 'day': day, 'hour': hour, 'minute': minute, 'second': second}


def parse_log(text):
    entries = []
    for line in text.splitlines():
        if line.startswith('#') or not line.strip():
            continue
        fields = line.split(' | ')
        head = fields[0].split()
        entry = {'ns': int(head[0]), 'cycle': int(head[1]), 'step': int(head[2]), 'phase': int(head[3]),
                 'kind': head[4], 'code': int(head[5]), 'acpi_seq': int(head[6]), 'value32': int(head[7]),
                 'name': fields[1] if len(fields) > 1 else '', 'info': fields[2] if len(fields) > 2 else ''}
        if entry['kind'] == 'REGION' and len(fields) > 3:
            space, write, width, address, value = fields[3].split()
            entry.update(space=int(space), write=int(write), width=int(width),
                         address=int(address, 16), value=int(value, 16))
        entries.append(entry)
    return entries


def step_value(entry):
    """The RTC value the module wrote for a logged PM step, or None for ACPI detail."""
    kind, phase, code = entry['kind'], entry['phase'], entry['code']
    if kind in ('CB_START', 'CB_END', 'PHASE_BEGIN', 'PHASE_END'):
        return encode(entry['cycle'], KINDS.index(kind), phase, code)
    if kind in ('NOTIFY', 'MARKER'):
        return encode(entry['cycle'], 0, PH_MISC, code)
    return None


def describe(entry):
    if entry['kind'] == 'REGION':
        spaces = {0: 'SystemMemory', 1: 'SystemIO', 2: 'PCI_Config', 3: 'EmbeddedControl', 4: 'SMBus', 5: 'CMOS'}
        rw = 'write' if entry['write'] else 'read'
        value = f' value=0x{entry["value"]:x}' if entry['write'] else ''
        return (f'REGION {rw} {spaces.get(entry["space"], entry["space"])} 0x{entry["address"]:x} '
                f'width={entry["width"]}{value} field={entry["name"] or "?"} region={entry["info"]}')
    if entry['kind'] in ('METHOD', 'METHOD_END'):
        return f'{entry["kind"]} {entry["name"]}'
    return f'{entry["kind"]} {entry["name"]} {entry["info"]}'.strip()


# ACPICA sets up a PCI_Config region on its first use only, evaluating _BBN/_SEG
# (and whatever they call). A later attempt repeats the same method without them.
REGION_SETUP = ('._BBN', '._SEG')


def without_region_setup(events):
    kept, depth = [], 0
    for event in events:
        setup = event['kind'] in ('METHOD', 'METHOD_END') and event['name'].endswith(REGION_SETUP)
        if event['kind'] == 'METHOD' and (setup or depth):
            depth += 1
            continue
        if event['kind'] == 'METHOD_END' and depth:
            depth -= 1
            continue
        kept.append(event)
    return kept


def last_method_hash(events):
    names = [e['name'] for e in events if e['kind'] == 'METHOD']
    return method_hash(names[-1]) if names else 0


def locate(decoded, alarms, entries, device_names=(), methods=()):
    """Map a post-reset breadcrumb onto the first cycle's (same-sequence) log."""
    report = {'decoded': decoded}
    heartbeat, hash_seen, acpi_count = alarms if alarms else (None, None, None)
    if alarms:
        report['alive_after_cycle_start_s'] = ('>= 127.5' if heartbeat == 255 else
                                               f'{heartbeat / 2:.1f}..{(heartbeat + 1) / 2:.1f}')
        report['method_hash'] = hash_seen
        report['acpi_events_after_step'] = '>= 255' if acpi_count == 255 else acpi_count
        report['method_candidates'] = sorted({path for h, path in methods if h == hash_seen}) if hash_seen else []
    if decoded['kind'].startswith('CB') and decoded['phase'] != 'misc':
        report['device_candidates'] = sorted({n for n in device_names if device_hash(n) == decoded['code']})
    # The same step in the reference (first) cycle: the second attempt repeats it.
    wanted = {encode(1, KINDS.index(decoded['kind']), PHASES.index(decoded['phase']), decoded['code'])}
    matches = [i for i, e in enumerate(entries) if e['cycle'] == 1 and step_value(e) in wanted]
    report['reference_matches'] = []
    for index in matches:
        after, context = [], []
        for e in entries[index + 1:]:
            if step_value(e) is not None:
                break
            after.append(e)
        for e in entries[max(0, index - 3):index + 1]:
            context.append(describe(e))
        item = {'step': entries[index]['step'], 'entry': describe(entries[index]), 'before': context[:-1],
                'acpi_events_following': len(after)}
        if alarms and acpi_count and acpi_count != 255:
            # Prefer the numbering whose last method matches the recorded hash.
            for label, events in (('as in the reference cycle', after),
                                  ('without first-use region setup (_BBN)', without_region_setup(after))):
                if acpi_count <= len(events) and last_method_hash(events[:acpi_count]) == hash_seen:
                    item['numbering'] = label
                    break
            else:
                item['numbering'] = 'no numbering matches the recorded method hash; reference cycle shown'
                events = after
            if acpi_count <= len(events):
                item['last_acpi_event'] = describe(events[acpi_count - 1])
                item['next_acpi_event'] = describe(events[acpi_count]) if acpi_count < len(events) else None
                item['acpi_events_up_to_it'] = [describe(e) for e in events[:acpi_count]]
        elif alarms and acpi_count:
            item['acpi_events_up_to_it'] = [describe(e) for e in after[:300]]
        report['reference_matches'].append(item)
    return report


def command(*args, timeout=60):
    return subprocess.check_output(args, text=True, timeout=timeout)


def save(path, data):
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


def module_state():
    return {key: (PARAMETERS / key).read_text().strip() for key in STATE}


def write_once(path, text):
    # A buffered close can retry a failed sysfs write; issue it exactly once.
    with path.open('wb', buffering=0) as stream:
        data = text.encode()
        if stream.write(data) != len(data):
            raise OSError(f'short write to {path}')


def require_module_file():
    if not KO.is_file() or not command('modinfo', '-F', 'vermagic', str(KO)).startswith(KERNEL + ' '):
        raise RuntimeError('build notes/pm-crumb against the running kernel first (make -C notes/pm-crumb)')
    with KO.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def selftest(out):
    """No sleep: prove RTC writes, the date encoding, and both ACPI probes on this boot."""
    write_once(PARAMETERS / 'marker', f'{SELFTEST_MARKER}\n')
    expected = encode(int(module_state()['cycle']), 0, PH_MISC, MISC_MARKER + SELFTEST_MARKER)
    state = module_state()
    registers, _saved = parse_rtc_debugfs((DEBUGFS / 'rtc').read_text())
    problems = []
    if int(state['last_value']) != expected:
        problems.append(f'module wrote value {state["last_value"]}, expected {expected}')
    if registers_value(registers) != expected:
        problems.append(f'RTC date/time registers hold {registers_value(registers)}, expected {expected}')
    if bcd(registers[0x02]) > 1:
        problems.append('RTC minutes were not reset by the marker')
    (SELFTEST_DEVICE / 'status').read_text()   # evaluates \_SB.PCI0.SATA._STA, which reads SBIT
    entries = parse_log((DEBUGFS / 'log').read_text())
    marker = max(i for i, e in enumerate(entries) if e['kind'] == 'MARKER' and e['value32'] == SELFTEST_MARKER)
    acpi = [e for e in entries[marker + 1:] if e['kind'] in ACPI_KINDS]
    if not any(e['kind'] == 'METHOD' and e['name'] == SELFTEST_METHOD for e in acpi):
        problems.append(f'no {SELFTEST_METHOD} method event after reading its status')
    if not any(e['kind'] == 'REGION' and e['address'] == SELFTEST_REGION and e['space'] == 0 for e in acpi):
        problems.append('no SystemMemory region read at 0xe00b8094 (SATA SBIT)')
    registers, _saved = parse_rtc_debugfs((DEBUGFS / 'rtc').read_text())
    methods = [e for e in acpi if e['kind'] == 'METHOD']
    if registers[0x0B] & 0x20:
        problems.append('RTC alarm interrupt became enabled; alarm bytes cannot be used')
    elif not methods or registers[0x03] != method_hash(methods[-1]['name']):
        problems.append(f'alarm byte 0x03 = {registers[0x03]} does not name the last method begun')
    elif registers[0x05] != min(len(acpi), 255):
        problems.append(f'alarm byte 0x05 = {registers[0x05]}, expected {min(len(acpi), 255)} ACPI events')
    result = {'expected_value': expected, 'state': module_state(), 'registers': registers,
              'acpi_events': [describe(e) for e in acpi], 'problems': problems}
    save(out / 'selftest.json', result)
    if problems:
        raise RuntimeError('breadcrumb selftest failed: ' + '; '.join(problems))
    print('PASS: RTC breadcrumb written and read back; ACPI method and region probes fire; no sleep occurred.',
          flush=True)


def boot_id():
    return Path('/proc/sys/kernel/random/boot_id').read_text().strip()


def reference_run(boot=None, root=Path('/var/tmp')):
    """Newest PM-test run holding a completed first-cycle breadcrumb log (of this boot, if given)."""
    for log in sorted(root.glob('imac-second-sleep-*/1-none-crumb.txt'),
                      key=lambda p: p.stat().st_mtime, reverse=True):
        context = json.loads((log.parent / 'context.json').read_text())
        result = json.loads((log.parent / '1-none-result.json').read_text())
        if boot is None or context.get('boot_id') == boot:
            if result['after']['success'] == result['before']['success'] + 1:
                return log.parent
    return None


def replace_stale_module(out):
    """Unload a module left armed by an unfinished run, once no PM job can be pending."""
    state = module_state()
    service = command('systemctl', 'show', 'systemd-suspend.service', '-p', 'ActiveState').strip()
    if service not in ('ActiveState=inactive', 'ActiveState=failed'):
        raise RuntimeError('a suspend job is still active; not touching the loaded module')
    if re.search(r'\[([^]]+)\]', Path('/sys/power/pm_test').read_text())[1] != 'none':
        raise RuntimeError('pm_test is still selected from an earlier run; reboot or inspect first')
    save(out / 'previous-module.json', state)
    save(out / 'previous-crumb-log.txt', (DEBUGFS / 'log').read_text())
    command('rmmod', MODULE)
    print('Replaced the breadcrumb module left loaded by the earlier run (RTC restored).', flush=True)


def run(tb_removed, after_first=False, xhci_d0_from=0):
    stats = {p: int((Path('/sys/power/suspend_stats') / p).read_text()) for p in ('success', 'fail')}
    reference = None
    if after_first:
        reference = reference_run(boot_id())
        if stats['success'] < 1 or reference is None:
            raise RuntimeError('--after-first needs a recorded, completed real first sleep in this boot')
    elif stats != {'success': 0, 'fail': 0}:
        raise RuntimeError('the two-cycle experiment requires a boot with no earlier sleeps')
    elif PARAMETERS.exists():
        raise RuntimeError('the breadcrumb module is already loaded; inspect it first')
    digest = require_module_file()
    if xhci_d0_from and ((XHCI / 'power/runtime_status').read_text().strip() != 'active'
                         or (XHCI / 'power_state').read_text().strip() != 'D0'):
        raise RuntimeError('--xhci-d0-from needs 00:14.0 active in D0 (power/control=on)')
    rtc_proc = Path('/proc/driver/rtc').read_text()
    if not re.search(r'^24hr\s*: yes$', rtc_proc, re.M) or not re.search(r'^alarm_IRQ\s*: no$', rtc_proc, re.M):
        raise RuntimeError('the RTC must be in 24-hour mode with no alarm interrupt armed')
    if 'alarmtimer_fired' in Path('/proc/timer_list').read_text():
        raise RuntimeError('an alarm timer is pending; its suspend path would need the RTC time')
    out = output_dir('imac-crumb-')
    save(out / 'context.json', {'boot_id': boot_id(), 'kernel': os.uname().release, 'module_sha256': digest,
                               'cmdline': Path('/proc/cmdline').read_text().strip(), 'rtc': rtc_proc,
                               'suspend_stats': stats, 'reference_run': str(reference) if reference else None,
                               'xhci_d0_from': xhci_d0_from})
    if after_first and PARAMETERS.exists():
        replace_stale_module(out)
    test_started = test_succeeded = False
    command('insmod', str(KO), 'arm=1', f'cycle_base={stats["success"] + stats["fail"]}',
            f'xhci_d0_from={xhci_d0_from}')
    try:
        if module_state()['armed'] != 'Y':
            raise RuntimeError('module loaded but did not arm')
        selftest(out)
        test_command = [sys.executable, str(NOTES / 'second-sleep-pm-test.py'), 'platform',
                        '--after-first' if after_first else '--prime',
                        '--mode', 's2idle', '--delay', '5', '--wifi-unbound', '--serial', '--crumb']
        if tb_removed:
            test_command.append('--tb-removed')
        save(out / 'test-started.json', {'command': test_command})
        os.sync()
        test_started = True
        subprocess.run(test_command, check=True)
        test_succeeded = True
        if xhci_d0_from and module_state()['xhci_d0_active'] == 'Y':
            print('SURVIVED: the attempt that resets this iMac completed with the xHCI kept in D0 '
                  '(XHC1._PS3/_PS0 not run).', flush=True)
    finally:
        if PARAMETERS.exists():
            save(out / 'module-final.json', module_state())
            save(out / 'crumb-log-final.txt', (DEBUGFS / 'log').read_text())
            if not test_started or test_succeeded:
                command('rmmod', MODULE)
                save(out / 'cleanup.json', {'module_unloaded': True, 'rtc': 'restored from system time'})
            else:
                save(out / 'cleanup.json', {'module_unloaded': False, 'reason':
                     'sleep test failed; confirm no PM job is pending, then rmmod imac_pm_crumb'})
        save(out / 'dmesg.txt', command('dmesg', '--color=never'))
        os.sync()


def device_names():
    names = set()
    for root, dirs, files in os.walk('/sys/devices'):
        if 'uevent' in files:
            names.add(os.path.basename(root))
        dirs[:] = [d for d in dirs if not os.path.islink(os.path.join(root, d))]
    return sorted(names)


def latest_run():
    run_dir = reference_run()
    if run_dir is None:
        raise RuntimeError('no completed first-cycle breadcrumb log under /var/tmp/imac-second-sleep-*')
    return run_dir


def report_text(report, rtc, run_dir):
    lines = [f'Reference run: {run_dir}',
             f'Kernel read the RTC at boot as {rtc["year"]:04}-{rtc["month"]:02}-{rtc["day"]:02} '
             f'{rtc["hour"]:02}:{rtc["minute"]:02}:{rtc["second"]:02}',
             f'Last PM step: {report["decoded"]["meaning"]} ({report["decoded"]["cycle_meaning"]})',
             f'Time from that step to the next boot reading the clock: {rtc["minute"] * 60 + rtc["second"]} s']
    if 'alive_after_cycle_start_s' in report:
        lines += [f'Heartbeat: still running {report["alive_after_cycle_start_s"]} s after the attempt began',
                  f'ACPI events after the step: {report["acpi_events_after_step"]}; '
                  f'last method hash {report["method_hash"]} = {report["method_candidates"] or "none"}']
    if report.get('device_candidates') is not None:
        lines.append(f'Devices with that hash: {report["device_candidates"]}')
    for match in report['reference_matches']:
        lines.append(f'In the first cycle this was step {match["step"]}: {match["entry"]}')
        lines += ['    before: ' + b for b in match['before']]
        if 'last_acpi_event' in match:
            lines.append(f'    Numbering: {match["numbering"]}')
            lines.append(f'    ACPI event #{report["acpi_events_after_step"]} (started, the last): {match["last_acpi_event"]}')
            lines.append(f'    Next event (never started): {match["next_acpi_event"]}')
        for event in match.get('acpi_events_up_to_it', []):
            lines.append('      ' + event)
    return '\n'.join(lines) + '\n'


def analyse(rtc, alarms, run_dir, names):
    decoded = decode_value(date_to_value(rtc['year'], rtc['month'], rtc['day'], rtc['hour']))
    reference = run_dir / '1-none-crumb.txt'
    entries = parse_log(reference.read_text()) if reference.exists() else []
    methods = [tuple(line.split(' ', 1)) for line in (run_dir / 'crumb-methods.txt').read_text().splitlines()]
    methods = [(int(h), path) for h, path in methods]
    report = locate(decoded, alarms, entries, names, methods)
    return report, report_text(report, rtc, run_dir)


def collect():
    if PARAMETERS.exists():
        raise RuntimeError('the breadcrumb module is loaded; collect is for the boot after a reset')
    require_module_file()
    out = output_dir('imac-crumb-collect-')
    kernel_log = command('journalctl', '-k', '-b', '0', '--no-pager', '-o', 'short-monotonic')
    rtc = parse_rtc_line(kernel_log)
    command('insmod', str(KO), 'arm=0')
    try:
        rtc_text = (DEBUGFS / 'rtc').read_text()
    finally:
        command('rmmod', MODULE)
    _registers, alarms = parse_rtc_debugfs(rtc_text)
    run_dir = latest_run()
    names = device_names()
    save(out / 'rtc-line.json', rtc)
    save(out / 'rtc-debugfs.txt', rtc_text)
    save(out / 'device-names.txt', '\n'.join(names) + '\n')
    save(out / 'run-dir.txt', str(run_dir) + '\n')
    save(out / 'kernel-log.txt', kernel_log)
    report, text = analyse(rtc, alarms, run_dir, names)
    save(out / 'report.json', report)
    save(out / 'report.txt', text)
    os.sync()
    print(text, flush=True)
    print('The RTC still holds breadcrumb data; once time is synchronized run: hwclock --systohc', flush=True)


def decode_saved(path):
    rtc = json.loads((path / 'rtc-line.json').read_text())
    _registers, alarms = parse_rtc_debugfs((path / 'rtc-debugfs.txt').read_text())
    run_dir = Path((path / 'run-dir.txt').read_text().strip())
    names = (path / 'device-names.txt').read_text().split()
    print(analyse(rtc, alarms, run_dir, names)[1], end='')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('action', choices=('run', 'collect', 'decode'))
    parser.add_argument('path', nargs='?', type=Path, help='collection directory for decode')
    parser.add_argument('--tb-removed', action='store_true', help='run with the whole Thunderbolt subtree removed')
    parser.add_argument('--xhci-d0-from', type=int, default=0, metavar='N',
                        help='keep 00:14.0 out of D3 from suspend attempt N of this boot on')
    parser.add_argument('--after-first', action='store_true',
                        help='this boot already recorded its real first sleep; run only the platform test')
    args = parser.parse_args()
    if args.action == 'decode':
        if not args.path:
            parser.error('decode needs a collection directory')
        decode_saved(args.path)
        return
    if (args.tb_removed or args.after_first or args.xhci_d0_from) and args.action != 'run':
        parser.error('--tb-removed, --after-first and --xhci-d0-from apply only to run')
    if args.xhci_d0_from < 0:
        parser.error('--xhci-d0-from must be a positive attempt number')
    if os.geteuid() != 0:
        parser.error('run with sudo or pkexec')
    if Path('/sys/class/dmi/id/product_name').read_text().strip() != 'iMac18,3':
        parser.error('this diagnostic is scoped to the investigated iMac18,3')
    if os.uname().release != KERNEL:
        parser.error('the module requires kernel ' + KERNEL)
    with open('/run/imac-crumb.lock', 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.action == 'run':
            run(args.tb_removed, args.after_first, args.xhci_d0_from)
        else:
            collect()


if __name__ == '__main__':
    try:
        main()
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        print(f'Stopped: {error}', file=sys.stderr)
        sys.exit(1)
