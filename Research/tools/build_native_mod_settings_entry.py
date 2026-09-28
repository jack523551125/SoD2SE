#!/usr/bin/env python3
"""Build an offline, fixed-build native Mod Settings category experiment.

Only three methods in the original ABC are patched. Display objects and all
original AVM2 binding identities are preserved; source recompilation is forbidden.
The output is not installed and has not been validated by the running game.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import subprocess
import tempfile
import copy
import xml.etree.ElementTree as ET
from pathlib import Path

from analyze_iggy_script_api import (
    PINNED_SETTINGS_SHA256, _run_ffdec_export, extract_abc_block,
    make_swf_wrapper, parse_settings_script,
)
from inspect_iggy_movie import inspect_iggy
from patch_native_entry_bytecode import patch_xml, verify_only_entry_changes


def abc_from_swf(data: bytes) -> bytes:
    """Read uncompressed SWF tags independently of FFDec's compiler."""
    if len(data) < 14 or data[:3] != b"FWS" or struct.unpack_from("<I", data, 4)[0] != len(data):
        raise ValueError("Expected a bounded uncompressed SWF")
    cursor = 8 + (5 + 4 * (data[8] >> 3) + 7) // 8 + 4
    blocks = []
    ended = False
    while cursor + 2 <= len(data):
        tag = struct.unpack_from("<H", data, cursor)[0]
        cursor += 2
        kind, size = tag >> 6, tag & 63
        if size == 63:
            if cursor + 4 > len(data):
                raise ValueError("Truncated SWF long tag")
            size = struct.unpack_from("<I", data, cursor)[0]
            cursor += 4
        end = cursor + size
        if end > len(data):
            raise ValueError("SWF tag exceeds file bounds")
        if kind == 82:
            if size < 9:
                raise ValueError("Truncated DoABC")
            name_end = data.find(b"\0", cursor + 4, end)
            if name_end < 0:
                raise ValueError("Unterminated DoABC name")
            blocks.append(data[name_end + 1:end])
        cursor = end
        if kind == 0:
            ended = size == 0 and cursor == len(data)
            break
    if not ended or len(blocks) != 1:
        raise ValueError("Expected exactly one DoABC and a final End tag")
    return blocks[0]


def abc_from_iggy(data: bytes) -> bytes:
    movie = inspect_iggy(data)
    start = movie["subfiles"][movie["movie_subfile_index"]]["offset"]
    pointers = {p["name"]: p["target_movie_offset"] for p in movie["movie_header_relative_pointers"]}
    return extract_abc_block(data, section_offset=start + pointers["declaration_strings"],
        section_end=start + pointers["names"])[0]


def replace_settings_abc(original: bytes, abc: bytes) -> bytes:
    """Patch only the SHA-pinned movie's ABC, alignment and relocation metadata.

    The second index stream's final raw-span command covers ABC[3:] plus
    alignment. Preserve its custom declaration descriptor and all other commands.
    This deliberately is not a generic Iggy writer.
    """
    if hashlib.sha256(original).hexdigest() != PINNED_SETTINGS_SHA256:
        raise ValueError("Input is not the pinned build 16535856 settings movie")
    if len(abc) < 4 or abc[:4] != b"\x10\x00\x2e\x00":
        raise ValueError("Expected AVM2 ABC version 46.16")
    before = inspect_iggy(original)
    old_abc = abc_from_iggy(original)
    if abc == old_abc:
        return original
    movie_start = 80
    declaration = 7351256
    old_names = 7535672
    abc_start = movie_start + declaration + 12
    padding = (-(declaration + 12 + len(abc))) % 8
    tail_start = movie_start + old_names
    delta = len(abc) + padding - (len(old_abc) + 7)
    if original[abc_start + len(old_abc):tail_start] != b"\0" * 7:
        raise ValueError("Unexpected original ABC padding")
    result = bytearray(original[:abc_start] + abc + b"\0" * padding + original[tail_start:])
    struct.pack_into("<I", result, abc_start - 4, len(abc))
    for pointer in before["movie_header_relative_pointers"]:
        target = pointer["target_movie_offset"]
        if target is not None and target >= old_names:
            struct.pack_into("<Q", result, movie_start + pointer["header_offset"],
                pointer["relative_value"] + delta)
    for index, subfile in enumerate(before["subfiles"]):
        offset = subfile["offset"] + (delta if subfile["offset"] >= tail_start else 0)
        size = subfile["size"] + (delta if subfile["kind"] == 1 else 0)
        size2 = subfile["size2"] + (delta if subfile["kind"] == 1 else 0)
        struct.pack_into("<IIII", result, 32 + 16 * index, subfile["kind"], size, size2, offset)
    index_offset = before["subfiles"][2]["offset"] + delta
    command = index_offset + 5127
    if result[command:command + 5] != b"\xff\x51\xd0\x02\x00":
        raise ValueError("Pinned ABC index-span command mismatch")
    struct.pack_into("<I", result, command + 1, 184401 + delta)
    output = bytes(result)
    after = inspect_iggy(output)
    if abc_from_iggy(output) != abc:
        raise ValueError("ABC did not survive reinsertion")
    if after["index_subfiles"][-1]["final_cumulative_offset"] != after["movie_subfile_size"]:
        raise ValueError("Index stream no longer covers the movie")
    # Normalize exactly the permitted edits; all other bytes must equal original.
    normalized = bytearray(output[:abc_start] + old_abc + b"\0" * 7 + output[tail_start + delta:])
    normalized[:80] = original[:80]
    for offset in (0x70, 0x88):
        normalized[movie_start + offset:movie_start + offset + 8] = original[movie_start + offset:movie_start + offset + 8]
    normalized[abc_start - 4:abc_start] = original[abc_start - 4:abc_start]
    old_command = before["subfiles"][2]["offset"] + 5127
    normalized[old_command:old_command + 5] = original[old_command:old_command + 5]
    if bytes(normalized) != original:
        raise ValueError("Non-target bytes changed")
    return output


