#!/usr/bin/env python3
"""Test the patched compositor on the iMac's own display, from a text console.

`stage BUILD_DIRECTORY` runs from the repository and writes a self-contained
session next to a build.py build. Its `BUILD_DIRECTORY/start` then runs on
another virtual console while the desktop keeps running on its own.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import subprocess
import time

HERE = Path(__file__).resolve().parent
PATCH = 'hyprland-0.56.2-edr.patch'

CONFIG = '''\
-- Physical EDR test session, written by session.py stage. For the patched
-- Hyprland 0.56.2 only: stock Hyprland rejects cm = "edr". It starts no desktop
-- services and does not read or change the desktop configuration.
local pattern = @PATTERN@
local guide = @GUIDE@

-- The desktop's monitor rules, then the EDR profile. DP-1, the panel's second
-- tile, gets the same catch-all rule as on the desktop: never disable it.
hl.monitor({ output = "", mode = "preferred", position = "auto", scale = "auto" })
dofile(@EDR@)

hl.config({
  input = {
    kb_layout = @LAYOUT@,
    kb_variant = @VARIANT@,
    kb_options = "compose:caps,shift:both_capslock_cancel",
    repeat_rate = 40,
    repeat_delay = 250,
    numlock_by_default = true,
  },
  general = { gaps_in = 4, gaps_out = 8, border_size = 0 },
  decoration = { rounding = 0, shadow = { enabled = false } },
  animations = { enabled = false },
  misc = {
    disable_hyprland_logo = true,
    disable_splash_rendering = true,
    background_color = "rgb(202020)",
    disable_autoreload = true,
    key_press_enables_dpms = true,
    mouse_move_enables_dpms = true,
  },
  xwayland = { enabled = false },
  ecosystem = { no_update_news = true, no_donation_nag = true },
  debug = { disable_logs = false, enable_stdout_logs = true },
})

local function bind(keys, description, action)
  hl.bind(keys, action, { description = description })
end

-- One pattern at a time: a new one replaces any that are open. The pattern
-- itself closes on any key but a modifier.
local function patterns(...)
  local commands = { ... }
  return function()
    for _, window in ipairs(hl.get_windows({ class = "imac-edr-pattern" })) do
      hl.dispatch(hl.dsp.window.close({ window = window }))
    end
    for _, command in ipairs(commands) do
      hl.exec_cmd(command[1], command[2])
    end
  end
end

local half = "monitor_w monitor_h*0.5"
bind("SUPER + 1", "HDR test pattern", patterns({ pattern .. " --fullscreen" }))
bind("SUPER + 2", "SDR comparison", patterns({ pattern .. " --fullscreen --sdr" }))
bind("SUPER + 3", "1000-nit HDR pattern", patterns({ pattern .. " --fullscreen --peak 1000" }))
bind("SUPER + 4", "HDR above SDR", patterns(
  { pattern, { float = true, size = half, move = "0 0" } },
  { pattern .. " --sdr", { float = true, size = half, move = "0 monitor_h*0.5" } }))
bind("SUPER + RETURN", "Terminal", hl.dsp.exec_cmd("foot"))
bind("SUPER + H", "Test guide", hl.dsp.exec_cmd(guide))
bind("SUPER + W", "Close window", hl.dsp.window.close())
bind("SUPER + F", "Full screen", hl.dsp.window.fullscreen({ mode = "fullscreen" }))
-- The recovery that restored a stretched panel before: off, three seconds, on.
-- Any key event wakes the display, so switch off after these keys are released.
bind("SUPER + D", "Display off and on", function()
  hl.timer(function()
    hl.dispatch(hl.dsp.dpms({ action = "off" }))
    hl.timer(function() hl.dispatch(hl.dsp.dpms({ action = "on" })) end, { timeout = 3000, type = "oneshot" })
  end, { timeout = 500, type = "oneshot" })
end)
bind("CTRL + ALT + BACKSPACE", "End the test session", hl.dsp.exit())
bind("SUPER + ESCAPE", "End the test session", hl.dsp.exit())

hl.on("hyprland.start", function() hl.exec_cmd(guide) end)
'''

GUIDE = '''\
iMac EDR test: patched Hyprland 0.56.2 with cm = "edr"
{state}

Esc closes a test pattern. Super+Escape or Ctrl+Alt+Backspace ends the test,
which also ends by itself at {deadline}. Ctrl+Alt+F1 switches to your desktop.

Test patterns (a new one replaces the last)
  Super+1  HDR: bars up to about 500 nits
  Super+2  the same bars in SDR
  Super+3  HDR with 1,000-nit content, tone-mapped
  Super+4  HDR above, SDR below

What to look for
  - Seven bars from black, then a ramp. In HDR the three right-hand bars
    are brighter than bar 4, desktop white; in SDR bars 4 to 7 match.
    Bars 1 to 4 look the same in HDR and SDR.
  - A smooth ramp without banding. Both halves of the screen match: no
    seam, no stretched or dark half.
  - Desktop white, like this text, is dimmer than on your desktop: 200 of
    an estimated 500 nits, leaving headroom for the highlights.
  - A normal pointer. It is drawn in software here.

Other keys
  Super+Return  terminal    Super+F  full screen    Super+H  this guide
  Super+D       display off for 3 s: can recover a stretched or dark half
'''

START = '''\
The EDR test takes over the display until it ends. In it:
  Esc                 closes a test pattern
  Super+Escape        ends the test and returns here (as does Ctrl+Alt+Backspace)
  Ctrl+Alt+F1         switches to your desktop
  Super+1 to Super+4  show the test patterns; the on-screen guide lists every key
It ends by itself after {minutes} minutes.
Press Enter to start, or Ctrl+C to cancel: '''

STAGED = '''\
Staged the test session in {session}.

To test on the iMac's display:
  1. Press Ctrl+Alt+F3 (add Fn if F3 is a media key on your keyboard).
  2. Log in, then run:
       {start}
  3. Follow the guide in the terminal that opens. Esc closes a test pattern.
  4. Super+Escape or Ctrl+Alt+Backspace ends the test; the console prints a summary.
  5. Type exit, then press Ctrl+Alt+F1 to return to your desktop.
The desktop keeps running meanwhile and will probably lock itself. The test
ends after 20 minutes (--minutes changes that). To end it from any terminal:
  {start} --stop
'''

NOT_CONSOLE = '''\
Run this from a text console, not from a desktop or remote session:
press Ctrl+Alt+F3, log in, then run this command again.'''


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def lua(value):
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'


def home(path):
    path = str(path)
    return '~' + path[len(str(Path.home())):] if path.startswith(str(Path.home()) + '/') else path


def console_layout():
    # The same source as Omarchy's own keyboard defaults.
    values = {}
    try:
        for line in Path('/etc/vconsole.conf').read_text().splitlines():
            key, _, value = line.partition('=')
            values[key.strip()] = value.strip().strip('"\'')
    except OSError:
        pass
    return values.get('XKBLAYOUT') or 'us', values.get('XKBVARIANT', '')


def stage(directory):
    if not (HERE / PATCH).is_file():
        raise ValueError('Stage from the repository copy of session.py')
    from demo import build
    work = directory.expanduser().resolve()
    binary = work / 'build/Hyprland'
    try:
        recorded = json.loads((work / 'source.json').read_text())['patch_sha256']
    except (OSError, ValueError, KeyError):
        recorded = None
    if not binary.is_file() or recorded is None:
        raise ValueError(f'{work}: no completed build.py build')
    if recorded != digest(HERE / PATCH):
        raise ValueError(f'{work} was built from another patch version; build the current one')
    for tool in ('foot', 'hyprctl', 'systemd-inhibit', 'journalctl'):
        if not shutil.which(tool):
            raise ValueError(f'{tool} is required')
    session = work / 'session'
    session.mkdir(exist_ok=True)
    pattern = build(session / 'pattern')
    shutil.copy2(HERE / 'edr.lua', session / 'edr.lua')
    shutil.copy2(Path(__file__).resolve(), session / 'session.py')
    layout, variant = console_layout()
    guide = f"foot --title='iMac EDR test' python3 {shlex.quote(str(session / 'session.py'))} guide"
    config = session / 'hyprland.lua'
    config.write_text(CONFIG.replace('@PATTERN@', lua(f'{shlex.quote(str(pattern))} --seconds 3600'))
                      .replace('@GUIDE@', lua(guide)).replace('@EDR@', lua(str(session / 'edr.lua')))
                      .replace('@LAYOUT@', lua(layout)).replace('@VARIANT@', lua(variant)))
    env = dict(os.environ, HYPRLAND_NO_SD_VARS='1', HYPRLAND_NO_SD_NOTIFY='1')
    env.pop('HYPRLAND_INSTANCE_SIGNATURE', None)
    check = subprocess.run([str(binary), '--verify-config', '-c', str(config)], env=env,
                           stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30)
    if check.returncode or 'config ok' not in check.stdout:
        raise ValueError(f'The session configuration does not verify:\n{check.stdout[-3000:]}')
    start = work / 'start'
    start.write_text('#!/bin/sh\nexec python3 "$(dirname "$(readlink -f "$0")")/session/session.py" run "$@"\n')
    start.chmod(0o755)
    print(STAGED.format(session=home(session), start=home(start)))


def running(binary):
    try:
        pid = int((HERE / 'running.pid').read_text())
        if Path(f'/proc/{pid}/exe').resolve() == binary.resolve():
            return pid
    except (OSError, ValueError):
        pass
    return None


def stop(binary):
    pid = running(binary)
    if pid is None:
        print('No EDR test session is running.')
        return
    os.kill(pid, signal.SIGTERM)
    print(f'Asked the EDR test compositor (PID {pid}) to exit.')


def end(process, grace):
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=grace)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def describe(monitors):
    panel = next((m for m in monitors if m.get('name') == 'eDP-1' and not m.get('disabled')), None)
    if panel is None:
        return ['WARNING: the built-in display, eDP-1, is not active.']
    form = panel.get('currentFormat', 'unknown format')
    lines = [f"eDP-1: {panel['width']}x{panel['height']} at {panel['refreshRate']:.2f} Hz, "
             f"scale {panel['scale']:g}, {form}",
             f"colour mode {panel.get('colorManagementPreset')}, "
             f"desktop white {panel.get('sdrMaxLuminance', 0):g} estimated nits"]
    if panel.get('colorManagementPreset') != 'edr':
        lines.append('WARNING: EDR is not active on eDP-1.')
    if '2101010' not in form and '16161616' not in form:
        lines.append('WARNING: 8-bit output; expect more banding in the ramp.')
    if panel.get('hardwareCursorsInUse'):
        lines.append('WARNING: the hardware cursor bypasses EDR.')
    if 'CM' not in panel.get('directScanoutBlockedBy', []):
        lines.append('WARNING: direct scanout is not blocked for EDR.')
    if any(m.get('name') == 'DP-1' and not m.get('disabled') for m in monitors):
        lines.append('WARNING: DP-1, the second tile, is enabled as its own output.')
    return lines


def probe():
    deadline = time.monotonic() + 5
    while True:
        try:
            monitors = json.loads(subprocess.check_output(['hyprctl', '-j', 'monitors', 'all'], timeout=5))
        except (OSError, ValueError, subprocess.SubprocessError):
            monitors = []
        if any(m.get('name') == 'eDP-1' and m.get('width') for m in monitors) or time.monotonic() > deadline:
            return monitors
        time.sleep(0.2)


def guide():
    monitors = probe()
    record = Path(os.environ.get('IMAC_EDR_RUN') or '/nonexistent')
    if record.is_dir():
        name = f'monitors-{time.strftime("%H%M%S")}.json' if (record / 'monitors.json').exists() else 'monitors.json'
        (record / name).write_text(json.dumps(monitors, indent=2) + '\n')
    print(GUIDE.format(state='\n'.join(describe(monitors)), deadline=os.environ.get('IMAC_EDR_DEADLINE', '?')))
    shell = os.environ.get('SHELL') or '/bin/sh'
    os.execvp(shell, [shell])


def interrupted(signum, frame):
    raise KeyboardInterrupt


def run(minutes):
    binary = HERE.parent / 'build/Hyprland'
    config = HERE / 'hyprland.lua'
    if not config.is_file() or not binary.is_file():
        raise ValueError('Run the staged session: BUILD_DIRECTORY/start')
    try:
        console = os.ttyname(0)
    except OSError:
        console = ''
    if os.environ.get('WAYLAND_DISPLAY') or os.environ.get('DISPLAY') or not re.fullmatch(r'/dev/tty[1-9][0-9]*', console):
        raise ValueError(NOT_CONSOLE)
    if os.getuid() == 0:
        raise ValueError('Run this as your own user, not root')
    if running(binary) is not None:
        raise ValueError('An EDR test session is already running; end it with --stop')
    try:
        input(START.format(minutes=minutes))
    except (EOFError, KeyboardInterrupt):
        print('\nCancelled.')
        return 1
    record = HERE / 'runs' / time.strftime('%Y%m%d-%H%M%S')
    record.mkdir(parents=True)
    began = time.time()
    deadline = time.strftime('%H:%M', time.localtime(began + minutes * 60))
    env = dict(os.environ, HYPRLAND_NO_SD_VARS='1', HYPRLAND_NO_SD_NOTIFY='1', XCURSOR_SIZE='24',
               HYPRCURSOR_SIZE='24', IMAC_EDR_RUN=str(record), IMAC_EDR_DEADLINE=deadline)
    for key in ('NOTIFY_SOCKET', 'HYPRLAND_INSTANCE_SIGNATURE'):
        env.pop(key, None)
    if Path('/dev/dri/amd-card').exists():
        env['AQ_DRM_DEVICES'] = '/dev/dri/amd-card'  # As imac-gpu.lua does for the desktop.
    print(f'Starting the EDR test on {console}; it ends by {deadline}.', flush=True)
    for signum in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(signum, interrupted)
    timed_out = False
    # Suspend with this compositor is untested; the lock ends when its pipe closes.
    inhibitor = subprocess.Popen(['systemd-inhibit', '--what=sleep', '--mode=block', '--who=iMac EDR test',
                                  '--why=Experimental compositor on the display', 'cat'],
                                 stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        with (record / 'hyprland.log').open('wb') as log:
            compositor = subprocess.Popen([str(binary), '-c', str(config)], env=env, stdin=subprocess.DEVNULL,
                                          stdout=log, stderr=subprocess.STDOUT)
        try:
            (HERE / 'running.pid').write_text(f'{compositor.pid}\n')
            compositor.wait(timeout=minutes * 60)
        except subprocess.TimeoutExpired:
            timed_out = True
        except KeyboardInterrupt:
            pass
        finally:
            end(compositor, 15)
            (HERE / 'running.pid').unlink(missing_ok=True)
    finally:
        inhibitor.stdin.close()
        end(inhibitor, 5)
    elapsed = time.time() - began
    try:
        kernel = subprocess.run(['journalctl', '-k', '-o', 'short-precise', '--no-pager', f'--since=@{int(began)}'],
                                capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        kernel = ''
    (record / 'kernel.log').write_text(kernel)
    cache = Path(os.environ.get('XDG_CACHE_HOME') or Path.home() / '.cache')
    report = cache / 'hyprland' / f'hyprlandCrashReport{compositor.pid}.txt'
    if report.is_file():
        shutil.copy2(report, record / 'crash-report.txt')
        outcome = 'crashed'
    elif timed_out:
        outcome = f'reached its {minutes}-minute limit'
    elif compositor.returncode == 0:
        outcome = 'ended normally'
    else:
        outcome = f'ended with status {compositor.returncode}'
    print(f'\nThe EDR test {outcome} after {int(elapsed // 60)} min {int(elapsed % 60)} s.')
    if report.is_file():
        print('Hyprland wrote a crash report: crash-report.txt in the logs below.')
    try:
        state = describe(json.loads((record / 'monitors.json').read_text()))
        print('Recorded at the start:\n  ' + '\n  '.join(state))
    except (OSError, ValueError):
        print('The display state was not recorded: the guide terminal did not start.')
    errors = [line for line in kernel.splitlines() if 'amdgpu' in line and re.search(r'(?i)error|fail|timed? ?out', line)]
    if errors:
        print(f'The kernel logged {len(errors)} amdgpu error lines; see kernel.log.')
    print(f'Logs: {home(record)}\nType exit to log out, then press Ctrl+Alt+F1 for your desktop.')
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest='command', required=True)
    staging = commands.add_parser('stage', help='write a session next to a build (from the repository)')
    staging.add_argument('directory', type=Path)
    session = commands.add_parser('run', help='run the staged session (from a text console)')
    session.add_argument('--minutes', type=int, default=20, help='time limit, 1..120 (default 20)')
    session.add_argument('--stop', action='store_true', help='end a running test session')
    commands.add_parser('guide', help='print the guide inside the test session')
    args = parser.parse_args()
    if args.command == 'run' and not 1 <= args.minutes <= 120:
        parser.error('--minutes must be 1..120')
    try:
        if args.command == 'stage':
            stage(args.directory)
        elif args.command == 'guide':
            guide()
        elif args.stop:
            stop(HERE.parent / 'build/Hyprland')
        else:
            return run(args.minutes)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        parser.exit(1, f'{error}\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
