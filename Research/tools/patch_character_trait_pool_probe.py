#!/usr/bin/env python3
"""Fixed-build, one-byte Character Iggy experiment; never edits a UAsset or game install."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from analyze_iggy_script_api import extract_abc_block, make_swf_wrapper
from inspect_iggy_movie import inspect_iggy


PINNED_IGGY_SHA256 = "d134758ed784ac6beb64cc8494acc315b1f30591541fecaacdf3532109fb188d"
PINNED_ABC_SHA256 = "143f089353e5ed0504db2dd8d2c59eb318c037228275dd203ce5486b4c421800"
CONSTRUCTOR_CONTEXT = bytes.fromhex("24 04 74 d7 d0 60 da 17 60 c2 06 53 01 d3 42 01 68 c1 06")
OLD_CAPACITY = 4
NEW_CAPACITY = 6
FFDEC_VERSION = "v.26.3.0"


def find_unique(data: bytes, pattern: bytes) -> int:
    if not pattern:
        raise ValueError("Patch pattern cannot be empty")
    first = data.find(pattern)
    if first < 0 or data.find(pattern, first + 1) >= 0:
        raise ValueError("Expected exactly one guarded ActionScript instruction sequence")
    return first


def _extract_movie_abc(payload: bytes, source_name: str) -> tuple[bytes, dict[str, Any], dict[str, Any]]:
    movie = inspect_iggy(payload, source_name=source_name)
    movie_start = movie["subfiles"][movie["movie_subfile_index"]]["offset"]
    pointers = {row["name"]: row for row in movie["movie_header_relative_pointers"]}
    declaration = pointers.get("declaration_strings", {}).get("target_movie_offset")
    names = pointers.get("names", {}).get("target_movie_offset")
    if declaration is None or names is None:
        raise ValueError("Pinned Character movie lacks bounded ABC pointers")
    abc, layout = extract_abc_block(
        payload,
        section_offset=movie_start + declaration,
        section_end=movie_start + names,
    )
    return abc, layout, movie


def patch_payload(payload: bytes, *, source_name: str, ffdec_cli: Path) -> tuple[bytes, dict[str, Any]]:
    source_hash = hashlib.sha256(payload).hexdigest()
    if source_hash != PINNED_IGGY_SHA256:
        raise ValueError(f"Only the pinned build 16535856 Character movie is accepted; got {source_hash}")
    abc, layout, before_movie = _extract_movie_abc(payload, source_name)
    if hashlib.sha256(abc).hexdigest() != PINNED_ABC_SHA256:
        raise ValueError("Pinned Character ActionScript bytecode hash mismatch")
    pattern_offset = find_unique(abc, CONSTRUCTOR_CONTEXT)
    immediate_offset = pattern_offset + 1
    if abc[immediate_offset] != OLD_CAPACITY:
        raise ValueError("The guarded trait-pool immediate is not the expected value 4")

    patched = bytearray(payload)
    absolute_offset = layout["abc_offset"] + immediate_offset
    patched[absolute_offset] = NEW_CAPACITY
    patched_bytes = bytes(patched)
    changed_offsets = [index for index, (old, new) in enumerate(zip(payload, patched_bytes)) if old != new]
    if changed_offsets != [absolute_offset] or len(payload) != len(patched_bytes):
        raise ValueError("Probe changed bytes outside the one guarded immediate")

    new_abc, new_layout, after_movie = _extract_movie_abc(patched_bytes, source_name + ".probe")
    if new_abc[immediate_offset] != NEW_CAPACITY or len(new_abc) != len(abc):
        raise ValueError("Reparsed ABC did not preserve its size or contain the requested capacity")
    if new_layout != layout or after_movie["movie_subfile_size"] != before_movie["movie_subfile_size"]:
        raise ValueError("Same-length script edit unexpectedly changed the Iggy movie layout")
    indexes = after_movie.get("index_subfiles", [])
    if not indexes or any(row.get("bytes_consumed") != row.get("size") for row in indexes):
        raise ValueError("Reparsed Iggy index subfile has incomplete byte coverage")
    if indexes[-1].get("final_cumulative_offset") != after_movie["movie_subfile_size"]:
        raise ValueError("Final Iggy index stream no longer terminates at the movie boundary")

    cli_version = subprocess.run(
        [str(ffdec_cli), "-help"], capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    if cli_version.returncode != 0 or FFDEC_VERSION not in cli_version.stdout + cli_version.stderr:
        raise ValueError("Expected JPEXS FFDec 26.3.0 for bytecode verification")
    with tempfile.TemporaryDirectory(prefix="sod2-character-trait-probe-") as temp_name:
        temp = Path(temp_name)
        wrapper = temp / "character.swf"
        export_dir = temp / "export"
        wrapper.write_bytes(make_swf_wrapper(new_abc))
        result = subprocess.run(
            [str(ffdec_cli), "-export", "script", str(export_dir), str(wrapper)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode != 0 or "Export finished." not in result.stdout + result.stderr:
            raise ValueError("FFDec could not parse patched ABC")
        script = (export_dir / "scripts" / "traits_behavior.as").read_text(encoding="utf-8")
        if "var _loc3_:uint = 6;" not in script:
            raise ValueError("FFDec did not recover the expected six-entry trait pool")

    report = {
        "schema": 1,
        "target_build": 16535856,
        "asset": "Art/UI/character.uasset",
        "source_uasset_sha256": "941e57905b698214e7e962a613e486ef512eaa0a48ba09f40abbf1522f58cd70",
        "source_iggy_sha256": source_hash,
        "source_abc_sha256": PINNED_ABC_SHA256,
        "output_iggy_sha256": hashlib.sha256(patched_bytes).hexdigest(),
        "output_abc_sha256": hashlib.sha256(new_abc).hexdigest(),
        "movie_size_unchanged": True,
        "index_stream_ends_at_movie_boundary": True,
        "output_loaded_in_game": False,
        "patch": {
            "method": "single guarded AVM2 pushbyte immediate rewrite; no source recompilation",
            "abc_guard_offset": pattern_offset,
            "payload_absolute_offset": absolute_offset,
            "old_value": OLD_CAPACITY,
            "new_value": NEW_CAPACITY,
            "changed_byte_count": len(changed_offsets),
            "ffdec_decompile_confirms_new_capacity": True,
        },
        "scope": "This tool emits local extracted Iggy bytes only. A separate pinned Unreal package write-back test is recorded in native-ui-screen-adapters.json; neither result was loaded in game.",
        "limitations": [
            "The probe only changes the preallocated trait/description widget count from 4 to 6; it does not prove additional entries fit or render correctly in the original layout.",
            "The ActionScript public methods still require a verified native call path and the correct currently selected character.",
            "No arbitrary component registration, focus/navigation support, input handling, language integration, or cleanup contract is established.",
            "This script does not package its output; separate package write-back passed, but game loading and runtime layout still need validation.",
        ],
    }
    return patched_bytes, report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="Pinned local character.iggy payload")
    parser.add_argument("--output", type=Path, required=True, help="New path for the offline probe result")
    parser.add_argument("--ffdec-cli", type=Path, required=True, help="JPEXS FFDec 26.3.0 CLI")
    parser.add_argument("--report", type=Path, required=True, help="Metadata-only JSON report")
    args = parser.parse_args()
    source = args.input.resolve()
    output = args.output.resolve()
    if source == output:
        parser.error("Input and output must be different files")
    if output.exists():
        parser.error("Output already exists; choose a new path so earlier work is not overwritten")
    try:
        patched, report = patch_payload(source.read_bytes(), source_name=source.name, ffdec_cli=args.ffdec_cli.resolve())
    except (OSError, ValueError) as error:
        parser.error(str(error))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(patched)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("PASS: one-byte Character Iggy trait-pool probe; movie layout and index streams unchanged")
    print(f"Output: {output}")
    print(f"Metadata report: {args.report.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
