#!/usr/bin/env python3
"""Locate fixed-build native mission-condition enum name pointer groups.

The report preserves raw PE string and qword-pointer evidence. It treats the
pointer order as an ordinal candidate only; it does not infer a struct default
or assume that omitted cooked properties take a particular value.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
from pathlib import Path

from pe_static import PeImage


ROOT = Path(__file__).resolve().parents[2]
DATABASE = ROOT / "Research" / "StateOfDecay2" / "16535856"
ENUM_NAME = "EMissionConditionComparison"
ENUM_VALUES = ["Equal", "Greater", "GreaterOrEqual", "Less", "LessOrEqual", "NotEqual"]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def find_string_rvas(image: PeImage, strings: list[str]) -> dict[str, list[int]]:
    result = {}
    for text in strings:
        needle = text.encode("ascii") + b"\0"
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
            cursor = offset + 1
        result[text] = offsets
    return result


def find_qword_pointer_slots(image: PeImage, target_vas: dict[str, int]) -> dict[str, list[dict]]:
    reverse = {value: key for key, value in target_vas.items()}
    slots = {key: [] for key in target_vas}
    for section in image.sections:
        if section.is_executable:
            continue
        start = section.raw_offset
        end = start + section.raw_size
        for offset in range(start, end - 7, 8):
            value = struct.unpack_from("<Q", image.data, offset)[0]
            name = reverse.get(value)
            if name is not None:
                slots[name].append({
                    "section": section.name,
                    "slot_rva": hex(section.virtual_address + offset - section.raw_offset),
                    "slot_file_offset": hex(offset),
                })
    return slots


def ordered_pointer_group_candidate(enum_name: str, enum_values: list[str], pointer_slots: dict[str, list[dict]]) -> dict:
    names = [enum_name + "::" + value for value in enum_values]
    rows = []
    for name in names:
        candidates = pointer_slots.get(name, [])
        if len(candidates) != 1:
            return {"complete": False, "entries": [], "reason": "%s has %d raw pointer slots" % (name, len(candidates))}
        rows.append({"name": name, **candidates[0]})
    rows.sort(key=lambda row: (row["section"], int(row["slot_rva"], 16)))
    offsets = [int(row["slot_rva"], 16) for row in rows]
    sections = {row["section"] for row in rows}
    contiguous = len(sections) == 1 and all(right - left == 8 for left, right in zip(offsets, offsets[1:]))
    return {
        "complete": contiguous,
        "contiguous_qword_pointer_group": contiguous,
        "entries": rows,
        "reason": None if contiguous else "enum-name pointers are not one contiguous qword group",
    }


def find_executable_instruction_refs(image: PeImage, target_rvas: dict[str, list[int]]) -> dict[str, list[dict]]:
    """Find decoded .pdata instruction operands that resolve to target RVAs."""
    try:
        import capstone
    except ImportError as error:
        raise SystemExit("Capstone 5.0.7 is required; install Research/tools/requirements.txt") from error

    reverse = {}
    for label, rvas in target_rvas.items():
        for rva in rvas:
            reverse.setdefault(rva, []).append(label)
    references = {label: [] for label in target_rvas}
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    md.detail = True
    md.skipdata = False

    for start, end in image.function_ranges:
        size = end - start
        section = image.section_for_rva(start, size)
        if section is None or not section.is_executable:
            continue
        try:
            offset = image.rva_to_offset(start, size)
        except ValueError:
            continue
        body = image.data[offset:offset + size]
        for instruction in md.disasm(body, start):
            for operand_index, operand in enumerate(instruction.operands):
                target_rva = None
                reference_kind = None
                if operand.type == capstone.CS_OP_IMM:
                    immediate = int(operand.imm)
                    if image.section_for_rva(immediate):
                        target_rva = immediate
                    else:
                        candidate = immediate - image.image_base
                        if candidate >= 0 and image.section_for_rva(candidate):
                            target_rva = candidate
                    reference_kind = "immediate-address"
                elif (
                    operand.type == capstone.CS_OP_MEM
                    and operand.mem.base == capstone.x86_const.X86_REG_RIP
                ):
                    target_rva = instruction.address + instruction.size + operand.mem.disp
                    reference_kind = "rip-relative-address"
                if target_rva not in reverse:
                    continue
                for label in reverse[target_rva]:
                    references[label].append({
                        "site_rva": hex(instruction.address),
                        "function_start_rva": hex(start),
                        "instruction": instruction.mnemonic + " " + instruction.op_str,
                        "operand_index": operand_index,
                        "reference_kind": reference_kind,
                        "target_rva": hex(target_rva),
                    })
    return references


def build_report(executable: Path) -> dict:
    image = PeImage(executable)
    enum_names = [ENUM_NAME + "::" + value for value in ENUM_VALUES]
    maximum_name = ENUM_NAME + "::" + ENUM_NAME + "_MAX"
    strings = find_string_rvas(image, enum_names + [maximum_name, ENUM_NAME])
    target_vas = {
        name: image.image_base + rvas[0]
        for name, rvas in strings.items()
        if rvas
    }
    slots = find_qword_pointer_slots(image, target_vas)
    group = ordered_pointer_group_candidate(ENUM_NAME, ENUM_VALUES, slots)
    max_slots = slots.get(maximum_name, [])
    executable_refs = find_executable_instruction_refs(image, strings)
    return {
        "schema": 1,
        "target": "target.json",
        "target_sha256": sha256_file(image.path),
        "method": "Search the exact executable image for ASCII FName strings, qword pointers in non-executable PE sections, and decoded immediate/RIP-relative operands in executable .pdata bodies.",
        "scope": {
            "game_process_started_or_attached": False,
            "executable_name": image.path.name,
            "enum_name": ENUM_NAME,
            "enum_value_count": len(ENUM_VALUES),
        },
        "enum_name_string_occurrences": {
            name: [hex(rva) for rva in rvas]
            for name, rvas in strings.items()
        },
        "raw_qword_pointer_slots": slots,
        "executable_instruction_references": executable_refs,
        "ordered_enum_name_pointer_group_candidate": group,
        "maximum_sentinel_pointer_slots": max_slots,
        "ordinal_mapping_candidates": [
            {"candidate_ordinal": index, "candidate_name": row["name"].split("::", 1)[1], "pointer_slot_rva": row["slot_rva"]}
            for index, row in enumerate(group["entries"])
        ] if group["complete"] else [],
        "limits": [
            "The contiguous qword group is raw name-pointer evidence, not an extracted UEnum numeric-value array or executable use site.",
            "The candidate ordinal order does not prove the field's default value for omitted CommunityMissionCondition properties.",
            "No live game process or memory was accessed.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("executable", type=Path, help="local fixed-version StateOfDecay2-Win64-Shipping.exe")
    parser.add_argument("--output", type=Path, default=DATABASE / "mission-condition-enum-native-pointer-evidence.json")
    args = parser.parse_args()
    report = build_report(args.executable)
    expected = json.loads((DATABASE / "target.json").read_text(encoding="utf-8"))["sha256"].upper()
    if report["target_sha256"] != expected:
        raise SystemExit("executable SHA256 does not match Research/StateOfDecay2/16535856/target.json")
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    group = report["ordered_enum_name_pointer_group_candidate"]
    print("PASS: %d enum names; contiguous pointer group candidate=%s" % (len(ENUM_VALUES), group["complete"]))


if __name__ == "__main__":
    main()
