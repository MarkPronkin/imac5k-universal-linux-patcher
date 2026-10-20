#!/usr/bin/env python3
"""Build, install and check imac-patcher's HDR (EDR) desktop for Hyprland.

apply builds Hyprland 0.56.2 with the EDR patch from checksum-pinned sources
under ~/.cache/imac-patcher/hdr and installs it, with a launcher and a wrapper
configuration, in ~/.local/share/imac-patcher/hdr. A user-level
hyprland.desktop then shadows the system entry that uwsm starts at login.
Before every start the launcher runs `check`, and it starts the stock
compositor instead whenever the build no longer matches the installed
Hyprland. Nothing outside the user's home directory is written.
"""
import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request

HERE = Path(__file__).resolve().parent
PATCH = HERE.parent / 'patches/hyprland-0.56.2-edr.patch'
MODEL = 'iMac18,3'
VERSION = '0.56.2'
COMMIT = 'efb50993780079460b0cbed1363e2166a2de1d9f'
# Hyprland submodule commits are from that commit's Git tree. Glaze is the
# version pinned by its CMakeLists.txt. No branch heads or moving dependencies.
SOURCES = {
    'hyprland': ('https://codeload.github.com/hyprwm/Hyprland/tar.gz/refs/tags/v0.56.2',
                 'ddeb92a654fa65d41ed2add3176de4fe54eab3752441c33ca99f5e598e0571e5'),
    'protocols': ('https://codeload.github.com/hyprwm/hyprland-protocols/tar.gz/bd153e76f751f150a09328dbdeb5e4fab9d23622',
                  'f31112800ec83ec529d0d35699a3d20fa0ed3cbb97d344146340815fec5ac055'),
    'udis86': ('https://codeload.github.com/canihavesomecoffee/udis86/tar.gz/5336633af70f3917760a6d441ff02d93477b0c86',
               '2f459fafa19535ef1be417bf7614e4f92475e5787d7ba76df20287cc29d1b5a9'),
    'glaze': ('https://codeload.github.com/stephenberry/glaze/tar.gz/refs/tags/v7.2.0',
              '17dba19ae63ae48f94994f00d49d5cb3c8f1306db1046c534c4828662490b7d4'),
}
STOCK_START = '/usr/bin/start-hyprland'
STOCK_BINARY = '/usr/bin/Hyprland'
PANEL = 'eDP-1'
MARKER = 'X-iMac-Patcher-HDR'
# The Hyprland libraries change ABI between their own releases; a different
# version of any of them means rebuilding. Every other library need only resolve.
ABI_LIBRARIES = re.compile(r'lib(?:aquamarine|hypr[a-z]*)\.so[.0-9]*')
CMAKE_MINIMUM = (3, 30)
BUILD_TOOLS = ('cmake', 'g++', 'make', 'patch', 'pkg-config')
# Characters a desktop entry's Exec key would need quoted or escaped.
UNSAFE_EXEC = re.compile(r'[\s"\'\\><~|&;$*?#()`%]')

# For the patched build only: stock Hyprland rejects cm = "edr". The user's
# configuration runs unchanged; hl.monitor is wrapped first, so every rule for
# the built-in panel keeps the user's own fields and gains the EDR profile.
CONFIG = '''\
-- Written by imac-patcher for module hdr; imac-patcher --remove hdr removes it.
-- Loaded only by the patched Hyprland @VERSION@ it installed: stock Hyprland
-- rejects cm = "edr". Your own configuration runs unchanged, except that every
-- rule for the built-in display, eDP-1, also gets the EDR profile below. Set
-- sdr_max_luminance (desktop white) or max_luminance (the panel's peak) on
-- your own eDP-1 rule to replace these estimates; they are not measurements.
local panel = "eDP-1"
local forced = { cm = "edr", bitdepth = 10, supports_hdr = -1 }
local defaults = { max_luminance = 500, sdr_max_luminance = 200 }

local function edr(rule)
  local result = {}
  for key, value in pairs(rule) do result[key] = value end
  for key, value in pairs(defaults) do
    if result[key] == nil then result[key] = value end
  end
  for key, value in pairs(forced) do result[key] = value end
  result.output = panel
  return result
end

local monitor = hl.monitor
local seen, fallback = false, nil
hl.monitor = function(rule, ...)
  if type(rule) == "table" then
    if rule.output == panel then
      seen = true
      return monitor(edr(rule), ...)
    elseif rule.output == nil or rule.output == "" then
      fallback = rule
    end
  end
  return monitor(rule, ...)
end

-- Relative modules resolve from your configuration directory, as without this
-- file; requiring by path keeps your hyprland.lua under automatic reload.
package.path = @USERDIR@ .. "/?.lua;" .. @USERDIR@ .. "/?/init.lua;" .. package.path
require(@USER@)

-- Without a rule of its own the panel follows the catch-all, so start from it.
if not seen then
  hl.monitor(edr(fallback or { mode = "preferred", position = "auto", scale = "auto" }))
end
'''

