#!/usr/bin/env python3
"""Test the patched compositor in a temporary window inside a Wayland session."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

from demo import build

CONFIG = '''hl.monitor({output="",mode="preferred",position="auto",scale=1,
  cm="edr",max_luminance=500,sdr_max_luminance=200,supports_hdr=-1})
hl.config({
  general={gaps_in=0,gaps_out=0,border_size=0},
  decoration={rounding=0,shadow={enabled=false},
    blur={enabled=true,size=4,passes=2,brightness=1,contrast=1,noise=0,vibrancy=0}},
  animations={enabled=false},
  misc={disable_hyprland_logo=true,disable_splash_rendering=true,
        enable_anr_dialog=false,disable_autoreload=true},
  render={use_fp16=0,fp16_sdr_tf=0,direct_scanout=1},
  xwayland={enabled=false},ecosystem={enforce_permissions=false},
  debug={disable_logs=false},
})
hl.window_rule({name="blur-probe",match={class="imac-edr-blur-probe"},
  float=true,size="monitor_w monitor_h",move="0 0"})
'''


def ctl(env, command):
    return json.loads(subprocess.check_output(['hyprctl', '-j', command], env=env, timeout=5))


def stop(process):
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def ppm(path):
    # grim's PPM output is a three-line header followed by packed RGB8.
    magic, dimensions, maximum, pixels = path.read_bytes().split(b'\n', 3)
    width, height = map(int, dimensions.split())
    if magic != b'P6' or maximum != b'255' or len(pixels) != width * height * 3:
        raise ValueError('Unexpected screencopy format')
    return width, height, pixels


def samples(path):
    width, height, pixels = ppm(path)
    values = []
    for bar in range(7):
        offset = (height // 3 * width + (2 * bar + 1) * width // 14) * 3
        rgb = pixels[offset:offset + 3]
        if max(rgb) - min(rgb) > 2:
            raise ValueError(f'Neutral bar acquired a color cast: {tuple(rgb)}')
        values.append(sum(rgb) / 3)
    return values


def wait_window(env, client):
    deadline = time.monotonic() + 10
    while not any(c['pid'] == client.pid and c['mapped'] for c in ctl(env, 'clients')):
        if client.poll() is not None or time.monotonic() > deadline:
            raise RuntimeError('Color-managed window did not map')
        time.sleep(0.1)
    time.sleep(0.3)  # Let its first frame reach the compositor.


def capture(env, monitor, frame):
    subprocess.run(['grim', '-o', monitor['name'], '-t', 'ppm', str(frame)],
                   env=env, check=True, timeout=8)
    return samples(frame)


def run(binary, work):
    parent = Path(os.environ['WAYLAND_DISPLAY'])
    if not parent.is_absolute():
        parent = Path(os.environ['XDG_RUNTIME_DIR']) / parent
    for name in ('config', 'cache'):
        (work / name).mkdir(mode=0o700)
    # Hyprland binds $XDG_RUNTIME_DIR/hypr/<commit>_<time>_<random>/.socket2.sock.
    # A socket path has 107 usable bytes and a signature with the full commit
    # hash up to 62, leaving 25 for this directory: `work` is too long.
    runtime = Path(tempfile.mkdtemp(prefix='edr-', dir='/tmp'))
    (work / 'runtime').symlink_to(runtime)
    config = work / 'hyprland.lua'
    config.write_text(CONFIG)
    pattern = build(work / 'pattern')
    env = dict(os.environ, WAYLAND_DISPLAY=str(parent), XDG_RUNTIME_DIR=str(runtime),
               XDG_CONFIG_HOME=str(work / 'config'), XDG_CACHE_HOME=str(work / 'cache'),
               # A nonexistent libseat backend prevents opening a physical seat.
               LIBSEAT_BACKEND='none', AQ_DRM_DEVICES='/dev/null', GSETTINGS_BACKEND='memory',
               HYPRLAND_NO_SD_VARS='1', HYPRLAND_NO_SD_NOTIFY='1', HYPRLAND_NO_RT='1',
               HYPRLAND_NO_CRASHREPORTER='1')
    for key in ('HYPRLAND_INSTANCE_SIGNATURE', 'DBUS_SESSION_BUS_ADDRESS', 'DISPLAY', 'NOTIFY_SOCKET'):
        env.pop(key, None)
    with (work / 'config-check.log').open('w') as log:
        subprocess.run([str(binary), '--verify-config', '-c', str(config)], env=env,
                       stdout=log, stderr=subprocess.STDOUT, check=True, timeout=15)
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
        monitors = ctl(env, 'monitors')
        if len(monitors) != 1 or not monitors[0]['name'].startswith('WAYLAND-'):
            raise RuntimeError('Expected exactly one nested Wayland output')
        monitor = monitors[0]
        if any(ctl(env, 'configerrors')):
            raise RuntimeError('Nested configuration has errors')
        if (monitor['colorManagementPreset'] != 'edr' or monitor['sdrMaxLuminance'] != 200 or
                monitor['hardwareCursorsInUse'] or 'CM' not in monitor['directScanoutBlockedBy']):
            raise RuntimeError('EDR monitor policy was not applied')
        values = {}
        for name, options in (('pq', []), ('sdr', ['--sdr']), ('pq1000', ['--peak', '1000'])):
            with (work / f'{name}.log').open('w') as log:
                client = subprocess.Popen([str(pattern), '--fullscreen', '--seconds', '30', *options],
                                          env=env, stdout=log, stderr=subprocess.STDOUT)
            try:
                wait_window(env, client)
                values[name] = capture(env, monitor, work / f'{name}.ppm')
            finally:
                stop(client)
        pq, sdr, high = values['pq'], values['sdr'], values['pq1000']
        if any(abs(pq[i] - sdr[i]) > 3 or abs(high[i] - sdr[i]) > 3 for i in range(4)):
            raise RuntimeError('SDR, PQ, and tone-mapped PQ disagree below reference white')
        if any(abs(v - sdr[3]) > 2 for v in sdr[4:]):
            raise RuntimeError('SDR comparison did not clip at reference white')
        for name in ('pq', 'pq1000'):
            bars = values[name]
            if bars[0] > 2 or bars[6] < bars[3] + 15 or any(a >= b for a, b in zip(bars, bars[1:])):
                raise RuntimeError(f'{name}: HDR highlights are not retained')
        # Put a transparent floating surface over the bars: blur must preserve
        # their centers while actually changing their edges.
        with (work / 'blur.log').open('w') as log:
            background = subprocess.Popen([str(pattern), '--seconds', '30'], env=env, stdout=log, stderr=log)
            try:
                wait_window(env, background)
                values['before_blur'] = capture(env, monitor, work / 'before-blur.ppm')
                overlay = subprocess.Popen([str(pattern), '--blur-probe', '--seconds', '30'], env=env, stdout=log, stderr=log)
                try:
                    wait_window(env, overlay)
                    values['blur'] = capture(env, monitor, work / 'blur.ppm')
                finally:
                    stop(overlay)
            finally:
                stop(background)
        if any(abs(a - b) > 3 for a, b in zip(values['before_blur'], values['blur'])):
            raise RuntimeError('Blur changed the luminance of a uniform patch')
        width, height, before = ppm(work / 'before-blur.ppm')
        w2, h2, after = ppm(work / 'blur.ppm')
        if (width, height) != (w2, h2):
            raise RuntimeError('Output resized during blur test')
        edge = (height // 3 * width + (width + 6) // 7) * 3
        if abs(before[edge] - after[edge]) < 5:
            raise RuntimeError('Blur probe did not blur the background')
        report = {'monitor': monitor, 'screencopy_rgb8': values,
                  'note': 'Screencopy receives a separate SDR conversion. These are not panel code values or measured nits.'}
        (work / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
        print('PASS: reference-white matching, HDR highlights, tone mapping, blur, EDR monitor policy')
        print(json.dumps(values))
    finally:
        stop(compositor)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('hyprland', type=Path, help='patched Hyprland executable')
    args = parser.parse_args()
    if not os.environ.get('WAYLAND_DISPLAY') or not os.environ.get('XDG_RUNTIME_DIR'):
        parser.error('run inside a Wayland session')
    work = Path(tempfile.mkdtemp(prefix='imac-edr-nested-'))
    print(f'Test artifacts: {work}', flush=True)
    try:
        run(args.hyprland.expanduser().resolve(), work)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        parser.exit(1, f'{error}\nSee {work} for logs.\n')


if __name__ == '__main__':
    main()
