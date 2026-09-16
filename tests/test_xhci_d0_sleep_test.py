"""The xHCI-in-D0 validation must fail any cycle that did not really sleep and come back whole."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location(
    'xhci_d0_sleep_test', Path(__file__).resolve().parents[1] / 'notes/xhci-d0-sleep-test.py')
TEST = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TEST)

GOOD_LOG = ('[ 10.0] PM: suspend entry (s2idle)\n[ 12.0] PM: suspend-to-idle\n'
            '[ 45.0] PM: resume from suspend-to-idle\n[ 47.0] PM: suspend exit\n')
KEYBOARD = ['05ac:0250', '046d:c52b']


class XhciD0SleepTest(unittest.TestCase):
    def check(self, **changes):
        args = dict(before={'success': 1, 'fail': 0}, after={'success': 2, 'fail': 0}, log=GOOD_LOG,
                    sleep_seconds=33.0, devices_before=KEYBOARD, devices_after=KEYBOARD,
                    service={'Result': 'success'})
        args.update(changes)
        return TEST.check_cycle(**args)

    def test_real_sleep_with_devices_back_passes(self):
        self.assertEqual(self.check(), [])

    def test_failures_are_reported(self):
        cases = {
            'counters': dict(after={'success': 2, 'fail': 1}),
            'short': dict(sleep_seconds=0.0),
            'deep': dict(log=GOOD_LOG.replace('(s2idle)', '(deep)')),
            'refused': dict(log=GOOD_LOG + 'PM: Some devices failed to suspend, or early wake event detected\n'),
            'usb': dict(devices_after=KEYBOARD[:1]),
            'service': dict(service={'Result': 'exit-code'}),
            'no keyboard wake': dict(keyboard_woke=False),
            'xhci error': dict(log=GOOD_LOG + '[ 48.0] xhci_hcd 0000:00:14.0: xHCI host not responding to stop endpoint command\n'),
        }
        for name, change in cases.items():
            with self.subTest(name):
                self.assertTrue(self.check(**change))

    def test_deep_needs_a_real_s3_resume_and_tolerates_power_button_wake(self):
        deep = ('[ 10.0] PM: suspend entry (deep)\n[ 11.0] ACPI: PM: Preparing to enter system sleep state S3\n'
                '[ 11.5] ACPI: PM: Low-level resume complete\n[ 11.6] ACPI: PM: Waking up from system sleep state S3\n'
                '[ 11.6] Timekeeping suspended for 61.250 seconds\n[ 14.0] PM: suspend exit\n')
        self.assertEqual(TEST.timekeeping_seconds(deep), 61.25)
        self.assertEqual(self.check(log=deep, mode='deep', keyboard_woke=False), [])
        self.assertTrue(self.check(log=deep.replace('Low-level resume complete', '').replace('Waking up', ''),
                                   mode='deep'))
        self.assertTrue(self.check(log=deep, mode='s2idle'))
        self.assertEqual(TEST.cycle_warnings('deep', False, True, deep), ['the USB keyboard did not wake it from S3'])
        self.assertEqual(TEST.cycle_warnings('s2idle', False, True, deep), [])
        warned = TEST.cycle_warnings('deep', True, False, 'pcieport 0000:06:00.0: Unable to change power state from D3cold to D0, device inaccessible')
        self.assertEqual(len(warned), 2)

    def test_a_required_long_sleep_must_happen(self):
        results = [{'slept_seconds': 68.3}, {'slept_seconds': 612.0}]
        self.assertIsNone(TEST.long_sleep_problem(results, 600))
        self.assertIsNone(TEST.long_sleep_problem(results[:1], 0))
        self.assertEqual(TEST.long_sleep_problem(results[:1], 600), 'no sleep lasted 600 s')

    def test_usb_devices_are_found_below_the_controller(self):
        with tempfile.TemporaryDirectory() as tmp:
            device = Path(tmp) / 'usb1' / '1-6'
            device.mkdir(parents=True)
            (device / 'idVendor').write_text('05ac\n')
            (device / 'idProduct').write_text('0250\n')
            (Path(tmp) / 'usb1' / 'idVendor').write_text('1d6b\n')
            (Path(tmp) / 'usb1' / 'idProduct').write_text('0002\n')
            self.assertEqual(TEST.usb_devices(Path(tmp)), ['05ac:0250', '1d6b:0002'])


if __name__ == '__main__':
    unittest.main()
