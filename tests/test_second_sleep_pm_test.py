"""Offline checks for interpreting the second-suspend diagnostic safely."""
import importlib.util
from pathlib import Path
import tempfile
import unittest


SPEC = importlib.util.spec_from_file_location(
    'second_sleep_pm_test', Path(__file__).resolve().parents[1] / 'notes/second-sleep-pm-test.py')
DIAG = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DIAG)


class SecondSleepPmTest(unittest.TestCase):
    def test_trace_must_record_current_boot_and_both_sides_of_pm_callbacks(self):
        with tempfile.TemporaryDirectory() as tmp:
            trace = Path(tmp)
            (trace / 'last_boot_info').write_text('# Current\n')
            (trace / 'tracing_on').write_text('1\n')
            for event in DIAG.TRACE_EVENTS:
                directory = trace / 'events/power' / event
                directory.mkdir(parents=True)
                (directory / 'enable').write_text('1\n')
            DIAG.require_recording(trace)
            (trace / 'tracing_on').write_text('0\n')
            with self.assertRaises(RuntimeError):
                DIAG.require_recording(trace)
            (trace / 'tracing_on').write_text('1\n')
            end = trace / 'events/power/device_pm_callback_end/enable'
            end.write_text('0\n')
            with self.assertRaises(RuntimeError):
                DIAG.require_recording(trace)
            end.write_text('1\n')
            (trace / 'last_boot_info').write_text('ffffffff81000000 [kernel]\n')
            with self.assertRaises(RuntimeError):
                DIAG.require_recording(trace)

    def assess(self, stage='devices', mode='s2idle', after=None, log=None, elapsed=75, sleep_seconds=0):
        return DIAG.assess(stage, mode, {'success': 1, 'fail': 0},
                           after if after is not None else {'success': 2, 'fail': 0},
                           log if log is not None else (
                               'PM: suspend entry (s2idle)\n'
                               'suspend debug: Waiting for 70 second(s).\nPM: suspend exit\n'),
                           elapsed, sleep_seconds, 70)

    def test_full_staged_cycle_passes(self):
        self.assertEqual(self.assess(), 'PASS')

    def test_driver_abort_is_not_a_pass_even_if_systemd_retries_successfully(self):
        self.assertTrue(self.assess(after={'success': 2, 'fail': 1}).startswith('FAIL'))

    def test_early_wakeup_before_reaching_the_test_delay_is_not_a_pass(self):
        self.assertTrue(self.assess(log='PM: suspend entry (s2idle)\nPM: suspend exit\n').startswith('INCONCLUSIVE'))

    def test_early_return_from_the_delay_is_not_a_pass(self):
        self.assertTrue(self.assess(elapsed=25).startswith('INCONCLUSIVE'))

    def test_wrong_sleep_mode_is_not_a_pass(self):
        self.assertTrue(self.assess(mode='deep').startswith('INCONCLUSIVE'))

    def test_pm_test_cannot_prime_the_real_first_sleep(self):
        self.assertTrue(self.assess(stage='none', sleep_seconds=30).startswith('INCONCLUSIVE'))
        log = 'PM: suspend entry (s2idle)\nPM: suspend exit\n'
        self.assertTrue(self.assess(stage='none', log=log).startswith('INCONCLUSIVE'))
        self.assertEqual(self.assess(stage='none', log=log, sleep_seconds=30), 'PASS')

    def test_async_enqueue_does_not_complete_the_cycle(self):
        previous = {'ExecMainStartTimestampMonotonic': '100', 'ActiveState': 'inactive'}
        self.assertFalse(DIAG.completed(previous, previous))
        self.assertFalse(DIAG.completed(previous, {'ExecMainStartTimestampMonotonic': '200', 'ActiveState': 'activating'}))
        self.assertFalse(DIAG.completed(previous, {'ExecMainStartTimestampMonotonic': '0', 'ActiveState': 'inactive'}))
        self.assertTrue(DIAG.completed(previous, {'ExecMainStartTimestampMonotonic': '200', 'ActiveState': 'inactive'}))

    def test_failed_service_completes_the_wait_so_settings_can_be_restored(self):
        self.assertTrue(DIAG.completed({'ExecMainStartTimestampMonotonic': '100'},
                                       {'ExecMainStartTimestampMonotonic': '200', 'ActiveState': 'failed'}))

    def test_unloaded_finished_unit_is_recognized_by_persistent_kernel_counters(self):
        unloaded = {'ExecMainStartTimestampMonotonic': '0', 'ActiveState': 'inactive'}
        before = {'success': 1, 'fail': 0}
        self.assertTrue(DIAG.completed(unloaded, unloaded, before, {'success': 2, 'fail': 0}))
        self.assertFalse(DIAG.completed(unloaded, unloaded, before, before))

    def test_counter_advance_does_not_finish_while_post_hooks_are_running(self):
        active = {'ExecMainStartTimestampMonotonic': '200', 'ActiveState': 'activating'}
        self.assertFalse(DIAG.completed({}, active, {'success': 1, 'fail': 0}, {'success': 2, 'fail': 0}))

    def test_wifi_netdev_and_old_phy_do_not_prove_reprobe_has_initialized_reset_work(self):
        with tempfile.TemporaryDirectory() as tmp:
            device = Path(tmp) / 'device'
            debug = Path(tmp) / 'debug'
            (device / 'net/wlp3s0').mkdir(parents=True)
            (device / 'ieee80211/phy1').mkdir(parents=True)
            (debug / 'phy0').mkdir(parents=True)
            (debug / 'phy0/reset').touch()
            self.assertFalse(DIAG.wifi_ready(device, debug))
            (debug / 'phy1').mkdir()
            (debug / 'phy1/reset').touch()
            self.assertTrue(DIAG.wifi_ready(device, debug))

    def fake_thunderbolt(self, tmp, usb_stick=False, bound=True):
        port = Path(tmp) / '0000:00:1c.4'
        functions = {'0000:05:00.0': '0x1578', '0000:05:00.0/0000:06:00.0': '0x15d3',
                     '0000:05:00.0/0000:06:00.0/0000:07:00.0': '0x15d2',
                     '0000:05:00.0/0000:06:02.0': '0x15d3', '0000:05:00.0/0000:06:02.0/0000:08:00.0': '0x15d4'}
        for relative, device in functions.items():
            path = port / relative
            path.mkdir(parents=True)
            (path / 'vendor').write_text('0x8086\n')
            (path / 'device').write_text(device + '\n')
        drivers = Path(tmp) / 'drivers'
        for name in ('pcieport', 'thunderbolt'):
            (drivers / name).mkdir(parents=True)
        if bound:
            (port / '0000:05:00.0/driver').symlink_to(drivers / 'pcieport')
            (port / '0000:05:00.0/0000:06:00.0/0000:07:00.0/driver').symlink_to(drivers / 'thunderbolt')
        (port / '0000:05:00.0/0000:06:00.0/0000:07:00.0/domain0/0-0').mkdir(parents=True)
        (port / '0000:05:00.0/0000:06:02.0/0000:08:00.0/usb4').mkdir()
        if usb_stick:
            stick = port / '0000:05:00.0/0000:06:02.0/0000:08:00.0/usb4/4-1'
            (stick / '4-1:1.0/host1/target1:0:0/1:0:0:0/block/sdb').mkdir(parents=True)
            (stick / 'idVendor').write_text('24a9\n')
            (stick / 'product').write_text('USB3.2 Flash Drive\n')
        return port

    def test_thunderbolt_subtree_lists_every_function_below_the_root_port(self):
        with tempfile.TemporaryDirectory() as tmp:
            port = self.fake_thunderbolt(tmp)
            self.assertEqual(list(DIAG.tb_subtree(port)), ['0000:05:00.0', '0000:06:00.0', '0000:06:02.0',
                                                           '0000:07:00.0', '0000:08:00.0'])
            self.assertEqual(DIAG.tb_subtree(port)['0000:07:00.0'], '0x8086:0x15d2')

    def test_thunderbolt_switch_is_not_mistaken_for_a_usb_device(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(DIAG.tb_in_use(self.fake_thunderbolt(tmp)), [])

    def test_removal_refuses_while_a_usb_stick_is_attached(self):
        with tempfile.TemporaryDirectory() as tmp:
            users = DIAG.tb_in_use(self.fake_thunderbolt(tmp, usb_stick=True))
            self.assertIn('USB 4-1 (USB3.2 Flash Drive)', users)
            self.assertIn('block sdb', users)

    def test_restored_requires_bridge_and_nhi_bound_to_thunderbolt(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertTrue(DIAG.tb_restored(self.fake_thunderbolt(tmp)))
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(DIAG.tb_restored(self.fake_thunderbolt(tmp, bound=False)))
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(DIAG.tb_restored(Path(tmp)))


if __name__ == '__main__':
    unittest.main()
