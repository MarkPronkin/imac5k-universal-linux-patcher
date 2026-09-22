#!/usr/bin/env python3
"""Press the staged test session's keys in a temporary window inside a Wayland session."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

GUIDE = 'iMac EDR test'
PATTERN = 'imac-edr-pattern'


def wait(predicate, seconds=10):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if value := predicate():
            return value
        time.sleep(0.1)
    return predicate()


def stop(process):
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def run(work, directory, exit_keys):
    binary = directory / 'build/Hyprland'
    config = directory / 'session/hyprland.lua'
    if not binary.is_file() or not config.is_file():
        raise ValueError(f'{directory}: stage a session first (session.py stage)')
    parent = Path(os.environ['WAYLAND_DISPLAY'])
    if not parent.is_absolute():
        parent = Path(os.environ['XDG_RUNTIME_DIR']) / parent
    record = work / 'record'
    for name in ('record', 'config', 'cache'):
        (work / name).mkdir(mode=0o700)
    runtime = Path(tempfile.mkdtemp(prefix='edr-', dir='/tmp'))  # Short IPC socket paths; see verify-nested.py.
    (work / 'runtime').symlink_to(runtime)
    env = dict(os.environ, WAYLAND_DISPLAY=str(parent), XDG_RUNTIME_DIR=str(runtime),
               XDG_CONFIG_HOME=str(work / 'config'), XDG_CACHE_HOME=str(work / 'cache'),
               LIBSEAT_BACKEND='none', AQ_DRM_DEVICES='/dev/null', GSETTINGS_BACKEND='memory',
               HYPRLAND_NO_SD_VARS='1', HYPRLAND_NO_SD_NOTIFY='1', HYPRLAND_NO_RT='1',
               HYPRLAND_NO_CRASHREPORTER='1', IMAC_EDR_RUN=str(record), IMAC_EDR_DEADLINE='--:--',
               SHELL='/bin/sh')
    for key in ('HYPRLAND_INSTANCE_SIGNATURE', 'DBUS_SESSION_BUS_ADDRESS', 'DISPLAY', 'NOTIFY_SOCKET'):
        env.pop(key, None)
    failures = []

    def check(ok, what):
        print(('PASS ' if ok else 'FAIL ') + what, flush=True)
        if not ok:
            failures.append(what)

    def ctl(*args):
        return json.loads(subprocess.check_output(['hyprctl', '-j', *args], env=env, timeout=5))

    def windows(kind):
        return [c for c in ctl('clients') if c['mapped'] and c['class'] == kind]

    def guides():
        return [c for c in windows('foot') if c['title'] == GUIDE]

    def press(*keys):
        subprocess.run(['wtype', *keys], env=env, check=True, timeout=5)
        time.sleep(0.4)

    def patterns_after(*keys, count=1):
        press('-M', 'logo', *keys, '-m', 'logo')
        time.sleep(0.6)  # Let any replaced pattern unmap.
        return wait(lambda: len(windows(PATTERN)) == count and windows(PATTERN))

    with (work / 'compositor.log').open('w') as log:
        compositor = subprocess.Popen([str(binary), '-c', str(config)], env=env, stdout=log,
                                      stderr=subprocess.STDOUT, start_new_session=True)
    try:
        deadline = time.monotonic() + 15
        while True:
            if compositor.poll() is not None:
                raise RuntimeError('Nested compositor exited; see compositor.log')
            locks = list(runtime.glob('hypr/*/hyprland.lock'))
            if locks:
                lines = locks[0].read_text().splitlines()
                if len(lines) >= 2 and lines[0] == str(compositor.pid):
                    env.update(HYPRLAND_INSTANCE_SIGNATURE=locks[0].parent.name, WAYLAND_DISPLAY=lines[1])
                    break
            if time.monotonic() > deadline:
                raise TimeoutError('Nested compositor did not become ready')
            time.sleep(0.1)
        check(not any(ctl('configerrors')), 'the session configuration has no errors')
        # wtype sends its own keymap. Physical keyboards use the configured layout,
        # so only this test resolves bindings through each keyboard's symbols.
        subprocess.run(['hyprctl', 'eval', 'hl.config({ input = { resolve_binds_by_sym = true } })'],
                       env=env, check=True, timeout=5, stdout=subprocess.DEVNULL)
        check(len(ctl('binds')) == 11, 'eleven bindings are registered')
        check(bool(wait(guides)), 'the guide opened at start')
        check(bool(wait(lambda: (record / 'monitors.json').exists(), 12)), 'the guide recorded monitors.json')
        monitor = ctl('monitors')[0]
        width, height = monitor['width'] / monitor['scale'], monitor['height'] / monitor['scale']

        shown = patterns_after('-k', '1')
        check(bool(shown) and shown[0]['fullscreen'] != 0, 'Super+1 shows a fullscreen HDR pattern')
        press('-k', 'Escape')
        check(bool(wait(lambda: not windows(PATTERN), 5)), 'Esc closes it')
        patterns_after('-k', '1')
        shown = patterns_after('-k', '2')
        check(bool(shown) and 'SDR' in shown[0]['title'], 'Super+2 replaces it with the SDR pattern')
        press('-M', 'logo', '-k', 'w', '-m', 'logo')
        check(bool(wait(lambda: not windows(PATTERN), 5)), 'Super+W closes the pattern')
        time.sleep(0.5)
        check(len(guides()) == 1, 'and leaves the guide open')
        pair = patterns_after('-k', '4', count=2)
        top = next((c for c in pair or [] if 'PQ' in c['title']), None)
        bottom = next((c for c in pair or [] if 'SDR' in c['title']), None)
        check(top is not None and top['floating'] and top['at'][1] == 0 and abs(top['size'][1] - height / 2) <= 1,
              'Super+4 floats HDR over the top half')
        check(bottom is not None and abs(bottom['at'][1] - height / 2) <= 1 and abs(bottom['size'][0] - width) <= 1,
              'and SDR over the bottom half')
        shown = patterns_after('-k', '1')
        check(bool(shown) and shown[0]['fullscreen'] != 0, 'Super+1 replaces both')
        press('-k', 'q')
        check(bool(wait(lambda: not windows(PATTERN), 5)), 'another key closes a pattern too')
        press('-M', 'logo', '-k', 'Return', '-m', 'logo')
        check(bool(wait(lambda: len(windows('foot')) >= 2)), 'Super+Return opens a terminal')
        press('-M', 'logo', '-k', 'd', '-m', 'logo')
        check(bool(wait(lambda: not ctl('monitors')[0]['dpmsStatus'], 2)), 'Super+D switches the display off')
        check(bool(wait(lambda: ctl('monitors')[0]['dpmsStatus'], 6)), 'and on again by itself')
        press(*exit_keys)
        try:
            check(compositor.wait(timeout=10) == 0, 'the exit keys end the session cleanly')
        except subprocess.TimeoutExpired:
            check(False, 'the exit keys end the session cleanly')
    finally:
        stop(compositor)
    return failures


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path, help='build directory with a staged session')
    parser.add_argument('--ctrl-alt-backspace', action='store_true', help='exit with Ctrl+Alt+Backspace, not Super+Escape')
    args = parser.parse_args()
    if not os.environ.get('WAYLAND_DISPLAY') or not os.environ.get('XDG_RUNTIME_DIR'):
        parser.error('run inside a Wayland session')
    exit_keys = (['-M', 'ctrl', '-M', 'alt', '-k', 'BackSpace', '-m', 'alt', '-m', 'ctrl'] if args.ctrl_alt_backspace
                 else ['-M', 'logo', '-k', 'Escape', '-m', 'logo'])
    work = Path(tempfile.mkdtemp(prefix='imac-edr-session-'))
    print(f'Test artifacts: {work}', flush=True)
    try:
        failures = run(work, args.directory.expanduser().resolve(), exit_keys)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        parser.exit(1, f'{error}\nSee {work} for logs.\n')
    if failures:
        parser.exit(1, f'{len(failures)} checks failed; see {work}.\n')
    print('PASS: the staged session responds to its keys')


if __name__ == '__main__':
    sys.exit(main())