# uwsm runs this as the session's main process, for every login.
LAUNCH = '''\
#!/bin/bash
# Written by imac-patcher for module hdr; imac-patcher --remove hdr removes it.
# uwsm starts this for hyprland.desktop: the patched Hyprland with EDR on the
# built-in display, or the stock compositor whenever the build no longer
# matches the installed Hyprland, with a notification saying why.
here=@HERE@
if ! problem=$(timeout 20 python3 "$here/hypr-edr.py" check 2>&1); then
    problem=${problem##*$'\\n'}
    message="This login uses the stock compositor: ${problem:-the check of the HDR build failed}."
    setsid -f sh -c 'sleep 20; exec notify-send --app-name=imac-patcher --urgency=critical "HDR is off" "$1"' \\
        sh "$message" >/dev/null 2>&1
    exec @STOCK@ "$@"
fi
exec @STOCK@ --path "$here/Hyprland" -- --config "$here/hyprland.lua" "$@"
'''

# Keys as in Hyprland's own entry. No TryExec: uwsm fails the login on an
# entry that TryExec discards instead of falling back to the system one.
ENTRY = '''\
[Desktop Entry]
Name=Hyprland
Comment=Hyprland with HDR (EDR) on the built-in display, from imac-patcher; imac-patcher --remove hdr removes this entry
Exec=@LAUNCH@
Type=Application
DesktopNames=Hyprland
Keywords=tiling;wayland;compositor;
@MARKER@=1
'''


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def lua(value):
    return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"') + '"'


def home(path):
    path = str(path)
    return '~' + path[len(str(Path.home())):] if path.startswith(str(Path.home()) + '/') else path


def xdg(variable, default):
    value = os.environ.get(variable, '')
    return Path(value) if value.startswith('/') else Path.home() / default


def atomic_write(path, data, mode=0o644):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f'.{path.name}.', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb' if isinstance(data, bytes) else 'w') as stream:
            os.fchmod(stream.fileno(), mode)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


# ── build ───────────────────────────────────────────────────────────────────

def archive(name, cache):
    url, expected = SOURCES[name]
    path = cache / f'{name}.tar.gz'
    if not path.exists():
        print(f'Downloading {name}...', flush=True)
        fd, temporary = tempfile.mkstemp(prefix=f'.{name}-', dir=cache)
        try:
            with os.fdopen(fd, 'wb') as output, urllib.request.urlopen(url, timeout=120) as response:
                shutil.copyfileobj(response, output)
            if digest(temporary) != expected:
                raise ValueError(f'{name}: downloaded archive checksum mismatch')
            os.replace(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)
    if digest(path) != expected:
        raise ValueError(f'{path}: archive checksum mismatch; not extracting')
    return path


def extract(path, directory):
    directory.mkdir(parents=True, exist_ok=True)
    with tarfile.open(path) as source:
        for original in source:
            parts = Path(original.name).parts
            if original.name.startswith('/') or '..' in parts:
                raise ValueError('Unexpected archive path')
            if len(parts) < 2:
                continue
            member = copy.copy(original)
            member.name = str(Path(*parts[1:]))
            source.extract(member, directory, filter='data')


