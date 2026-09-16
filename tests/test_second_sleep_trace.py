"""Offline guards for the diagnostic boot-memory reservation and recovery proof."""
import importlib.util
from pathlib import Path
import unittest


SPEC = importlib.util.spec_from_file_location(
    'second_sleep_trace', Path(__file__).resolve().parents[1] / 'notes/second-sleep-trace.py')
TRACE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TRACE)


class SecondSleepTraceTest(unittest.TestCase):
    def test_only_a_contiguous_unencumbered_ram_region_is_accepted(self):
        region = '100000000-86effffff : System RAM\n'
        self.assertTrue(TRACE.region_is(region, 'System RAM'))
        self.assertFalse(TRACE.region_is('00000000-00000000 : System RAM\n', 'System RAM'))
        self.assertFalse(TRACE.region_is('800000000-8007fffff : System RAM\n', 'System RAM'))
        self.assertFalse(TRACE.region_is(region + '  800000000-80000ffff : Kernel code\n', 'System RAM'))
        self.assertFalse(TRACE.region_is(region.replace('System RAM', 'Reserved'), 'System RAM'))
        self.assertTrue(TRACE.region_is('800000000-800ffffff : Reserved\n', 'Reserved'))

    def test_boot_options_preserve_encryption_and_other_existing_options(self):
        before = 'cryptdevice=PARTUUID=example:root root=/dev/mapper/root acpi_sleep=nonvs quiet'
        after = before + ' ' + ' '.join(TRACE.PARAMS)
        TRACE.check_cmdline_change(before, after, True)
        TRACE.check_cmdline_change(after, before, False)
        with self.assertRaises(RuntimeError):
            TRACE.check_cmdline_change(before, after.replace('root=/dev/mapper/root ', ''), True)
        with self.assertRaises(RuntimeError):
            TRACE.check_cmdline_change(before, after.replace('$0x800000000', 'bashx800000000'), True)
        with self.assertRaises(RuntimeError):
            TRACE.check_cmdline_change(before, after + ' quiet', True)
        with self.assertRaises(RuntimeError):
            TRACE.check_cmdline_change(after, before + ' reboot=pci', False)

    def test_existing_memory_and_trace_configuration_is_not_combined_blindly(self):
        for option in ('memmap=8M$0x100000000', 'reserve_mem=8M:4096:old', 'trace_instance=old'):
            with self.subTest(option=option), self.assertRaises(RuntimeError):
                TRACE.check_cmdline_change(option, option + ' ' + ' '.join(TRACE.PARAMS), True)

    def test_marker_must_survive_a_different_boot_with_identical_kernel_and_mapping(self):
        current = {'boot_id': 'new-boot', 'kernel': TRACE.KERNEL, 'params': list(TRACE.PARAMS)}
        marker = {**current, 'boot_id': 'old-boot', 'marker': 'unique-marker'}
        self.assertTrue(TRACE.marker_survived(marker, current, 'tracing_mark_write: unique-marker'))
        self.assertFalse(TRACE.marker_survived(marker, current, 'empty buffer'))
        self.assertFalse(TRACE.marker_survived({**marker, 'boot_id': 'new-boot'}, current, 'unique-marker'))
        self.assertFalse(TRACE.marker_survived({**marker, 'kernel': 'another'}, current, 'unique-marker'))
        self.assertFalse(TRACE.marker_survived({**marker, 'params': []}, current, 'unique-marker'))
        self.assertFalse(TRACE.marker_survived({}, current, 'unique-marker'))


if __name__ == '__main__':
    unittest.main()
