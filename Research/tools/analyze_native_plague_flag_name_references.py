#!/usr/bin/env python3
"""Audit fixed-build native instruction references to the two plague flags.

This records direct code operands that point at the exact ASCII property names
and their local instruction context. It does not infer field reads from raw
offsets or resolve reflective, virtual, or delegate dispatch.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from analyze_all_pdata_direct_call_xrefs import sha256_file
from analyze_mission_condition_enum_native_registration import (
    _instructions_for_ranges,
    _runtime_function_records,
    chained_ranges_for_root,
)
from analyze_mission_condition_enum_registration import (
    find_executable_instruction_refs,
    find_string_rvas,
)
from pe_static import PeImage


ROOT = Path(__file__).resolve().parents[2]
DATABASE = ROOT / "Research" / "StateOfDecay2" / "16535856"
EXPECTED_IMAGE_SHA256 = "EBF0A73E164BAA701F74655585F262F8E38A32B1F6DC5057303489BA5B333ECE"
PROPERTY_NAMES = ["IsPlagueZombie", "bIsBloodPlagueZombie"]
ASCII_METADATA = re.compile(r"[A-Za-z0-9_:/\\. -]{3,160}\Z")


def _call_targets(instructions: list) -> list[int]:
    import capstone

    return [
        int(instruction.operands[0].imm)
        for instruction in instructions
        if instruction.mnemonic == "call"
        and instruction.operands
        and instruction.operands[0].type == capstone.CS_OP_IMM
    ]


def _reference_context(image: PeImage, runtime_records: list, reference: dict) -> dict:
    import capstone

    root = int(reference["function_start_rva"], 16)
    site = int(reference["site_rva"], 16)
    ranges = chained_ranges_for_root(runtime_records, root)
    instructions = _instructions_for_ranges(image, ranges)
    index = next((i for i, row in enumerate(instructions) if row.address == site), None)
    if index is None:
        raise ValueError("direct name reference site is absent from its decoded function chain")
    start = max(0, index - 4)
    end = min(len(instructions), index + 13)
    window = instructions[start:end]
    following = instructions[index + 1:min(len(instructions), index + 17)]
    calls = _call_targets(following)
    string_references = []
    seen_string_refs = set()
    for instruction in instructions:
        for operand in instruction.operands:
            target_rva = None
            if operand.type == capstone.CS_OP_MEM and operand.mem.base == capstone.x86_const.X86_REG_RIP:
                target_rva = instruction.address + instruction.size + operand.mem.disp
            elif operand.type == capstone.CS_OP_IMM:
                immediate = int(operand.imm)
                if image.section_for_rva(immediate):
                    target_rva = immediate
                else:
                    candidate = immediate - image.image_base
                    if candidate >= 0 and image.section_for_rva(candidate):
                        target_rva = candidate
            if target_rva is None:
                continue
            try:
                offset = image.rva_to_offset(target_rva, 1)
                raw = image.data[offset:offset + 161].split(b"\0", 1)[0]
                text = raw.decode("ascii")
            except (ValueError, UnicodeDecodeError):
                continue
            if not ASCII_METADATA.fullmatch(text) or (instruction.address, target_rva) in seen_string_refs:
                continue
            seen_string_refs.add((instruction.address, target_rva))
            string_references.append({
                "site_rva": hex(instruction.address),
                "target_rva": hex(target_rva),
                "text": text,
            })
    if 0x1135D10 in calls and 0x1DBB3F0 in calls:
        pattern = "name-reference-followed-by-0x1135d10-and-0x1dbb3f0"
    elif 0x12043F0 in calls:
        pattern = "name-reference-followed-by-0x12043f0"
    elif 0x24FC450 in calls:
        pattern = "name-reference-followed-by-0x24fc450"
    else:
        pattern = "other-or-unresolved"
    return {
        "function_start_rva": reference["function_start_rva"],
        "reference_site_rva": reference["site_rva"],
        "local_call_targets": [hex(value) for value in calls],
        "context_pattern": pattern,
        "function_ascii_metadata_references": string_references,
        "instructions": [
            {"rva": hex(row.address), "mnemonic": row.mnemonic, "operands": row.op_str}
            for row in window
        ],
    }


def build_report(executable: Path) -> dict:
    image = PeImage(executable)
    digest = sha256_file(image.path)
    if digest != EXPECTED_IMAGE_SHA256:
        raise ValueError("executable SHA256 does not match fixed target: " + digest)
    string_rvas = find_string_rvas(image, PROPERTY_NAMES)
    references = find_executable_instruction_refs(image, string_rvas)
    runtime_records = _runtime_function_records(image)
    contexts = {
        name: [_reference_context(image, runtime_records, row) for row in rows]
        for name, rows in references.items()
    }

    xp_report = json.loads(
        (DATABASE / "roguelite-kill-experience-disassembly.json").read_text(encoding="utf-8-sig")
    )
    xp_ranges = [
        (int(ranges["start"], 16), int(ranges["end_exclusive"], 16))
        for row in xp_report.get("functions", [])
        for ranges in row.get("pdata_ranges_rva", [row["pdata_range_rva"]])
    ]
    xp_body_refs = {
        name: [
            row for row in rows
            if any(start <= int(row["site_rva"], 16) < end for start, end in xp_ranges)
        ]
        for name, rows in references.items()
    }
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
            "selected_xp_disassembly_function_count": len(xp_report.get("functions", [])),
            "selected_xp_disassembly_pdata_range_count": len(xp_ranges),
        },
        "method": "Search exact ASCII plague-flag property names, decode every executable .pdata operand, and retain local instruction context for each direct string-address reference.",
        "property_name_string_occurrences": {
            name: [hex(rva) for rva in rvas]
            for name, rvas in string_rvas.items()
        },
        "executable_instruction_reference_counts": {
            name: len(rows) for name, rows in references.items()
        },
        "executable_instruction_references": references,
        "reference_contexts": contexts,
        "selected_xp_function_direct_name_references": xp_body_refs,
        "limits": [
            "A direct code reference to a property-name string can belong to property registration, serialization, or name-based reflection; local call patterns are recorded but not assigned undocumented semantics.",
            "Zero direct property-name references inside the selected XP function bodies does not rule out field access by numeric offset, inherited accessors, reflection, virtual calls, delegates, or functions outside that selection.",
            "This scan does not identify which victim field is delivered by a death event and does not prove whether XP classification reads either plague flag.",
            "No live game process or memory was accessed.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("executable", type=Path, help="local fixed-version StateOfDecay2-Win64-Shipping.exe")
    parser.add_argument("--output", type=Path, default=DATABASE / "zombie-plague-flag-native-name-references.json")
    args = parser.parse_args()
    report = build_report(args.executable)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    counts = report["executable_instruction_reference_counts"]
    print(
        "PASS: plague flag direct native name references: IsPlagueZombie=%d, bIsBloodPlagueZombie=%d; XP-body name references=%d"
        % (
            counts["IsPlagueZombie"],
            counts["bIsBloodPlagueZombie"],
            sum(len(rows) for rows in report["selected_xp_function_direct_name_references"].values()),
        )
    )


if __name__ == "__main__":
    main()
