"""Ensure EFI recovery/deletion only recognizes this diagnostic's own records."""
import importlib.util
from pathlib import Path
import unittest

SPEC = importlib.util.spec_from_file_location(
    'second_sleep_efi_capture', Path(__file__).resolve().parents[1] / 'notes/second-sleep-efi-capture.py')
EFI = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(EFI)


class EfiCaptureTest(unittest.TestCase):
    def test_matching_owned_nonvolatile_record_decodes(self):
        text = 'IMAC_PM_CAPTURE v1 run=' + 'a' * 32 + ' part=0\nphase=dpm_suspend_noirq begin\n'
        result = EFI.decode_variable('ImacSleepCapture0-' + EFI.GUID, (7).to_bytes(4, 'little') + text.encode())
        self.assertEqual(result['part'], 0)
        self.assertEqual(result['run_id'], 'a' * 32)
        self.assertEqual(result['text'], text)

    def test_unrelated_and_inconsistent_records_are_never_accepted_for_deletion(self):
        name = 'ImacSleepCapture0-' + EFI.GUID
        payload = ('IMAC_PM_CAPTURE v1 run=' + 'a' * 32 + ' part=0\ndata').encode()
        raw = (7).to_bytes(4, 'little') + payload
        cases = [
            ('BootOrder-' + EFI.GUID, raw),
            (name.replace(EFI.GUID, '00000000-0000-0000-0000-000000000000'), raw),
            (name, (6).to_bytes(4, 'little') + payload),
            (name, (0x80000006).to_bytes(4, 'little') + payload),
            (name, (0x40000007).to_bytes(4, 'little') + payload),
            (name, (0x80000027).to_bytes(4, 'little') + payload),
            ('ImacSleepCapture1-' + EFI.GUID, raw),
            (name, raw.replace(b'IMAC_PM_CAPTURE', b'FOREIGN_CAPTURE')),
            (name, raw + b'x' * 1024),
        ]
        for filename, content in cases:
            with self.subTest(filename=filename, content=content[:80]), self.assertRaises(ValueError):
                EFI.decode_variable(filename, content)

    def test_apple_checksum_flag_preserves_owned_record_and_raw_attributes(self):
        text = 'IMAC_PM_CAPTURE v1 run=' + 'b' * 32 + ' part=2\nstack frame\n'
        raw = (0x80000007).to_bytes(4, 'little') + text.encode()
        record = EFI.decode_variable('ImacSleepCapture2-' + EFI.GUID, raw)
        self.assertEqual(record['attributes'], 0x80000007)
        self.assertEqual(record['text'], text)
        self.assertEqual(record['part'], 2)


if __name__ == '__main__':
    unittest.main()
