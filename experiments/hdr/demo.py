#!/usr/bin/env python3
"""Build and run a temporary, color-managed Wayland test window."""
import argparse
import math
from pathlib import Path
import shlex
import subprocess
import tempfile


def build(directory):
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    protocols = Path(subprocess.check_output(
        ['pkg-config', '--variable=pkgdatadir', 'wayland-protocols'], text=True).strip())
    for name, xml in (
        ('xdg-shell', protocols / 'stable/xdg-shell/xdg-shell.xml'),
        ('color-management', protocols / 'staging/color-management/color-management-v1.xml'),
    ):
        subprocess.run(['wayland-scanner', 'client-header', str(xml), str(directory / f'{name}-client.h')], check=True)
        subprocess.run(['wayland-scanner', 'private-code', str(xml), str(directory / f'{name}-protocol.c')], check=True)
    flags = shlex.split(subprocess.check_output(['pkg-config', '--cflags', '--libs', 'wayland-client'], text=True))
    binary = directory / 'imac-edr-pattern'
    subprocess.run([
        'cc', '-std=c11', '-O2', '-Wall', '-Wextra', '-I', str(directory),
        str(Path(__file__).with_name('pattern.c')),
        str(directory / 'xdg-shell-protocol.c'), str(directory / 'color-management-protocol.c'),
        *flags, '-lm', '-o', str(binary),
    ], check=True)
    return binary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build-only', type=Path, metavar='DIRECTORY')
    parser.add_argument('--sdr', action='store_true', help='show a tagged SDR comparison')
    parser.add_argument('--fullscreen', action='store_true')
    parser.add_argument('--peak', type=float, default=507.5, help='HDR source peak in nits (203..10000)')
    parser.add_argument('--seconds', type=int, default=30, choices=range(1, 3601), metavar='1..3600')
    args = parser.parse_args()
    if not math.isfinite(args.peak) or not 203 <= args.peak <= 10000:
        parser.error('--peak must be 203..10000')
    if args.build_only:
        print(build(args.build_only))
        return 0
    with tempfile.TemporaryDirectory(prefix='imac-edr-pattern-') as directory:
        binary = build(directory)
        command = [str(binary), '--seconds', str(args.seconds), '--peak', str(args.peak)]
        if args.sdr:
            command.append('--sdr')
        if args.fullscreen:
            command.append('--fullscreen')
        return subprocess.run(command).returncode


if __name__ == '__main__':
    raise SystemExit(main())
