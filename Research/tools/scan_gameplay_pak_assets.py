#!/usr/bin/env python3
"""Statically scan gameplay Unreal assets directly from a local SoD2 PAK set.

The scanner only writes derived path/string metadata. It never extracts or
redistributes asset payloads and never starts or attaches to the game process.
The caller supplies the installed PAK folder and the local u4pak.py parser.
"""

from __future__ import annotations

import argparse
import bisect
import importlib.util
import json
import re
import sys
import zlib
from collections import Counter
from pathlib import Path


ASCII_RUN = re.compile(rb"[\x20-\x7e]{4,}")
WIDE_ASCII_RUN = re.compile(rb"(?=((?:[\x20-\x7e]\x00){4,}))")
NAME_LIKE = re.compile(r"[A-Za-z0-9_ .:/<>-]{4,96}\Z")
DEFAULT_PREFIXES = (
    "GameSystems", "UI", "AI", "Missions", "Blueprints", "LegacyArcs",
    "RadioRoom", "Community", "MissionSettings", "AmbientMissions",
    "DemoMissions", "EnclaveArcs", "EnclaveMissions", "ExtremeEnclaves",
    "FactionMissions", "HeartlandMissions", "MissionEvents", "MissionObjectives",
    "PersonalArcs", "StarterScenarioArcs", "Story", "StoryUMG", "TutorialMissions",
    "DLC2_DaybreakStorySettings", "DLC3_HardMode_StorySettings", "DemoStorySettings",
    "GreenZone_StorySettings", "HeartlandStorySettings", "SharedStorySettings",
    "EnclaveAssets", "MissionCastingCollectionInterface", "StoryDirectorAsset",
)
DEFAULT_TERMS = (
    r"(?i)(population|capacity|recruit|enlist|invite|summon|character.?count|"
    r"community.?member|survivor.?pool|player.?enclave|communityscreen|"
    r"legacy|exil|transfer|can.?add.?character|disabled.*cap|cap)"
)


def lz4_block_decompress(source: bytes) -> bytes:
    """Decode a raw LZ4 block (the framing-less form stored by these PAKs)."""
    output = bytearray()
    position = 0
    length = len(source)
    while position < length:
        token = source[position]
        position += 1
        literal_length = token >> 4
        if literal_length == 15:
            while True:
                if position >= length:
                    raise ValueError("truncated LZ4 literal length")
                extra = source[position]
                position += 1
                literal_length += extra
                if extra != 255:
                    break
        literal_end = position + literal_length
        if literal_end > length:
            raise ValueError("truncated LZ4 literals")
        output.extend(source[position:literal_end])
        position = literal_end
        if position == length:
            break
        if position + 2 > length:
            raise ValueError("truncated LZ4 match offset")
        distance = source[position] | (source[position + 1] << 8)
        position += 2
        if distance == 0 or distance > len(output):
            raise ValueError("invalid LZ4 match offset")
        match_length = (token & 0x0F) + 4
        if (token & 0x0F) == 15:
            while True:
                if position >= length:
                    raise ValueError("truncated LZ4 match length")
                extra = source[position]
                position += 1
                match_length += extra
                if extra != 255:
                    break
        for _ in range(match_length):
            output.append(output[-distance])
    return bytes(output)


def asset_strings(data: bytes):
    """Yield unique ASCII and ASCII-range UTF-16LE strings from package bytes."""
    seen = set()
    ascii_matches = list(ASCII_RUN.finditer(data))
    ascii_spans = [(match.start(), match.end()) for match in ascii_matches]
    ascii_starts = [start for start, _end in ascii_spans]
    for match in ascii_matches:
        value = match.group().decode("ascii")
        if value not in seen:
            seen.add(value)
            yield value
    wide_end = -1
    for match in WIDE_ASCII_RUN.finditer(data):
        span_index = bisect.bisect_right(ascii_starts, match.start()) - 1
        if span_index >= 0 and match.start() < ascii_spans[span_index][1]:
            continue
        if match.start() < wide_end:
            continue
        value = match.group(1).decode("utf-16le")
        wide_end = match.start() + len(match.group(1))
        if value not in seen:
            seen.add(value)
            yield value


def is_name_like(value: str) -> bool:
    """Keep short identifiers/labels and discard prose or binary noise."""
    return bool(NAME_LIKE.fullmatch(value)) and len(value.split()) <= 5


def path_is_selected(path: str, prefixes) -> bool:
    normalized = path.replace("/", "\\").casefold()
    return any(
        normalized.startswith(prefix.casefold() + "\\")
        or normalized == (prefix + ".uasset").casefold()
        for prefix in prefixes
    )


def asset_path_selected(path: str, prefixes, path_regex=None) -> bool:
    """Select by full asset path regex when supplied, otherwise by root prefix."""
    if path_regex is not None:
        return bool(path_regex.search(path))
    return path_is_selected(path, prefixes)