def prepare(work, cache):
    marker = work / 'source.json'
    expected = {'commit': COMMIT, 'patch_sha256': digest(PATCH), 'sources': SOURCES}
    expected = json.loads(json.dumps(expected))
    if marker.exists():
        if json.loads(marker.read_text()) != expected:
            raise ValueError('This directory contains another patch version; use a new work directory')
        return work / 'source'
    source = work / 'source'
    if source.exists():
        raise ValueError('An unrecorded source directory exists; use a new work directory')
    downloaded = {name: archive(name, cache) for name in SOURCES}
    extract(downloaded['hyprland'], source)
    extract(downloaded['protocols'], source / 'subprojects/hyprland-protocols')
    extract(downloaded['udis86'], source / 'subprojects/udis86')
    extract(downloaded['glaze'], work / 'glaze')
    subprocess.run(['patch', '--batch', '--forward', '--fuzz=0', '-p1', '-i', str(PATCH)], cwd=source, check=True)
    marker.write_text(json.dumps(expected, indent=2) + '\n')
    return source


def logged(command, log, **options):
    """Run a build step with its output on the terminal and in the log."""
    if log is None:
        subprocess.run(command, check=True, **options)
        return
    with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                          errors='replace', **options) as process:
        for line in process.stdout:
            sys.stdout.write(line)
            log.write(line)
    if process.returncode:
        raise subprocess.CalledProcessError(process.returncode, command)


def build(work, cache, jobs=4, cmake='cmake', prepare_only=False, log=None):
    """Patch and build the compositor in WORK; return the executable's path."""
    work.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)
    source = prepare(work, cache)
    if prepare_only:
        return source
    env = dict(os.environ, GIT_COMMIT_HASH=COMMIT, GIT_BRANCH='imac-edr', GIT_DIRTY='dirty', GIT_TAG='v0.56.2-imac-edr')
    logged([
        cmake, '-S', str(source), '-B', str(work / 'build'), '-DCMAKE_BUILD_TYPE=Release',
        '-DNO_HYPRPM=ON', '-DNO_UWSM=ON', '-DCMAKE_DISABLE_FIND_PACKAGE_Git=ON',
        f'-DFETCHCONTENT_SOURCE_DIR_GLAZE={work / "glaze"}', '-DFETCHCONTENT_FULLY_DISCONNECTED=ON',
        f'-DCMAKE_INSTALL_PREFIX={work / "install"}',
    ], log, env=env)
    logged([cmake, '--build', str(work / 'build'), '--target', 'Hyprland', '-j', str(jobs)], log, env=env)
    return work / 'build/Hyprland'