def build(iggy: Path, ffdec: Path, output_dir: Path) -> dict:
    data = iggy.read_bytes()
    if hashlib.sha256(data).hexdigest() != PINNED_SETTINGS_SHA256:
        raise ValueError("Settings Iggy input hash mismatch")
    original_abc = abc_from_iggy(data)
    source, class_count = _run_ffdec_export(ffdec, original_abc)
    parse_settings_script(source)
    output_dir.mkdir(parents=True, exist_ok=False)
    with tempfile.TemporaryDirectory(prefix="sod2-mod-settings-entry-") as scratch:
        root = Path(scratch)
        wrapper = root / "original.swf"
        compiled = root / "entry.swf"
        wrapper.write_bytes(make_swf_wrapper(original_abc))
        def run(*args):
            result = subprocess.run([str(ffdec), *map(str, args)], capture_output=True,
                text=True, encoding="utf-8", errors="replace", timeout=180)
            if result.returncode:
                raise ValueError("FFDec failed: " + (result.stdout + result.stderr)[-2000:])
        xml = root / 'original.xml'
        run('-swf2xml', wrapper, xml)
        run('-xml2swf', xml, root / 'noop.swf')
        if abc_from_swf((root / 'noop.swf').read_bytes()) != original_abc:
            raise ValueError("XML serialization changed the original ABC")
        run('-selectclass', 'settings', '-format', 'script:pcodehex', '-export', 'script', root / 'pcode', wrapper)
        tree = ET.parse(xml)
        before = copy.deepcopy(tree.getroot().find('.//abc'))
        patch_facts = patch_xml(tree, (root / 'pcode/scripts/settings.pcode').read_text(encoding='utf-8'))
        tree.write(root / 'entry.xml', encoding='utf-8', xml_declaration=True)
        run('-xml2swf', root / 'entry.xml', compiled)
        run('-swf2xml', compiled, root / 'verified.xml')
        verify_only_entry_changes(before, ET.parse(root / 'verified.xml').getroot().find('.//abc'))
        abc = abc_from_swf(compiled.read_bytes())
        rebuilt = replace_settings_abc(data, abc)
        # Re-extract from the rebuilt Iggy, then independently decompile again.
        verified_source, verified_count = _run_ffdec_export(ffdec, abc_from_iggy(rebuilt))
        for token in ("Mod 设置", "Mod Settings", "Mod 设置 / Mod Settings",
                      'ExternalInterface.call("SoD2SE_Mcm_v1",0,',
                      'ExternalInterface.call("SoD2SE_Mcm_v1",14,',
                      "SoD2SE_ModSettings_Back", "this.OnCategoryBack"):
            if token not in verified_source:
                raise ValueError("Recompiled entry lost binding: " + token)
        if verified_count != class_count:
            raise ValueError("Script class count changed")
        if replace_settings_abc(data, original_abc) != data:
            raise ValueError("No-op ABC writeback changed bytes")
        (output_dir / "settings-mod-entry.iggy").write_bytes(rebuilt)
    report = {
        "target_build": 16535856, "language": "runtime-detected-from-game",
        "scope": "Original settings category entry and return only; no MCM setting pages",
        "status": "offline_bytecode_patch_not_game_verified",
        "input_sha256": hashlib.sha256(data).hexdigest(),
        "output_sha256": hashlib.sha256(rebuilt).hexdigest(),
        "original_abc_size": len(original_abc), "compiled_abc_size": len(abc),
        "script_class_count": verified_count, **patch_facts,
        "native_category_enum_callback_guarded": True,
        "xml_noop_abc_byte_identical": True,
        "uses_original_category_button_focus_and_back_handler": True,
        "non_target_bytes_preserved": True, "noop_byte_identical": True,
        "independent_abc_reexport_passed": True,
        "runtime_verified": False, "installed": False,
    }
    (output_dir / "entry-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iggy", required=True, type=Path)
    parser.add_argument("--ffdec", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(build(args.iggy, args.ffdec, args.output_dir), ensure_ascii=False, indent=2))
