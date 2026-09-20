#!/usr/bin/env python3
"""make-bcl-table.py -- give Linux the iMac18,3 panel's full brightness range.

Apple's SSDT "PEG0GFX0" holds the ACPI brightness table `_BCL` (named ABCL)
with levels 1..80, while the firmware's own setter BSET(level) scales
655 * level onto the backlight controller's 0..0xFFFF range. Linux's 100% is
therefore BSET(80) = 52400 -- 80% of what macOS drives (0..65535, 500 nits),
which is the "Boot Camp is dimmer" gap iMac owners report.

This reads the machine's own table, rewrites only ABCL to levels 4..100 (below
4 is under macOS's usable floor, ~2176 raw), bumps the OEM revision so the
kernel prefers the upgrade, and compiles it for mkinitcpio's acpi_override
hook. Apple's table never leaves the machine: nothing here is redistributed.

Nothing on the kernel command line can switch an initramfs ACPI override off,
so a bad table is the one failure in macOS mode with no boot-time escape. Two
checks stand in the way of writing one:

  * the disassembled table must have exactly the shape this firmware is known
    to have (ABCL = 80 levels starting at 0x50), and
  * iasl must round-trip the untouched table back to the firmware's own bytes,
    proving the disassembler/compiler pair is faithful on it before a modified
    table built the same way is trusted.

Either check failing exits 4, which the patcher treats as "keep the firmware's
80 levels" rather than an error: brightness still works in macOS mode, just not
above ~400 nits.

    sudo scripts/make-bcl-table.py [--force] [out.aml]

--force writes the table even when the round-trip check fails. Needs root (the
ACPI tables are root-only) and iasl from acpica.
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# The name mkinitcpio's acpi_override hook picks up. Anything under
# kernel/firmware/acpi/ in the early cpio must stay below 18 bytes
# (lib/earlycpio.c, MAX_CPIO_FILE_NAME), which "imac-bcl100.aml" does.
DEFAULT_OUT = Path("/etc/initcpio/acpi_override/imac-bcl100.aml")
TABLES = Path("/sys/firmware/acpi/tables")
MARKER = "PEG0GFX0"
# The two leading _BCL entries are "level on AC" and "level on battery"; the
# rest is the level list the kernel exposes as 0..max_brightness.
STOCK_FIRST, STOCK_COUNT = "0x50", 0x52
LEVELS = list(range(4, 101))
# Bytes an iasl recompile is allowed to change: the checksum, and the creator
# ID and revision it stamps in place of Apple's.
IGNORED_FIELDS = ((9, 10), (28, 36))

DEFBLOCK = re.compile(r'("%s", )0x([0-9A-Fa-f]{8})\)' % MARKER)
ABCL = re.compile(
    r"(Method \(ABCL, 0, NotSerialized\)\s*\{\s*Return \(Package \()"
    r"0x[0-9A-Fa-f]+(\)\s*\{)(.*?)(\}\))", re.S)


def abcl_entries(dsl):
    """The ABCL package's entries, or None when the method is not there."""
    match = ABCL.search(dsl)
    if not match:
        return None
    return [v.strip() for v in match[3].replace("\n", " ").split(",") if v.strip()]


def is_upgraded(dsl):
    """True when this table already carries the levels this script writes."""
    entries = abcl_entries(dsl)
    return entries is not None and entries[0] == "0x64" and len(entries) == 2 + len(LEVELS)


def is_stock(dsl):
    """True when the table has the shape the iMac18,3 firmware is known to have."""
    entries = abcl_entries(dsl)
    return entries is not None and entries[0] == STOCK_FIRST and len(entries) == STOCK_COUNT


def bump_oem_revision(dsl):
    """Raise the OEM revision by one, so the kernel prefers this table."""
    out, n = DEFBLOCK.subn(
        lambda m: "%s0x%08X)" % (m[1], int(m[2], 16) + 1), dsl, count=1)
    if n != 1:
        raise ValueError("DefinitionBlock header for %s not found" % MARKER)
    return out


def rewrite_abcl(dsl, levels=LEVELS):
    """Replace only the ABCL package, keeping every other method untouched."""
    match = ABCL.search(dsl)
    if not match:
        raise ValueError("ABCL not found")
    body = ",\n                    ".join(
        ["0x64", "0x32"] + ["0x%02X" % level for level in levels])
    package = (match[1] + "0x%02X" % (2 + len(levels)) + match[2]
               + "\n                    " + body + "\n                " + match[4])
    return dsl[:match.start()] + package + dsl[match.end():]


def comparable(aml):
    """The table with the fields a recompile legitimately rewrites masked out."""
    blob = bytearray(aml)
    for start, end in IGNORED_FIELDS:
        blob[start:end] = b"\0" * (end - start)
    return bytes(blob)


