"""RTC breadcrumbs must decode exactly what the kernel module writes."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('second_sleep_crumb', ROOT / 'notes/second-sleep-crumb.py')
CRUMB = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CRUMB)
PM_SPEC = importlib.util.spec_from_file_location('second_sleep_pm_test', ROOT / 'notes/second-sleep-pm-test.py')
PM = importlib.util.module_from_spec(PM_SPEC)
PM_SPEC.loader.exec_module(PM)


def bcd(value):
    return (value // 10) << 4 | value % 10


def registers_for(value):
    """RTC registers after the module's write_time_locked() in BCD, 24-hour mode."""
    year, month, day, hour = CRUMB.value_to_date(value)
    return {0x00: 0x07, 0x02: 0x00, 0x04: bcd(hour), 0x07: bcd(day), 0x08: bcd(month),
            0x09: bcd(year - 2000), 0x0B: 0x02}


class CrumbTest(unittest.TestCase):
    def test_hashes_match_the_c_module(self):
        # Values printed by the module's hash_string() compiled with gcc.
        self.assertEqual(CRUMB.device_hash('0000:00:14.0'), 610)
        self.assertEqual(CRUMB.device_hash('0000:01:00.0'), 112)
        self.assertEqual(CRUMB.device_hash('PNP0C09:00'), 428)
        self.assertEqual(CRUMB.method_hash('PCI0.XHC1._PS3'), 3)
        self.assertEqual(CRUMB.method_hash('PCI0.SATA._STA'), 195)

    def test_every_step_is_a_valid_past_date_and_decodes_back(self):
        for kind in range(4):
            for phase in range(CRUMB.NPHASE):
                for cycle in range(CRUMB.NCYCLE):
                    for code in (0, 17, 610, CRUMB.DEVHASH - 1):
                        value = CRUMB.encode(cycle, kind, phase, code)
                        year, month, day, hour = CRUMB.value_to_date(value)
                        self.assertTrue(2000 <= year <= 2024 and 1 <= day <= 28, (year, day))
                        self.assertEqual(CRUMB.date_to_value(year, month, day, hour), value)
                        decoded = CRUMB.decode_value(value)
                        self.assertEqual((decoded['cycle'], decoded['kind'], decoded['phase'], decoded['code']),
                                         (cycle, CRUMB.KINDS[kind], CRUMB.PHASES[phase], code))

    def test_cycle_beyond_the_second_saturates(self):
        self.assertEqual(CRUMB.encode(7, 0, 7, 610), CRUMB.encode(2, 0, 7, 610))

    def test_bcd_registers_decode_to_the_written_value(self):
        value = CRUMB.encode(2, 0, 7, 610)
        self.assertEqual(CRUMB.registers_value(registers_for(value)), value)

    def test_a_real_clock_reading_is_not_mistaken_for_a_breadcrumb(self):
        rtc = CRUMB.parse_rtc_line('[    0.13] PM: RTC time: 15:57:26, date: 2026-09-14\n')
        with self.assertRaises(ValueError):
            CRUMB.date_to_value(rtc['year'], rtc['month'], rtc['day'], rtc['hour'])

    def test_kernel_line_after_a_reset_decodes_step_and_elapsed_time(self):
        value = CRUMB.encode(2, 0, 7, 610)
        year, month, day, hour = CRUMB.value_to_date(value)
        rtc = CRUMB.parse_rtc_line(f'PM: RTC time: {hour:02}:01:23, date: {year:04}-{month:02}-{day:02}')
        decoded = CRUMB.decode_value(CRUMB.date_to_value(rtc['year'], rtc['month'], rtc['day'], rtc['hour']))
        self.assertEqual(decoded['meaning'], 'CB_START of a device callback in dpm_suspend_noirq, device hash 610')
        self.assertEqual(decoded['cycle_meaning'], 'second (or later) attempt')
        self.assertEqual(rtc['minute'] * 60 + rtc['second'], 83)

    def test_markers_and_notifiers_are_named(self):
        self.assertEqual(CRUMB.decode_value(CRUMB.encode(1, 0, 15, 16 + 2))['meaning'], 'helper marker 2')
        self.assertEqual(CRUMB.decode_value(CRUMB.encode(2, 0, 15, 3))['meaning'], 'PM notifier PM_SUSPEND_PREPARE')
        self.assertEqual(CRUMB.decode_value(CRUMB.encode(2, 2, 15, 1002))['meaning'], 'PHASE_BEGIN CPU_OFF')

    def test_alarm_bytes_locate_the_region_access_in_the_reference_cycle(self):
        hash_ps3 = CRUMB.method_hash('PCI0.XHC1._PS3')
        log = '\n'.join([
            '# entries=7',
            f'100 1 50 7 CB_START 17 0 2 | 0000:00:17.0 | ahci pci_pm_suspend_noirq',
            f'101 1 51 7 CB_END 17 0 0 | 0000:00:17.0 | ',
            f'102 1 52 7 CB_START 610 0 2 | 0000:00:14.0 | xhci_hcd pci_pm_suspend_noirq',
            f'103 1 52 7 METHOD {hash_ps3} 1 0 | PCI0.XHC1._PS3 | ',
            '104 1 52 7 REGION 0 2 0 | D0D3 | PCI0.XHC1.XPRT | 2 1 8 0x74 0x3',
            '105 1 52 7 REGION 0 3 0 | MPMC | PMST | 0 1 32 0xfe000020 0x3',
            f'106 1 53 7 CB_END 610 0 0 | 0000:00:14.0 | ',
        ]) + '\n'
        entries = CRUMB.parse_log(log)
        self.assertEqual(entries[5]['address'], 0xFE000020)
        decoded = CRUMB.decode_value(CRUMB.encode(2, 0, 7, 610))
        report = CRUMB.locate(decoded, (7, hash_ps3, 3), entries, ['0000:00:14.0', 'usb1'],
                              [(hash_ps3, 'PCI0.XHC1._PS3')])
        self.assertEqual(report['device_candidates'], ['0000:00:14.0'])
        self.assertEqual(report['method_candidates'], ['PCI0.XHC1._PS3'])
        self.assertEqual(report['alive_after_cycle_start_s'], '3.5..4.0')
        (match,) = report['reference_matches']
        self.assertEqual(match['step'], 52)
        self.assertEqual(match['acpi_events_following'], 3)
        self.assertEqual(match['last_acpi_event'],
                         'REGION write SystemMemory 0xfe000020 width=32 value=0x3 field=MPMC region=PMST')

    def test_second_attempt_numbering_skips_first_use_region_setup(self):
        osdw, ps3 = CRUMB.method_hash('OSDW'), CRUMB.method_hash('PCI0.XHC1._PS3')
        log = '\n'.join([
            '1 1 52 7 CB_START 610 0 2 | 0000:00:14.0 | xhci_hcd pci_pm_suspend_noirq',
            f'2 1 52 7 METHOD {ps3} 1 0 | PCI0.XHC1._PS3 | ',
            f'3 1 52 7 METHOD {osdw} 2 0 | OSDW | ',
            '4 1 52 7 METHOD_END 0 3 0 | OSDW | ',
            '5 1 52 7 REGION 0 4 0 | D3HE | PCI0.XHC1.XPRT | 2 0 8 0xa2 0x0',
            '6 1 52 7 METHOD 197 5 0 | _SB_.PCI0._BBN | ',
            '7 1 52 7 METHOD 211 6 0 | _SB_.BN00 | ',
            '8 1 52 7 METHOD_END 0 7 0 | _SB_.BN00 | ',
            '9 1 52 7 METHOD_END 0 8 0 | _SB_.PCI0._BBN | ',
            '10 1 52 7 REGION 0 9 0 | D3HE | PCI0.XHC1.XPRT | 2 1 8 0xa2 0x4',
            '11 1 52 7 REGION 0 10 0 | STGE | PCI0.XHC1.XPRT | 2 0 8 0x50 0x0',
            '12 1 52 7 REGION 0 11 0 | STGE | PCI0.XHC1.XPRT | 2 1 8 0x50 0x5f',
            '13 1 53 7 CB_END 610 0 0 | 0000:00:14.0 | ',
        ]) + '\n'
        decoded = CRUMB.decode_value(CRUMB.encode(2, 0, 7, 610))
        report = CRUMB.locate(decoded, (3, osdw, 6), CRUMB.parse_log(log), [], [(osdw, 'OSDW')])
        (match,) = report['reference_matches']
        self.assertEqual(match['numbering'], 'without first-use region setup (_BBN)')
        self.assertEqual(match['last_acpi_event'], 'REGION read PCI_Config 0x50 width=8 field=STGE region=PCI0.XHC1.XPRT')
        self.assertEqual(match['next_acpi_event'],
                         'REGION write PCI_Config 0x50 width=8 value=0x5f field=STGE region=PCI0.XHC1.XPRT')

    def test_rtc_debugfs_alarms_are_raw_bytes(self):
        registers, alarms = CRUMB.parse_rtc_debugfs('reg01=0e\nreg0b=02\nsaved_alarms=0e,c3,ff valid=1 last_value=5\n')
        self.assertEqual(alarms, (14, 195, 255))
        self.assertEqual(registers[0x0B], 2)

    def test_pm_helper_refuses_an_unarmed_or_logless_module(self):
        with tempfile.TemporaryDirectory() as tmp:
            parameters, debug = Path(tmp) / 'parameters', Path(tmp) / 'debug'
            with self.assertRaises(RuntimeError):
                PM.require_crumb(parameters, debug)
            parameters.mkdir()
            (parameters / 'armed').write_text('N\n')
            with self.assertRaises(RuntimeError):
                PM.require_crumb(parameters, debug)
            (parameters / 'armed').write_text('Y\n')
            with self.assertRaises(RuntimeError):
                PM.require_crumb(parameters, debug)
            debug.mkdir()
            (debug / 'log').write_text('# entries=0\n')
            PM.require_crumb(parameters, debug)

    def test_real_s2idle_counts_even_when_the_rtc_cannot_time_it(self):
        # 2026-09-14 19:17: a 71.8 s sleep that CLOCK_BOOTTIME recorded as zero.
        log = ('[ 4816.060013] PM: suspend entry (s2idle)\n'
               '[ 4818.221591] PM: suspend-to-idle\n'
               '[ 4890.065693] PM: Triggering wakeup from IRQ 9\n'
               '[ 4890.065968] PM: resume from suspend-to-idle\n'
               '[ 4892.248614] PM: suspend exit\n')
        self.assertAlmostEqual(PM.s2idle_seconds(log), 71.844377, places=5)
        verdict = PM.assess('none', 's2idle', {'success': 0, 'fail': 0}, {'success': 1, 'fail': 0},
                            log, 5.06, 0.0, 5)
        self.assertEqual(verdict, 'PASS')

    def test_aborted_s2idle_without_the_loop_is_still_inconclusive(self):
        log = '[ 10.0] PM: suspend entry (s2idle)\n[ 12.0] PM: suspend exit\n'
        self.assertEqual(PM.s2idle_seconds(log), 0.0)
        verdict = PM.assess('none', 's2idle', {'success': 0, 'fail': 0}, {'success': 1, 'fail': 0},
                            log, 2.0, 0.0, 5)
        self.assertTrue(verdict.startswith('INCONCLUSIVE'))

    def test_reference_is_the_newest_completed_first_cycle_of_the_requested_boot(self):
        import json
        import os
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            def make(name, boot, ok, mtime):
                run = root / name
                run.mkdir()
                (run / 'context.json').write_text(json.dumps({'boot_id': boot}))
                after = {'success': 1 if ok else 0, 'fail': 0 if ok else 1}
                (run / '1-none-result.json').write_text(json.dumps({'before': {'success': 0, 'fail': 0},
                                                                     'after': after}))
                (run / '1-none-crumb.txt').write_text('# entries=0\n')
                os.utime(run / '1-none-crumb.txt', (mtime, mtime))
                return run
            old = make('imac-second-sleep-old', 'boot-a', True, 100)
            make('imac-second-sleep-failed', 'boot-a', False, 200)
            other = make('imac-second-sleep-other', 'boot-b', True, 300)
            self.assertEqual(CRUMB.reference_run('boot-a', root), old)
            self.assertEqual(CRUMB.reference_run(None, root), other)
            self.assertIsNone(CRUMB.reference_run('boot-c', root))


if __name__ == '__main__':
    unittest.main()
