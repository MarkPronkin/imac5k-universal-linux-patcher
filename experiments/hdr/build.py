#!/usr/bin/env python3
"""Build the pinned EDR compositor in a separate directory; never install it.

The build itself is scripts/hypr-edr.py's, which imac-patcher's hdr module
uses too; this keeps the experiment's command line and directory layout.
"""
import argparse
import importlib.util
from pathlib import Path
import subprocess

HELPER = Path(__file__).resolve().parents[2] / 'scripts/hypr-edr.py'
spec = importlib.util.spec_from_file_location('hypr_edr', HELPER)
edr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(edr)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--cache', type=Path, help='directory for verified source archives')
    parser.add_argument('--jobs', type=int, default=4)
    parser.add_argument('--cmake', default='cmake')
    parser.add_argument('--prepare-only', action='store_true')
    args = parser.parse_args()
    if not 1 <= args.jobs <= 64:
        parser.error('--jobs must be 1..64')
    work = args.directory.expanduser().resolve()
    cache = args.cache.expanduser().resolve() if args.cache else work / 'downloads'
    try:
        result = edr.build(work, cache, jobs=args.jobs, cmake=args.cmake, prepare_only=args.prepare_only)
        print(f'Patched source: {result}' if args.prepare_only else f'Built: {result}')
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, f'{error}\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