def differing_offsets(original, rebuilt):
    """Offsets where two tables differ, ignoring checksum and creator fields."""
    left, right = comparable(original), comparable(rebuilt)
    if len(left) != len(right):
        return None            # a length change is not a per-byte difference
    return [i for i, (a, b) in enumerate(zip(left, right)) if a != b]


def run(cmd, **kwargs):
    return subprocess.run(cmd, capture_output=True, text=True, **kwargs)


def disassemble(work, table, others):
    """Disassemble one table with the rest of the namespace for externals."""
    result = run(["iasl", "-e", *others, "-d", str(table)], cwd=work)
    dsl = table.with_suffix(".dsl")
    if not dsl.exists():
        sys.exit("iasl could not disassemble %s:\n%s" % (table.name, result.stdout))
    return dsl


def compile_table(work, dsl, prefix):
    result = run(["iasl", "-p", prefix, str(dsl)], cwd=work)
    out = Path(work) / (prefix + ".aml")
    if not out.exists():
        errors = "\n".join(l for l in result.stdout.splitlines() if l.startswith("Error"))
        sys.exit("iasl could not compile %s:\n%s" % (dsl.name, errors or result.stdout))
    return out


def main():
    parser = argparse.ArgumentParser(description="Build the full-range ACPI brightness table.")
    parser.add_argument("out", nargs="?", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--force", action="store_true",
                        help="write the table even if iasl does not round-trip the original")
    args = parser.parse_args()

    if os.geteuid() != 0:
        sys.exit("run with sudo: the ACPI tables under %s are root-only" % TABLES)
    if not shutil.which("iasl"):
        sys.exit("iasl is missing (install acpica)")

    with tempfile.TemporaryDirectory() as work:
        # Copy out of sysfs: iasl needs regular files it can read repeatedly.
        names = []
        for src in [TABLES / "DSDT"] + sorted(TABLES.glob("SSDT*")):
            if not src.is_file():
                continue
            dest = Path(work) / (src.name + ".dat")
            dest.write_bytes(src.read_bytes())
            names.append(dest)
        target = next((p for p in names if MARKER.encode() in p.read_bytes()), None)
        if target is None:
            sys.exit("no %s table on this machine -- this is not the firmware "
                     "this script was written for" % MARKER)
        others = [p.name for p in names if p != target]

        original = target.read_bytes()
        dsl = disassemble(work, target, others)
        text = dsl.read_text()

        if is_upgraded(text):
            # Booted with the override already in place: the loaded table is
            # exactly what this script would produce, so ship it unchanged.
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_bytes(original)
            args.out.chmod(0o644)
            print("wrote %s (%d bytes): copied the table this boot already runs"
                  % (args.out, len(original)))
            return 0
        if not is_stock(text):
            entries = abcl_entries(text)
            print("ABCL is not the table this script knows (first entry %s, %s entries; "
                  "expected %s and %d). Leaving the firmware's range alone."
                  % (entries[0] if entries else "absent",
                     len(entries) if entries else 0, STOCK_FIRST, STOCK_COUNT),
                  file=sys.stderr)
            return 4

        # Round-trip the untouched table first: if iasl cannot reproduce the
        # firmware's own bytes, its output for the modified one is not trusted.
        rebuilt = compile_table(work, dsl, "roundtrip").read_bytes()
        drift = differing_offsets(original, rebuilt)
        if drift is None or drift:
            detail = ("length %d vs %d" % (len(original), len(rebuilt)) if drift is None
                      else "%d bytes differ, first at offset 0x%X" % (len(drift), drift[0]))
            print("iasl did not round-trip this firmware's table (%s)." % detail, file=sys.stderr)
            if not args.force:
                print("Leaving the firmware's range alone; pass --force to override.",
                      file=sys.stderr)
                return 4
            print("--force given: continuing on an unverified round-trip.", file=sys.stderr)
        else:
            print("iasl round-trips this table byte for byte")

        upgraded = rewrite_abcl(bump_oem_revision(text))
        dsl.write_text(upgraded)
        built = compile_table(work, dsl, "out")

        # Read the result back through the disassembler: what gets installed is
        # checked as a table, not merely as the text that was compiled.
        check_dir = Path(work) / "verify"
        check_dir.mkdir()
        check = check_dir / "out.dat"
        check.write_bytes(built.read_bytes())
        for name in others:
            (check_dir / name).write_bytes((Path(work) / name).read_bytes())
        if not is_upgraded(disassemble(str(check_dir), check, others).read_text()):
            sys.exit("the compiled table does not read back with the new levels")

        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_bytes(built.read_bytes())
        args.out.chmod(0o644)
        print("wrote %s (%d bytes): ABCL levels %d..%d"
              % (args.out, args.out.stat().st_size, LEVELS[0], LEVELS[-1]))
        return 0


if __name__ == "__main__":
    sys.exit(main())
