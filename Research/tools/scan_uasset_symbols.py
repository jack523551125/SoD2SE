#!/usr/bin/env python3
"""List readable symbol-like strings from caller-supplied cooked Unreal assets.

This is a lightweight static triage helper. It does not parse a full package,
resolve imports, recover a WidgetTree, or prove that a symbol is callable.
"""

import argparse
import bisect
import re
import sys
from pathlib import Path


ASCII_STRINGS = re.compile(rb"[\x20-\x7e]{4,}")
UTF16_ASCII_STRINGS = re.compile(rb"(?=((?:[\x20-\x7e]\x00){4,}))")


def scan(path, pattern, minimum):
    data = path.read_bytes()
    candidates = set()
    ascii_matches = list(ASCII_STRINGS.finditer(data))
    ascii_spans = [(match.start(), match.end()) for match in ascii_matches]
    ascii_starts = [start for start, _end in ascii_spans]
    for match in ascii_matches:
        value = match.group().decode("ascii")
        if len(value) >= minimum:
            candidates.add(value)
    wide_end = -1
    for match in UTF16_ASCII_STRINGS.finditer(data):
        start = match.start()
        value_bytes = match.group(1)
        # A byte-oriented UTF-16 regex can start at the final ASCII character
        # and consume that string's NUL terminator as the first wide NUL byte.
        span_index = bisect.bisect_right(ascii_starts, start) - 1
        if span_index >= 0 and start < ascii_spans[span_index][1]:
            continue
        if start < wide_end:
            continue
        wide_end = start + len(value_bytes)
        value = value_bytes.decode("utf-16le")
        if len(value) >= minimum:
            candidates.add(value)
    return sorted(value for value in candidates if pattern.search(value))


def expand_assets(inputs):
    assets = []
    missing = []
    for item in inputs:
        if not item.exists():
            missing.append(item)
        elif item.is_dir():
            assets.extend(sorted(item.rglob("*.uasset")))
        elif item.is_file():
            assets.append(item)
        else:
            missing.append(item)
    return sorted(dict.fromkeys(assets)), missing


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("assets", nargs="+", type=Path, help="cooked .uasset files or directories to inspect")
    parser.add_argument(
        "--pattern",
        default=r"(?i)(CharacterUI|CommunityUI|Attached(Character|Community)|SelectedCharacter|CharacterOverlay|Skills?|CloseCharacterUI|RefreshHints)",
        help="regular expression used to filter extracted strings",
    )
    parser.add_argument("--min-length", type=int, default=4)
    args = parser.parse_args(argv)
    if args.min_length < 1:
        parser.error("--min-length must be positive")
    try:
        pattern = re.compile(args.pattern)
    except re.error as error:
        parser.error("invalid --pattern: %s" % error)

    assets, missing = expand_assets(args.assets)
    failed = bool(missing)
    for item in missing:
        print("ERROR: asset or directory not found: %s" % item, file=sys.stderr)
    if not assets:
        print("ERROR: no .uasset files were selected", file=sys.stderr)
        return 1
    matched_files = 0
    for asset in assets:
        try:
            values = scan(asset, pattern, args.min_length)
        except OSError as error:
            print("ERROR: cannot read %s: %s" % (asset, error), file=sys.stderr)
            failed = True
            continue
        if values:
            matched_files += 1
            print("[%s] %d matching strings" % (asset.name, len(values)))
            for value in values:
                print("  " + value)
    print("scanned %d asset file(s); %d matched the symbol pattern" % (len(assets), matched_files))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
