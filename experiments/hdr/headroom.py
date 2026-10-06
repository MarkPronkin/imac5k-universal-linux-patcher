#!/usr/bin/env python3
"""Trade backlight for HDR headroom on an EDR output, keeping desktop white steady.

The panel has one backlight and no local dimming, so headroom only exists when
desktop white sits below the panel's peak. Raising the backlight and scaling the
desktop down by the same factor keeps white where it was and opens that gap, so
it is worth doing only while HDR content is on screen. Backlight level is
assumed to be proportional to luminance; `check` shows how that holds up.
"""
import argparse
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import time

BACKLIGHT = Path('/sys/class/backlight/acpi_video0')
OUTPUT, PANEL_PEAK, HEADROOM = 'eDP-1', 500, 2.5  # Peak nits at full backlight; see README.
WHITE, STEP, RAMP = 200, 25, 6  # Default desktop white, its step in nits, ramp steps
STATE = Path.home() / '.cache/imac5k-edr/headroom.json'
MATCHING = Path.home() / '.cache/imac5k-edr/matching.pid'


def levels():
    top = int((BACKLIGHT / 'max_brightness').read_text())
    return int((BACKLIGHT / 'actual_brightness').read_text()), top


def monitor():
    for one in json.loads(subprocess.check_output(['hyprctl', '-j', 'monitors'], timeout=5)):
        if one['name'] != OUTPUT:
            continue
        if one.get('colorManagementPreset') != 'edr':
            raise RuntimeError(f'{OUTPUT} is not in EDR mode; this only runs in the EDR test session')
        return one
    raise RuntimeError(f'{OUTPUT} is not active')


def state():
    try:
        saved = json.loads(STATE.read_text())
    except (OSError, ValueError):
        saved = {}
    return {'white': saved.get('white', WHITE), 'headroom': saved.get('headroom', 1.0),
            # Backlight level to luminance: measured by `match`, 1.0 until then.
            'curve': saved.get('curve', 1.0), 'match_level': saved.get('match_level', 0)}


def luminance(level, top, curve):
    """The fraction of full brightness a backlight level gives, per `match`."""
    return (level / top) ** curve


def backlight_for(peak, top, curve):
    return max(1, min(top, round(top * (peak / PANEL_PEAK) ** (1 / curve))))


def apply(white, headroom, ramp=RAMP, curve=None):
    """Move the backlight and the output's luminances together, in small steps."""
    level, top = levels()
    curve = state()['curve'] if curve is None else curve
    white = max(10, min(PANEL_PEAK, white))
    peak = min(PANEL_PEAK, white * headroom)
    target = backlight_for(peak, top, curve)
    for index in range(1, ramp + 1):
        step = round(level + (target - level) * index / ramp)
        reached = PANEL_PEAK * luminance(step, top, curve)
        subprocess.run(['brightnessctl', '--quiet', '--device', BACKLIGHT.name, 'set', str(step)], timeout=5, check=True)
        subprocess.run(['hyprctl', 'eval', (
            f'hl.monitor({{output="{OUTPUT}",mode="preferred",position="auto",scale=2,bitdepth=10,cm="edr",'
            f'max_luminance={round(reached)},sdr_max_luminance={round(min(white, reached))},supports_hdr=-1}})'
        )], timeout=5, check=True, stdout=subprocess.DEVNULL)
        if index < ramp:
            time.sleep(0.04)
    save(white=white, headroom=headroom)
    return white, peak


def save(**changes):
    saved = state() | changes
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(saved) + '\n')


def describe():
    level, top = levels()
    current, panel = state(), monitor()
    peak = PANEL_PEAK * luminance(level, top, current['curve'])
    return (f"backlight {level}/{top} ({100 * level / top:.0f}%), desktop white "
            f"{panel.get('sdrMaxLuminance')} nits, panel peak {peak:.0f} nits, headroom "
            f"{peak / max(1, panel.get('sdrMaxLuminance', 1)):.2f}x (setting: {current['white']} nits, "
            f"{current['headroom']:g}x, backlight curve {current['curve']:.2f})")


def rule(peak, white):
    subprocess.run(['hyprctl', 'eval', (
        f'hl.monitor({{output="{OUTPUT}",mode="preferred",position="auto",scale=2,bitdepth=10,cm="edr",'
        f'max_luminance={round(peak)},sdr_max_luminance={round(white)},supports_hdr=-1}})'
    )], timeout=5, check=True, stdout=subprocess.DEVNULL)