def default_jobs():
    # Hyprland's C++26 units take up to about 2 GiB each to compile.
    try:
        kib = next(int(line.split()[1]) for line in Path('/proc/meminfo').read_text().splitlines()
                   if line.startswith('MemTotal:'))
    except (OSError, StopIteration, ValueError):
        kib = 0
    return max(1, min(os.cpu_count() or 1, kib // (2 * 1024 * 1024) or 1))


def cmake_version(cmake='cmake'):
    try:
        output = subprocess.run([cmake, '--version'], capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    match = re.search(r'version (\d+)\.(\d+)', output)
    return (int(match[1]), int(match[2])) if match else None


# ── the installed build ─────────────────────────────────────────────────────

def stock_version(binary=STOCK_BINARY):
    try:
        output = subprocess.run([binary, '--version'], capture_output=True, text=True, timeout=20,
                                stdin=subprocess.DEVNULL).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    match = re.match(r'Hyprland (\S+)', output)
    return match[1] if match else None


def linked(binary):
    """Return ({soname: real path} for every resolved library, [missing sonames])."""
    result = subprocess.run(['ldd', str(binary)], capture_output=True, text=True, timeout=20)
    if result.returncode:
        raise OSError(f'ldd {binary} failed: {result.stderr.strip()}')
    resolved, missing = {}, []
    for line in result.stdout.splitlines():
        name, arrow, target = line.strip().partition(' => ')
        if not arrow:
            continue
        target = target.rsplit(' (', 1)[0].strip()
        if target == 'not found':
            missing.append(name)
        else:
            resolved[name] = os.path.realpath(target)
    return resolved, missing


def abi(resolved):
    return {name: path for name, path in sorted(resolved.items()) if ABI_LIBRARIES.fullmatch(name)}


def render_config(user_config):
    return (CONFIG.replace('@VERSION@', VERSION).replace('@USERDIR@', lua(user_config.parent))
            .replace('@USER@', lua(user_config)))


def render_launch(root, stock=STOCK_START):
    return LAUNCH.replace('@HERE@', shlex.quote(str(root))).replace('@STOCK@', shlex.quote(stock))


def render_entry(launch):
    return ENTRY.replace('@LAUNCH@', str(launch)).replace('@MARKER@', MARKER)


class Desktop:
    def __init__(self, data_home=None, config_home=None, cache_home=None):
        data = Path(data_home) if data_home else xdg('XDG_DATA_HOME', '.local/share')
        config = Path(config_home) if config_home else xdg('XDG_CONFIG_HOME', '.config')
        cache = Path(cache_home) if cache_home else xdg('XDG_CACHE_HOME', '.cache')
        self.root = data / 'imac-patcher/hdr'
        self.entry = data / 'wayland-sessions/hyprland.desktop'
        self.user_config = config / 'hypr/hyprland.lua'
        self.cache = cache / 'imac-patcher/hdr'
        self.binary = self.root / 'Hyprland'
        self.config = self.root / 'hyprland.lua'
        self.launch = self.root / 'launch'
        self.helper = self.root / 'hypr-edr.py'
        self.record = self.root / 'build.json'

    def owned_entry(self):
        try:
            return any(line.startswith(MARKER + '=') for line in self.entry.read_text().splitlines())
        except (OSError, UnicodeDecodeError):
            return False

    def installed(self):
        files = [path for path in (self.binary, self.config, self.launch, self.helper, self.record)
                 if path.exists() or path.is_symlink()]
        return files + ([self.entry] if self.owned_entry() else [])

    def scripts(self):
        """The files apply writes besides the binary and its record."""
        return {self.config: (render_config(self.user_config), 0o644),
                self.launch: (render_launch(self.root), 0o755),
                self.helper: (Path(__file__).read_text(), 0o644)}

    def read_record(self):
        try:
            record = json.loads(self.record.read_text())
        except (OSError, ValueError):
            return None
        return record if isinstance(record, dict) else None

    def check(self, stock=None):
        """Why a login must not start the build, as messages; empty when it may."""
        if not (self.binary.is_file() and os.access(self.binary, os.X_OK) and self.config.is_file()):
            return ['the HDR build is incomplete; run imac-patcher --apply hdr']
        record = self.read_record()
        if record is None:
            return ['the record of the HDR build is missing; run imac-patcher --apply hdr']
        stock = stock_version() if stock is None else stock
        if stock != record.get('version'):
            return [f'the system Hyprland is {stock or "missing"} but the HDR build is {record.get("version")}; '
                    'HDR returns once imac-patcher supports that version and hdr is applied again']
        resolved, missing = linked(self.binary)
        if missing:
            return [f'{", ".join(missing)} is missing for the HDR build; run imac-patcher --apply hdr']
        if abi(resolved) != record.get('libraries'):
            return ["Hyprland's libraries were updated since the HDR build; run imac-patcher --apply hdr to rebuild it"]
        return []

    def problems(self):
        """Every reason the module is not fully applied, for the status note."""
        found = []
        if self.entry.exists() and not self.owned_entry():
            found.append(f'{home(self.entry)} is not imac-patcher\'s; logins never start the HDR build')
        elif not self.owned_entry():
            found.append('the session entry is missing; logins start the stock compositor')
        for path, (text, _) in self.scripts().items():
            try:
                if path.read_text() != text:
                    found.append(f'{home(path)} is from another imac-patcher release; apply hdr again')
            except (OSError, UnicodeDecodeError):
                found.append(f'{home(path)} is missing')
        record = self.read_record()
        if record is not None and record.get('patch_sha256') != digest(PATCH):
            found.append('the HDR build is from an earlier patch; apply hdr again to rebuild it')
        try:
            found += self.check()
        except (OSError, subprocess.SubprocessError) as error:
            found.append(str(error))
        return list(dict.fromkeys(found))

    def platform_problems(self):
        found = []
        if not self.user_config.is_file():
            found.append(f'{home(self.user_config)} is missing: HDR needs a Lua Hyprland configuration')
        if not Path(STOCK_START).is_file():
            found.append(f'{STOCK_START} is missing: HDR needs Hyprland 0.56 or newer')
        if not shutil.which('uwsm'):
            found.append('uwsm is missing: HDR is started through the uwsm session entry, as on Omarchy')
        return found

    def state(self, model):
        installed = self.installed()
        if model != MODEL or self.platform_problems():
            # Keep an install removable wherever it could not be applied today.
            return 'partial' if installed else 'n/a'
        if not installed:
            return 'not-applied'
        return 'partial' if self.problems() else 'applied'

    # ── apply ───────────────────────────────────────────────────────────────

    def preflight(self, model):
        if model != MODEL:
            raise ValueError(f'HDR (EDR) is built for the iMac18,3 panel only; this is {model}')
        if os.getuid() == 0:
            raise ValueError('Apply hdr as your desktop user, not root')
        found = self.platform_problems()
        if found:
            raise ValueError('\n'.join(found))
        stock = stock_version()
        if stock != VERSION:
            raise ValueError(f'The EDR patch is for Hyprland {VERSION}; this system has {stock or "no working Hyprland"}')
        if self.entry.exists() and not self.owned_entry():
            raise ValueError(f'{self.entry} is your own session entry; move it away to use hdr')
        if UNSAFE_EXEC.search(str(self.launch)):
            raise ValueError(f'{self.launch}: a session entry cannot start a path with these characters')

    def reusable(self):
        record = self.read_record()
        if record is None or record.get('patch_sha256') != digest(PATCH):
            return False
        try:
            return not self.check()
        except (OSError, subprocess.SubprocessError):
            return False

    def compile(self, jobs):
        missing = [tool for tool in BUILD_TOOLS if not shutil.which(tool)]
        if missing:
            raise ValueError(f'Building HDR needs {", ".join(missing)}')
        version = cmake_version()
        if version is None or version < CMAKE_MINIMUM:
            raise ValueError(f'Building HDR needs CMake {".".join(map(str, CMAKE_MINIMUM))} or newer')
        work = self.cache / digest(PATCH)[:12]
        print(f'Building the patched Hyprland {VERSION} in {home(work)} with {jobs} jobs.\n'
              'This takes about ten minutes; the full log goes to '
              f'{home(self.cache / "build.log")}.', flush=True)
        self.cache.mkdir(parents=True, exist_ok=True)
        with (self.cache / 'build.log').open('w') as log:
            binary = build(work, self.cache / 'downloads', jobs=jobs, log=log)
        version = subprocess.run([str(binary), '--version'], capture_output=True, text=True, timeout=20,
                                 stdin=subprocess.DEVNULL).stdout
        if f'Hyprland {VERSION}' not in version or 'imac-edr' not in version:
            raise ValueError(f'{binary} is not the patched build:\n{version}')
        return work, binary

    def verify(self, binary, text):
        """Run the wrapper configuration, with the user's, through the build."""
        fd, temporary = tempfile.mkstemp(prefix='.hyprland.', suffix='.lua', dir=self.root)
        try:
            with os.fdopen(fd, 'w') as stream:
                stream.write(text)
            env = dict(os.environ)
            env.pop('HYPRLAND_INSTANCE_SIGNATURE', None)
            result = subprocess.run([str(binary), '--verify-config', '-c', temporary], env=env,
                                    stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60)
        finally:
            Path(temporary).unlink(missing_ok=True)
        if result.returncode or 'config ok' not in result.stdout:
            raise ValueError('Your Hyprland configuration does not verify with the HDR build:\n'
                             + (result.stdout + result.stderr)[-3000:])

    def apply(self, model, jobs=None):
        self.preflight(model)
        self.root.mkdir(parents=True, exist_ok=True)
        work = None
        if self.reusable():
            print('The installed HDR build matches this release and Hyprland; not rebuilding.')
            binary = self.binary
        else:
            work, binary = self.compile(jobs or default_jobs())
        resolved, missing = linked(binary)
        if missing:
            raise ValueError(f'{binary} cannot load {", ".join(missing)}')
        scripts = self.scripts()
        self.verify(binary, scripts[self.config][0])
        previous = self.read_record() if work is None else None
        if work is not None:
            atomic_write(self.binary, binary.read_bytes(), 0o755)
        record = {'version': VERSION, 'commit': COMMIT, 'patch_sha256': digest(PATCH), 'libraries': abi(resolved),
                  'built': (previous or {}).get('built') or datetime.now(timezone.utc).isoformat(timespec='seconds')}
        atomic_write(self.record, json.dumps(record, indent=2) + '\n')
        for path, (text, mode) in scripts.items():
            atomic_write(path, text, mode)
        # Last, so that a login can only find the entry once everything it starts is in place.
        atomic_write(self.entry, render_entry(self.launch))
        if work is not None:
            shutil.rmtree(work, ignore_errors=True)  # The verified downloads stay for a rebuild.
        print(APPLIED.format(entry=home(self.entry)))

    def remove(self):
        if self.entry.exists() and not self.owned_entry():
            print(f'{home(self.entry)} is not imac-patcher\'s; left alone.', file=sys.stderr)
        elif self.owned_entry():
            self.entry.unlink()
        for path in (self.binary, self.config, self.launch, self.helper, self.record):
            path.unlink(missing_ok=True)
        if self.root.is_dir():
            for leftover in self.root.glob('.*'):
                leftover.unlink(missing_ok=True)
            for directory in (self.root, self.root.parent):
                try:
                    directory.rmdir()
                except OSError:
                    break
        shutil.rmtree(self.cache, ignore_errors=True)
        print('HDR removed: the next login starts the stock compositor. A running HDR session keeps going until you log out.')

    def note(self, model):
        state = self.state(model)
        if state == 'partial':
            if model != MODEL or self.platform_problems():
                return ['hdr: installed where it cannot run; imac-patcher --remove hdr takes it out']
            return [f'hdr: {problem}' for problem in self.problems()]
        if state != 'applied':
            return []
        running = compositor()
        if running is None:
            return []
        if running != self.binary.resolve():
            return ['hdr takes effect at your next login']
        panel = next((m for m in monitors() if m.get('name') == PANEL), None)
        if panel is not None and panel.get('colorManagementPreset') != 'edr':
            return [f'hdr: the HDR build is running but {PANEL} is not in EDR mode; check your monitor rules']
        return []


APPLIED = '''\
HDR installed. It starts at your next login: log out (Omarchy menu, System,
Log out) and back in, or restart.
  Desktop white is an estimated 200 of the panel's 500 nits, leaving the rest
  for HDR highlights, so ordinary windows look dimmer than before: keep the
  brightness at maximum.
  Every login checks the build first and starts the stock compositor, with a
  notification, if Hyprland has been upgraded since.
  To go back: imac-patcher --remove hdr, also from a text console, or delete
  {entry}.'''


def monitors():
    try:
        return json.loads(subprocess.check_output(['hyprctl', '-j', 'monitors', 'all'], timeout=5,
                                                  stderr=subprocess.DEVNULL))
    except (OSError, ValueError, subprocess.SubprocessError):
        return []


def compositor():
    """The executable of the Hyprland instance this shell belongs to, if any."""
    try:
        instances = json.loads(subprocess.check_output(['hyprctl', '-j', 'instances'], timeout=5,
                                                       stderr=subprocess.DEVNULL))
        signature = os.environ.get('HYPRLAND_INSTANCE_SIGNATURE')
        pid = next((i['pid'] for i in instances if i.get('instance') == signature), instances[0]['pid'])
        return Path(f'/proc/{pid}/exe').resolve()
    except (OSError, ValueError, LookupError, TypeError, subprocess.SubprocessError):
        return None


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('command', choices=('status', 'note', 'apply', 'remove', 'check'))
    parser.add_argument('--model', default='')
    parser.add_argument('--jobs', type=int)
    args = parser.parse_args()
    if args.jobs is not None and not 1 <= args.jobs <= 64:
        parser.error('--jobs must be 1..64')
    desktop = Desktop()
    try:
        if args.command == 'status':
            print(desktop.state(args.model))
        elif args.command == 'note':
            for line in desktop.note(args.model):
                print(f'  {line}')
        elif args.command == 'check':
            problems = desktop.check()
            if problems:
                print(problems[0])
                return 1
        elif args.command == 'apply':
            desktop.apply(args.model, args.jobs)
        else:
            desktop.remove()
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
