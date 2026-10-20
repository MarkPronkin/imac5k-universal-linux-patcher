#!/usr/bin/env python3
"""Run the patched compositor as the real desktop, for one login.

`arm BUILD_DIRECTORY` runs from the repository. It writes the EDR desktop next
to a build.py build: the owner's own Hyprland configuration, unchanged, then
the EDR profile. It then shadows the session entry uwsm starts,
hyprland.desktop, with a user-level one in ~/.local/share/wayland-sessions.
The next login runs the patched compositor; its launcher removes that entry
first, so every login after it is the stock desktop again. Nothing outside
the build directory and that one entry is written.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from session import PATCH, describe, digest, home, lua, probe  # noqa: E402

MARKER = 'X-iMac-EDR'

ENTRY = '''\
[Desktop Entry]
Name=Hyprland (iMac EDR, one login)
Comment=Written by desktop.py arm; its launcher removes this entry when it starts
Exec={launch}
TryExec={launch}
DesktopNames=Hyprland
Type=Application
{marker}={work}
'''

CONFIG = '''\
-- EDR desktop, written by desktop.py arm. For the patched Hyprland 0.56.2 only:
-- stock Hyprland rejects cm = "edr". The owner's configuration runs unchanged,
-- then the EDR profile replaces its eDP-1 rule.
dofile(@USER@)
dofile(@EDR@)

-- The launcher keeps standard output in the run directory.
hl.config({ debug = { disable_logs = false, enable_stdout_logs = true } })
hl.on("hyprland.start", function() hl.exec_cmd(@RECORD@) end)
'''

# uwsm runs this as the session's main process. Removing the entry comes
# first, so a failure anywhere below still leaves the next login stock.
LAUNCH = '''\
#!/bin/bash
# One login into the EDR desktop, written by desktop.py arm.
here=@HERE@
entry=@ENTRY@
grep -qs '^@MARKER@=' "$entry" && rm -f -- "$entry"
binary="$here/../build/Hyprland"
[[ -x $binary && -f $here/hyprland.lua ]] || exec /usr/bin/start-hyprland "$@"
export IMAC_EDR_RUN="$here/runs/$(date +%Y%m%d-%H%M%S)"
mkdir -p -- "$IMAC_EDR_RUN" || exec /usr/bin/start-hyprland "$@"
began=$(date +%s)
# Suspend with this compositor is untested; the lock ends with the session.
systemd-inhibit --what=sleep --mode=block --who='iMac EDR desktop' \\
  --why='Experimental compositor on the display' sleep infinity &
inhibitor=$!
/usr/bin/start-hyprland --path "$binary" -- --config "$here/hyprland.lua" >>"$IMAC_EDR_RUN/hyprland.log" 2>&1 &
child=$!
trap 'kill -TERM "$child" 2>/dev/null' TERM INT HUP
while :; do
  wait "$child"
  status=$?
  kill -0 "$child" 2>/dev/null || break
done
kill "$inhibitor" 2>/dev/null
journalctl -k -o short-precise --no-pager --since="@$began" >"$IMAC_EDR_RUN/kernel.log" 2>&1
find "${XDG_CACHE_HOME:-$HOME/.cache}/hyprland" -maxdepth 1 -name 'hyprlandCrashReport*.txt' \\
  -newermt "@$began" -exec cp -t "$IMAC_EDR_RUN" {} + 2>/dev/null
exit "$status"
'''

ARMED = '''\
Armed: the next login starts the EDR desktop, once.
  {entry}
Log out (Omarchy menu, System, Log out) and log in again, or restart:
the login after that, and every one after, is the stock desktop again.
Sleep is blocked while it runs. To cancel before logging in:
  python3 {script} disarm
'''


def entry_path():
    data = Path(os.environ.get('XDG_DATA_HOME') or Path.home() / '.local/share')
    return data / 'wayland-sessions/hyprland.desktop'


def quote(path):
    return "'" + str(path).replace("'", "'\\''") + "'"


def ours(entry):
    try:
        return any(line.startswith(MARKER + '=') for line in entry.read_text().splitlines())
    except OSError:
        return False


def arm(directory):
    if not (HERE / PATCH).is_file():
        raise ValueError('Arm from the repository copy of desktop.py')
    if os.getuid() == 0:
        raise ValueError('Run this as your own user, not root')
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
    user = Path.home() / '.config/hypr/hyprland.lua'
    if not user.is_file():
        raise ValueError(f'{user} is missing: the EDR desktop runs your own configuration')
    for tool in ('/usr/bin/start-hyprland', 'systemd-inhibit', 'journalctl', 'hyprctl', 'notify-send'):
        if not shutil.which(tool):
            raise ValueError(f'{tool} is required')
    entry = entry_path()
    if entry.exists() and not ours(entry):
        raise ValueError(f'{entry} is your own session entry; it would be replaced')
    desktop = work / 'desktop'
    desktop.mkdir(exist_ok=True)
    for name in ('desktop.py', 'session.py', 'edr.lua'):
        shutil.copy2(HERE / name, desktop / name)
    config = desktop / 'hyprland.lua'
    record = f'python3 {desktop / "desktop.py"} record'
    config.write_text(CONFIG.replace('@USER@', lua(str(user))).replace('@EDR@', lua(str(desktop / 'edr.lua')))
                      .replace('@RECORD@', lua(record)))
    env = dict(os.environ)
    env.pop('HYPRLAND_INSTANCE_SIGNATURE', None)
    check = subprocess.run([str(binary), '--verify-config', '-c', str(config)], env=env,
                           stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60)
    if check.returncode or 'config ok' not in check.stdout:
        raise ValueError(f'The EDR desktop configuration does not verify:\n{check.stdout[-3000:]}')
    launch = desktop / 'launch'
    launch.write_text(LAUNCH.replace('@HERE@', quote(desktop)).replace('@ENTRY@', quote(entry))
                      .replace('@MARKER@', MARKER))
    launch.chmod(0o755)
    entry.parent.mkdir(parents=True, exist_ok=True)
    entry.write_text(ENTRY.format(launch=launch, marker=MARKER, work=work))
    print(ARMED.format(entry=home(entry), script=home(HERE / 'desktop.py')))


def disarm():
    entry = entry_path()
    if not entry.exists():
        print('Not armed: the next login is the stock desktop.')
    elif not ours(entry):
        raise ValueError(f'{entry} was not written by desktop.py; left alone')
    else:
        entry.unlink()
        print('Disarmed: the next login is the stock desktop.')


def compositor():
    try:
        instances = json.loads(subprocess.check_output(['hyprctl', '-j', 'instances'], timeout=5))
        signature = os.environ.get('HYPRLAND_INSTANCE_SIGNATURE')
        pid = next((i['pid'] for i in instances if i.get('instance') == signature), instances[0]['pid'])
        return Path(f'/proc/{pid}/exe').resolve()
    except (OSError, ValueError, LookupError, subprocess.SubprocessError):
        return None


def record():
    run = Path(os.environ.get('IMAC_EDR_RUN') or '/nonexistent')
    monitors = probe()
    state = describe(monitors)
    if run.is_dir():
        (run / 'monitors.json').write_text(json.dumps(monitors, indent=2) + '\n')
        (run / 'state.txt').write_text('\n'.join(state) + '\n')
    time.sleep(5)  # The notification daemon starts with the rest of the desktop.
    warned = any(line.startswith('WARNING') for line in state)
    subprocess.run(['notify-send', '--app-name=iMac EDR', f'--urgency={"critical" if warned else "normal"}',
                    'EDR desktop' + (': check the display state' if warned else ' is on'), '\n'.join(state)],
                   timeout=10, check=False)


def status():
    entry = entry_path()
    print(f'Next login: {"the EDR desktop (armed)" if ours(entry) else "the stock desktop"}')
    binary = compositor()
    patched = binary is not None and binary.parent.name == 'build' and (binary.parent.parent / 'desktop').is_dir()
    print(f'Running compositor: {binary or "none found"}' + (' (patched EDR build)' if patched else ''))
    print('\n'.join(describe(probe())))
    if patched:
        runs = sorted((binary.parent.parent / 'desktop/runs').glob('*'))
        if runs:
            print(f'Logs: {home(runs[-1])}')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest='command', required=True)
    arming = commands.add_parser('arm', help='start the EDR desktop at the next login (from the repository)')
    arming.add_argument('directory', type=Path)
    commands.add_parser('disarm', help='keep the next login stock')
    commands.add_parser('status', help='show what runs now and at the next login')
    commands.add_parser('record', help='record the display state, run by the EDR desktop at start')
    args = parser.parse_args()
    try:
        if args.command == 'arm':
            arm(args.directory)
        elif args.command == 'disarm':
            disarm()
        elif args.command == 'record':
            record()
        else:
            status()
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        parser.exit(1, f'{error}\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