def extract_record(stream, record) -> bytes:
    if record.encrypted:
        raise ValueError("encrypted record")
    method = record.compression_method & 0xFF
    if method == 0:
        stream.seek(record.data_offset)
        data = stream.read(record.uncompressed_size)
    else:
        if not record.compression_blocks:
            raise ValueError("compressed record has no block table")
        blocks = []
        for start, end in record.compression_blocks:
            stream.seek(start)
            source = stream.read(end - start)
            if len(source) != end - start:
                raise ValueError("truncated compressed block")
            if method == 1:
                blocks.append(zlib.decompress(source))
            elif method == 3:
                blocks.append(lz4_block_decompress(source))
            else:
                raise ValueError("unsupported compression method %d" % method)
        data = b"".join(blocks)
    if len(data) != record.uncompressed_size:
        raise ValueError(
            "size mismatch: got %d, expected %d" % (len(data), record.uncompressed_size)
        )
    return data


def load_u4pak(module_path: Path):
    spec = importlib.util.spec_from_file_location("sod2_static_u4pak", module_path)
    if spec is None or spec.loader is None:
        raise ImportError("cannot load u4pak module: %s" % module_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def scan(pak_root: Path, parser_path: Path, prefixes, term_regex: str, path_regex: str | None = None):
    u4pak = load_u4pak(parser_path)
    terms = re.compile(term_regex)
    paths = re.compile(path_regex) if path_regex else None
    pak_files = sorted(pak_root.glob("*.pak"))
    if not pak_files:
        raise FileNotFoundError("no .pak files found in %s" % pak_root)

    selected = []
    pak_counts = Counter()
    compression_counts = Counter()
    total_selected_uassets = 0
    for pak_path in pak_files:
        with pak_path.open("rb") as stream:
            pak = u4pak.read_index(stream, force_version=3)
            for record in pak.records:
                path = record.filename.replace("/", "\\")
                if not path.lower().endswith(".uasset"):
                    continue
                if not asset_path_selected(path, prefixes, paths):
                    continue
                total_selected_uassets += 1
                pak_counts[pak_path.name] += 1
                compression_counts[str(record.compression_method & 0xFF)] += 1
                selected.append((pak_path, record))

    findings = []
    errors = []
    bytes_scanned = 0
    for pak_path, record in selected:
        try:
            with pak_path.open("rb") as stream:
                data = extract_record(stream, record)
            bytes_scanned += len(data)
            matches = sorted(
                {
                    value
                    for value in asset_strings(data)
                    if terms.search(value) and is_name_like(value)
                },
                key=str.casefold,
            )
            if matches:
                findings.append(
                    {
                        "pak": pak_path.name,
                        "asset": record.filename.replace("\\", "/"),
                        "uncompressed_size": record.uncompressed_size,
                        "symbols": matches,
                    }
                )
        except (OSError, ValueError, zlib.error) as error:
            errors.append({"pak": pak_path.name, "asset": record.filename, "error": str(error)})

    return {
        "schema": 1,
        "method": "offline PAK index and selected cooked .uasset string scan",
        "scope": "name-like ASCII and ASCII-range UTF-16LE strings only; not a Blueprint/UAsset parser",
        "prefixes": list(prefixes) if paths is None else [],
        "path_regex": path_regex,
        "terms_regex": term_regex,
        "pak_count": len(pak_files),
        "selected_uasset_count": total_selected_uassets,
        "scanned_uasset_count": len(selected) - len(errors),
        "scanned_uncompressed_bytes": bytes_scanned,
        "compression_method_counts": dict(sorted(compression_counts.items())),
        "selected_assets_by_pak": dict(sorted(pak_counts.items())),
        "matched_asset_count": len(findings),
        "errors": errors,
        "findings": sorted(findings, key=lambda row: (row["asset"].casefold(), row["pak"])),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pak-root", required=True, type=Path, help="installed Content/Paks directory")
    parser.add_argument("--u4pak-module", type=Path, help="path to u4pak.py; defaults to the sibling research-tool checkout")
    parser.add_argument("--output", required=True, type=Path, help="derived JSON report output path")
    parser.add_argument("--prefix", action="append", help="asset root to include; may be repeated")
    parser.add_argument("--path-regex", help="scan .uasset files matching this path regex instead of root prefixes")
    parser.add_argument("--terms", default=DEFAULT_TERMS, help="regex for identifier-like strings to retain")
    args = parser.parse_args(argv)
    parser_path = args.u4pak_module or Path(__file__).resolve().parents[3] / "u4pak" / "u4pak.py"
    prefixes = tuple(args.prefix or DEFAULT_PREFIXES)
    try:
        report = scan(args.pak_root, parser_path, prefixes, args.terms, args.path_regex)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    except (OSError, ImportError, ValueError) as error:
        print("ERROR: %s" % error, file=sys.stderr)
        return 1
    print(
        "scanned %d/%d .uasset records in %d PAKs; %d assets had matching symbol-like strings; %d errors"
        % (
            report["scanned_uasset_count"], report["selected_uasset_count"], report["pak_count"],
            report["matched_asset_count"], len(report["errors"]),
        )
    )
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
