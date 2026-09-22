#!/usr/bin/env python3
"""Build the pinned EDR compositor in a separate directory; never install it."""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request

HERE = Path(__file__).resolve().parent
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


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


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
    patch = HERE / 'hyprland-0.56.2-edr.patch'
    marker = work / 'source.json'
    expected = {'commit': COMMIT, 'patch_sha256': digest(patch), 'sources': SOURCES}
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
    subprocess.run(['patch', '--batch', '--forward', '--fuzz=0', '-p1', '-i', str(patch)], cwd=source, check=True)
    marker.write_text(json.dumps(expected, indent=2) + '\n')
    return source


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
    work.mkdir(parents=True, exist_ok=True)
    cache = args.cache.expanduser().resolve() if args.cache else work / 'downloads'
    cache.mkdir(parents=True, exist_ok=True)
    try:
        source = prepare(work, cache)
        if args.prepare_only:
            print(f'Patched source: {source}')
            return 0
        env = dict(os.environ, GIT_COMMIT_HASH=COMMIT, GIT_BRANCH='imac-edr', GIT_DIRTY='dirty', GIT_TAG='v0.56.2-imac-edr')
        subprocess.run([
            args.cmake, '-S', str(source), '-B', str(work / 'build'), '-DCMAKE_BUILD_TYPE=Release',
            '-DNO_HYPRPM=ON', '-DNO_UWSM=ON', '-DCMAKE_DISABLE_FIND_PACKAGE_Git=ON',
            f'-DFETCHCONTENT_SOURCE_DIR_GLAZE={work / "glaze"}', '-DFETCHCONTENT_FULLY_DISCONNECTED=ON',
            f'-DCMAKE_INSTALL_PREFIX={work / "install"}',
        ], check=True, env=env)
        subprocess.run([args.cmake, '--build', str(work / 'build'), '--target', 'Hyprland', '-j', str(args.jobs)], check=True, env=env)
        print(f'Built: {work / "build/Hyprland"}')
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, f'{error}\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
