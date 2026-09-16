#!/usr/bin/env python3
"""Run the prepared two-cycle test with persistent PM tracing.

Normal-restart retention was validated; retention through the fault failed.
The separate EFI snapshot helper can wrap this test to record an overdue cycle.

    sudo python3 notes/recorded-second-sleep.py

Wake the first real sleep after about 30 seconds. Leave the next, five-second
platform test alone. If the machine resets, run second-sleep-trace.py capture
before starting any further recording or sleep. Nothing reboots automatically
except the unresolved fault itself.
"""
import argparse
from pathlib import Path
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tb-removed', action='store_true', help='remove the unused Thunderbolt PCI subtree')
    args = parser.parse_args()
    notes = Path(__file__).resolve().parent
    subprocess.run([sys.executable, str(notes / 'second-sleep-trace.py'), 'start'], check=True)
    test_command = [sys.executable, str(notes / 'second-sleep-pm-test.py'),
                    'platform', '--prime', '--mode', 's2idle', '--delay', '5',
                    '--wifi-unbound', '--serial', '--persistent-trace']
    if args.tb_removed:
        test_command.append('--tb-removed')
    subprocess.run(test_command, check=True)
    # Only stop after the test helper confirms all cycles and cleanup succeeded.
    # An unsuccessful helper may have deliberately left a pending PM job armed.
    subprocess.run([sys.executable, str(notes / 'second-sleep-trace.py'), 'stop'], check=True)


if __name__ == '__main__':
    main()
