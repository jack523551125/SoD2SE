#!/usr/bin/env python3
"""Decode the fixed-build EZombieVariantType enum registration offline."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from analyze_all_pdata_direct_call_xrefs import sha256_file
from analyze_mission_condition_enum_native_registration import (
    _instructions_for_ranges,
    _read_pointer_name_table,
    _runtime_function_records,
    chained_ranges_for_root,
    decode_ranges,
)
from analyze_mission_condition_enum_registration import (
    find_executable_instruction_refs,
    find_qword_pointer_slots,
    find_string_rvas,
    ordered_pointer_group_candidate,
)
from pe_static import PeImage


ROOT = Path(__file__).resolve().parents[2]
DATABASE = ROOT / "Research" / "StateOfDecay2" / "16535856"
EXPECTED_IMAGE_SHA256 = "EBF0A73E164BAA701F74655585F262F8E38A32B1F6DC5057303489BA5B333ECE"
ENUM_NAME = "EZombieVariantType"
ENUM_VALUES = ["Slow", "Unique", "Fast", "Armored", "Plague"]
INITIALIZER_ROOT_RVA = 0xD660D0
ENUMERATOR_BUILDER_ROOT_RVA = 0x11B4D10


def _call_target(instruction) -> int | None:
    import capstone

    if instruction.mnemonic == "call" and instruction.operands and instruction.operands[0].type == capstone.CS_OP_IMM:
        return int(instruction.operands[0].imm)
    return None


def _rip_target(instruction) -> int | None:
    import capstone

    for operand in instruction.operands:
        if operand.type == capstone.CS_OP_MEM and operand.mem.base == capstone.x86_const.X86_REG_RIP:
            return instruction.address + instruction.size + operand.mem.disp
    return None


def infer_enum_mapping(name_table: list[dict], explicit_values_pointer_is_null: bool) -> list[dict]:
    """Return an ordinal inference only for the verified index-fallback path."""
    expected = [ENUM_NAME + "::" + value for value in ENUM_VALUES]
    expected.append(ENUM_NAME + "::" + ENUM_NAME + "_MAX")
    names = [row.get("name") for row in name_table]
    if names != expected:
        raise ValueError("enum name table is incomplete, reordered, or has an unexpected sentinel")
    if not explicit_values_pointer_is_null:
        raise ValueError("explicit enum numeric values prevent inferring ordinals from table order")
    return [
        {"name": row["name"].split("::", 1)[1], "candidate_numeric_value": index}
        for index, row in enumerate(name_table)
    ]


def build_report(executable: Path) -> dict:
    image = PeImage(executable)
    digest = sha256_file(image.path)
    if digest != EXPECTED_IMAGE_SHA256:
        raise ValueError("executable SHA256 does not match fixed target: " + digest)

    sentinel = ENUM_NAME + "::" + ENUM_NAME + "_MAX"
    enum_strings = [ENUM_NAME + "::" + value for value in ENUM_VALUES] + [sentinel, ENUM_NAME]
    string_rvas = find_string_rvas(image, enum_strings)
    if any(len(string_rvas[name]) != 1 for name in enum_strings):
        raise ValueError("expected one exact ASCII occurrence per native enum string")

    target_rvas = {name: values for name, values in string_rvas.items()}
    code_refs = find_executable_instruction_refs(image, target_rvas)
    type_refs = code_refs[ENUM_NAME]
    if len(type_refs) != 1 or type_refs[0]["function_start_rva"] != hex(INITIALIZER_ROOT_RVA):
        raise ValueError("expected one direct .pdata reference to the enum type name")

    target_vas = {name: image.image_base + rvas[0] for name, rvas in string_rvas.items()}
    pointer_slots = find_qword_pointer_slots(image, target_vas)
    pointer_group = ordered_pointer_group_candidate(ENUM_NAME, ENUM_VALUES, pointer_slots)
    if not pointer_group.get("complete"):
        raise ValueError("enum member strings do not form a complete contiguous pointer group")
    max_slots = pointer_slots.get(sentinel, [])
    if len(max_slots) != 1 or int(max_slots[0]["slot_rva"], 16) != int(pointer_group["entries"][-1]["slot_rva"], 16) + 8:
        raise ValueError("enum sentinel pointer does not immediately follow member group")

    runtime_records = _runtime_function_records(image)
    initializer_ranges = chained_ranges_for_root(runtime_records, INITIALIZER_ROOT_RVA)
    initializer_instructions = _instructions_for_ranges(image, initializer_ranges)
    enum_name_rva = string_rvas[ENUM_NAME][0]
    name_refs = [instruction for instruction in initializer_instructions if _rip_target(instruction) == enum_name_rva]
    if len(name_refs) != 1:
        raise ValueError("initializer does not contain exactly one LEA to enum type name")

    builder_calls = [instruction for instruction in initializer_instructions
                     if _call_target(instruction) == ENUMERATOR_BUILDER_ROOT_RVA]
    if len(builder_calls) != 1:
        raise ValueError("initializer does not call expected enum-member builder exactly once")
    call_site = builder_calls[0].address
    by_rva = {instruction.address: instruction for instruction in initializer_instructions}
    setup_sites = [0xD6618E, 0xD66194, 0xD66199, 0xD6619C, 0xD661A6]
    if call_site != setup_sites[-1] or any(site not in by_rva for site in setup_sites):
        raise ValueError("enum builder setup sequence changed")
    setup = [
        {"rva": hex(site), "mnemonic": by_rva[site].mnemonic, "operands": by_rva[site].op_str}
        for site in setup_sites
    ]
    table_rva = _rip_target(by_rva[0xD6619C])
    if table_rva is None:
        raise ValueError("could not resolve enum member-name table")
    name_table = _read_pointer_name_table(image, table_rva)
    expected_names = [ENUM_NAME + "::" + value for value in ENUM_VALUES] + [sentinel]
    if [row["name"] for row in name_table] != expected_names:
        raise ValueError("initializer's runtime name table disagrees with native enum strings")

    builder_ranges = chained_ranges_for_root(runtime_records, ENUMERATOR_BUILDER_ROOT_RVA)
    builder_instructions = _instructions_for_ranges(image, builder_ranges)
    builder_by_text = {instruction.mnemonic + " " + instruction.op_str for instruction in builder_instructions}
    builder_evidence = {
        "optional_values_pointer_is_null": "xor r8d, r8d" in {row["mnemonic"] + " " + row["operands"] for row in setup},
        "builder_copies_r8_to_rsi": "mov rsi, r8" in builder_by_text,
        "null_values_fallback_uses_loop_index": "movzx edi, bl" in builder_by_text,
        "fallback_byte_written_to_enumerator_record": "mov byte ptr [rsp + 0x38], dil" in builder_by_text,
        "enumerator_record_stride_is_16_bytes": "shl rax, 4" in builder_by_text,
        "records_passed_to_virtual_setter": "call qword ptr [rax + 0x200]" in builder_by_text,
    }
    if not all(builder_evidence.values()):
        raise ValueError("enum builder no longer exhibits the expected sequential-index fallback")

    values = infer_enum_mapping(name_table, builder_evidence["optional_values_pointer_is_null"])
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
        },
        "method": "Resolve exact enum-name strings, aligned native name-pointer slots, direct executable code references, initializer CHAININFO fragments, and the shared enumerator builder on the fixed build.",
        "enum": ENUM_NAME,
        "enum_type_name_rva": hex(enum_name_rva),
        "enum_type_name_direct_code_reference": type_refs[0],
        "ordered_member_name_pointer_group": pointer_group,
        "sentinel_pointer_slot": max_slots[0],
        "initializer": {
            "root_rva": hex(INITIALIZER_ROOT_RVA),
            "chain_ranges": decode_ranges(image, initializer_ranges),
            "enum_name_reference_site_rva": hex(name_refs[0].address),
            "builder_call_site_rva": hex(call_site),
            "builder_call_setup": setup,
            "enumerator_name_table_rva": hex(table_rva),
            "enumerator_name_table": name_table,
        },
        "enumerator_builder": {
            "root_rva": hex(ENUMERATOR_BUILDER_ROOT_RVA),
            "chain_ranges": decode_ranges(image, builder_ranges),
            "instruction_evidence": builder_evidence,
        },
        "candidate_numeric_value_mapping": values,
        "candidate_plague_ordinal": 4,
        "confidence": "strong-static-inference",
        "limits": [
            "The native setter is virtual and not symbolically named, so this is a strong static inference rather than a runtime observation.",
            "The map establishes the enum's ordinal order; it does not prove which victim field is supplied to a kill event or whether experience awards read the plague flags.",
            "No live game process or memory was accessed.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("executable", type=Path, help="local fixed-version StateOfDecay2-Win64-Shipping.exe")
    parser.add_argument("--output", type=Path, default=DATABASE / "zombie-variant-enum-native-registration.json")
    args = parser.parse_args()
    report = build_report(args.executable)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("PASS: EZombieVariantType order is Slow=0, Unique=1, Fast=2, Armored=3, Plague=4 (strong static inference)")


if __name__ == "__main__":
    main()
