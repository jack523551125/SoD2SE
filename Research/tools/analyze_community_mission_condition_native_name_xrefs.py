#!/usr/bin/env python3
"""Scan fixed-build code operands that directly reference condition names.

This is a narrow static follow-up for the unresolved CommunityMissionCondition
default. It checks exact ASCII name occurrences, aligned raw qword name
pointers, and decoded immediate/RIP-relative operands in executable .pdata
ranges. A zero result does not exclude hashed FNames, reflection, or indirect
metadata references.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from analyze_all_pdata_direct_call_xrefs import sha256_file
from analyze_mission_condition_enum_registration import find_executable_instruction_refs, find_qword_pointer_slots, find_string_rvas
from pe_static import PeImage


ROOT = Path(__file__).resolve().parents[2]
DATABASE = ROOT / "Research" / "StateOfDecay2" / "16535856"
NAMES = [
    "MissionCondition",
    "Comparison",
    "ComparisonStat",
    "CommunityMembers",
    "CommunityOutposts",
    "EMissionConditionComparison",
]
WIDE_NAMES = ["UCommunityMissionCondition", "CommunityMissionCondition"]
EXPECTED_IMAGE_SHA256 = "EBF0A73E164BAA701F74655585F262F8E38A32B1F6DC5057303489BA5B333ECE"


def find_utf16le_string_rvas(image: PeImage, strings: list[str]) -> dict[str, list[int]]:
    result = {}
    for text in strings:
        needle = text.encode("utf-16le") + bytes((0, 0))
        offsets = []
        cursor = 0
        while True:
            offset = image.data.find(needle, cursor)
            if offset < 0:
                break
            for section in image.sections:
                if section.raw_offset <= offset < section.raw_offset + section.raw_size:
                    offsets.append(section.virtual_address + offset - section.raw_offset)
                    break
            cursor = offset + 2
        result[text] = offsets
    return result


def build_report(executable: Path) -> dict:
    image = PeImage(executable)
    digest = sha256_file(image.path)
    if digest != EXPECTED_IMAGE_SHA256:
        raise ValueError("executable SHA256 does not match fixed target: " + digest)
    occurrences = find_string_rvas(image, NAMES)
    wide_occurrences = find_utf16le_string_rvas(image, WIDE_NAMES)
    all_occurrences = {
        **{"ascii:" + name: values for name, values in occurrences.items()},
        **{"utf16le:" + name: values for name, values in wide_occurrences.items()},
    }
    targets = {
        "%s#%d" % (name, index): [rva]
        for name, values in all_occurrences.items()
        for index, rva in enumerate(values)
    }
    vas = {
        label: image.image_base + rvas[0]
        for label, rvas in targets.items()
    }
    pointer_slots = find_qword_pointer_slots(image, vas)
    instruction_refs = find_executable_instruction_refs(image, targets)
    return {
        "schema": 1,
        "target": "target.json",
        "target_sha256": digest,
        "scope": {
            "game_process_started_or_attached": False,
            "executable_name": image.path.name,
            "executable_pdata_ranges_scanned": sum(
                1 for start, end in image.function_ranges
                if (section := image.section_for_rva(start, end - start)) and section.is_executable
            ),
            "searched_name_occurrence_count": sum(len(values) for values in occurrences.values()),
            "searched_wide_name_occurrence_count": sum(len(values) for values in wide_occurrences.values()),
        },
        "method": "For each exact ASCII occurrence, scan aligned qword pointers in non-executable sections and decode executable .pdata bodies for immediate/RIP-relative operands that resolve to that occurrence.",
        "string_occurrences_ascii": {name: [hex(rva) for rva in values] for name, values in occurrences.items()},
        "string_occurrences_utf16le": {name: [hex(rva) for rva in values] for name, values in wide_occurrences.items()},
        "raw_qword_pointer_slots": pointer_slots,
        "executable_instruction_references": instruction_refs,
        "limits": [
            "The report only covers exact ASCII strings, aligned qword pointer slots, and directly decoded immediate/RIP-relative code operands.",
            "It does not resolve FName hashes, relocation records, pointer tables with other encodings, property metadata accessed through reflection, or serialized/default object construction.",
            "No direct code reference or raw pointer match does not prove a name or field is unused.",
            "No live game process or memory was accessed.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("executable", type=Path, help="local fixed-version StateOfDecay2-Win64-Shipping.exe")
    parser.add_argument("--output", type=Path, default=DATABASE / "community-mission-condition-native-name-xrefs.json")
    args = parser.parse_args()
    report = build_report(args.executable)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    count = sum(len(refs) for refs in report["executable_instruction_references"].values())
    print("PASS: scanned %d ASCII and %d UTF-16 names across %d .pdata ranges; %d direct code-name references" % (
        report["scope"]["searched_name_occurrence_count"],
        report["scope"]["searched_wide_name_occurrence_count"],
        report["scope"]["executable_pdata_ranges_scanned"], count,
    ))


if __name__ == "__main__":
    main()
