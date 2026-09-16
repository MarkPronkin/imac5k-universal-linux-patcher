#!/usr/bin/env python3
"""Read and replace individual Limine entries without truncating the config."""
import hashlib
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import time


def sections(text):
    return re.split(r"(?m)(?=^/+[^\n]+)", text)


def title(section):
    return section.split("\n", 1)[0].split(" (", 1)[0]


def field(section, key):
    match = re.search(rf"(?m)^\s*{re.escape(key)}:\s*([^\n]+)", section)
    return match[1].strip() if match else ""


def entry(text, marker):
    matches = [part for part in sections(text) if title(part) == marker]
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one entry {marker}")
    return matches[0]


def update(path, marker, replacement=""):
    path = path.resolve(strict=True)
    original = path.read_text()
    result = "".join(part for part in sections(original) if title(part) != marker)
    result = result.rstrip("\n") + "\n"
    if replacement:
        if title(replacement.lstrip("\n")) != marker:
            raise ValueError("Replacement entry has a different marker")
        result += "\n" + replacement.strip("\n") + "\n"
    if result == original:
        return
    metadata = path.stat()
    backup = path.with_name(f"{path.name}.backup-{time.time_ns()}")
    shutil.copy2(path, backup)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            os.fchmod(stream.fileno(), metadata.st_mode & 0o7777)
            if os.geteuid() == 0:
                os.fchown(stream.fileno(), metadata.st_uid, metadata.st_gid)
            stream.write(result)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def main(argv):
    path, action, *args = argv
    path = Path(path)
    text = path.read_text()
    if action == "replace":
        update(path, args[0], sys.stdin.read())
    elif action == "remove":
        update(path, args[0])
    elif action == "field":
        value = field(entry(text, args[0]), args[1])
        if not value:
            raise ValueError(f"Missing {args[1]} in {args[0]}")
        print(value)
    elif action == "cmdline":
        expected = f"boot():/EFI/Linux/{Path(args[0]).name}"
        matches = [part for part in sections(text)
                   if field(part, "path").split("#", 1)[0] == expected]
        lines = {field(part, "cmdline") for part in matches}
        if len(lines) != 1 or not next(iter(lines), ""):
            raise ValueError(f"Missing or ambiguous cmdline for {expected}")
        print(lines.pop())
    elif action == "verify":
        image = Path(args[1])
        actual = hashlib.blake2b(image.read_bytes()).hexdigest()
        expected = f"boot():/EFI/Linux/{image.name}#{actual}"
        if field(entry(text, args[0]), "path") != expected:
            raise ValueError(f"Entry path/hash does not match {image}")
    elif action == "restore-tests":
        previous, esp, excluded = args
        for part in sections(Path(previous).read_text()):
            marker = title(part)
            if not marker.startswith('/Test - ') or marker == excluded:
                continue
            pinned = field(part, 'path')
            match = re.fullmatch(r'boot\(\):/EFI/Linux/([A-Za-z0-9._-]+\.efi)#([0-9a-f]{128})', pinned)
            if not match:
                raise ValueError(f'Invalid saved image path/hash in {marker}')
            image = Path(esp) / 'EFI/Linux' / match[1]
            if hashlib.blake2b(image.read_bytes()).hexdigest() != match[2]:
                raise ValueError(f'Saved image hash mismatch in {marker}')
            if not field(part, 'cmdline'):
                raise ValueError(f'Missing saved cmdline in {marker}')
            update(path, marker, part)
    else:
        raise ValueError(f"Unknown action: {action}")


if __name__ == "__main__":
    try:
        main(sys.argv[1:])
    except (OSError, ValueError) as error:
        print(error, file=sys.stderr)
        sys.exit(1)