def set_backlight(level):
    subprocess.run(['brightnessctl', '--quiet', '--device', BACKLIGHT.name, 'set', str(level)],
                   timeout=5, check=True)


def matching():
    """The PID of a running measurement, if there is one."""
    try:
        pid = int(MATCHING.read_text())
        os.kill(pid, 0)
        return pid
    except (OSError, ValueError):
        return None


def measure(level, seconds):
    """Alternate the two states until stopped; the difference is what gets matched."""
    was, top = levels()
    MATCHING.write_text(f'{os.getpid()}\n')
    running = True

    def finish(*_):
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, finish)
    signal.signal(signal.SIGINT, finish)
    try:
        while running:
            for backlight, white in ((level, PANEL_PEAK), (top, state()['white'])):
                set_backlight(backlight)
                rule(PANEL_PEAK, white)
                for _ in range(int(seconds / 0.05)):
                    if not running:
                        break
                    time.sleep(0.05)
    finally:
        MATCHING.unlink(missing_ok=True)
        white = state()['white']
        curve = math.log(max(5, white) / PANEL_PEAK) / math.log(level / top)
        save(curve=round(curve, 3))
        set_backlight(was)
        apply(state()['white'], state()['headroom'])
    return curve


def match(level, seconds):
    """Start or stop the measurement; the session binds this to one key."""
    running = matching()
    if running:
        os.kill(running, signal.SIGTERM)
        for _ in range(40):
            if not matching():
                break
            time.sleep(0.05)
        current = state()
        print(f"backlight {current['match_level']}/{levels()[1]} measured as "
              f"{100 * current['white'] / PANEL_PEAK:.0f}% of full brightness: level^{current['curve']:.2f}")
        return current['curve']
    current = state()
    top = levels()[1]
    level = level or backlight_for(current['white'], top, current['curve'])
    # Start from the straight-line guess, and remember what is being measured.
    save(white=round(PANEL_PEAK * level / top / 5) * 5, match_level=level)
    if os.fork():
        return None
    os.setsid()
    devnull = os.open(os.devnull, os.O_RDWR)
    for fd in (0, 1, 2):
        os.dup2(devnull, fd)
    measure(level, seconds)
    os._exit(0)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('state', help='print the backlight and the output luminances')
    brighter = commands.add_parser('step', help='change desktop white, keeping the headroom setting')
    brighter.add_argument('nits', type=int, help=f'change in nits, e.g. {STEP} or -{STEP}')
    commands.add_parser('engage', help=f'open {HEADROOM:g}x headroom at the same desktop white')
    commands.add_parser('release', help='give the headroom back: lower backlight, brighter signal')
    commands.add_parser('toggle', help='engage or release, whichever is not current')
    checking = commands.add_parser('check', help='alternate between the two, to judge them by eye')
    checking.add_argument('--seconds', type=int, default=3, choices=range(1, 30), metavar='1..29')
    checking.add_argument('--rounds', type=int, default=4, choices=range(1, 20), metavar='1..19')
    measuring = commands.add_parser('match', help='start or stop measuring the backlight curve')
    measuring.add_argument('--level', type=int, default=0, help='backlight level to measure (default: the one in use)')
    measuring.add_argument('--seconds', type=float, default=1.0, help='how long to hold each state')
    args = parser.parse_args()
    try:
        current = state()
        if args.command == 'state':
            print(describe())
        elif args.command == 'step':
            white = max(5, min(PANEL_PEAK, current['white'] + args.nits))
            if matching():
                save(white=white)  # The measurement loop picks it up on its next turn.
                print(f'matching against {white} nits')
            else:
                white, peak = apply(white, current['headroom'])
                print(f'desktop white {white} nits, peak {peak:.0f} nits')
        elif args.command == 'match':
            match(args.level, args.seconds)
        elif args.command in ('engage', 'release', 'toggle'):
            headroom = HEADROOM if args.command == 'engage' else 1.0
            if args.command == 'toggle':
                headroom = 1.0 if current['headroom'] > 1 else HEADROOM
            white, peak = apply(current['white'], headroom)
            print(f'desktop white {white} nits, peak {peak:.0f} nits, headroom {peak / white:.2f}x')
        else:
            # White should not appear to change between the two; only highlights.
            for round_ in range(args.rounds):
                for headroom in (1.0, HEADROOM):
                    white, peak = apply(current['white'], headroom)
                    print(f'{round_ + 1}/{args.rounds}: peak {peak:.0f} nits, headroom {peak / white:.2f}x', flush=True)
                    time.sleep(args.seconds)
            apply(current['white'], current['headroom'])
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        parser.exit(1, f'{error}\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
