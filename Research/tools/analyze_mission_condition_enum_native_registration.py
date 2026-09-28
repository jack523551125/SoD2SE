#!/usr/bin/env python3
"""Decode the fixed-build native registration path for one mission enum.

This targeted report follows Windows x64 CHAININFO unwind records so split
hot/cold fragments are not mistaken for unrelated tiny functions. It records
instruction and table evidence only; the inferred enum values are not a
recovered UPROPERTY default for CommunityMissionCondition.
"""

from __future__ import annotations

import argparse
import json
import struct
from pathlib import Path

from analyze_all_pdata_direct_call_xrefs import sha256_file
from pe_static import PeImage


ROOT = Path(__file__).resolve().parents[2]
DATABASE = ROOT / "Research" / "StateOfDecay2" / "16535856"
ENUM_NAME = "EMissionConditionComparison"
INITIALIZER_ROOT_RVA = 0xF65D90
ENUMERATOR_BUILDER_ROOT_RVA = 0x11B4D10
ENUMERATOR_BUILDER_RVA = 0x11B4D10
EXPECTED_IMAGE_SHA256 = "EBF0A73E164BAA701F74655585F262F8E38A32B1F6DC5057303489BA5B333ECE"


def _runtime_function_records(image: PeImage) -> list[dict]:
    table_offset = image.rva_to_offset(image.exception_rva, image.exception_size)
    records = []
    for index in range(image.exception_size // 12):
        start, end, unwind = struct.unpack_from("<III", image.data, table_offset + index * 12)
        if start >= end or not image.section_for_rva(start, end - start):
            continue
        unwind_offset = image.rva_to_offset(unwind, 4)
        first = image.data[unwind_offset]
        code_count = image.data[unwind_offset + 2]
        flags = first >> 3
        chain = None
        if flags & 0x4:  # UNW_FLAG_CHAININFO
            chain_offset = unwind_offset + 4 + ((code_count + 1) // 2) * 4
            parent = struct.unpack_from("<III", image.data, chain_offset)
            chain = {"begin_rva": parent[0], "end_exclusive_rva": parent[1], "unwind_info_rva": parent[2]}
        records.append({
            "begin_rva": start,
            "end_exclusive_rva": end,
            "unwind_info_rva": unwind,
            "unwind_flags": flags,
            "unwind_code_count": code_count,
            "chained_parent": chain,
        })
    return records


def chained_ranges_for_root(records: list[dict], root_start_rva: int) -> list[dict]:
    """Return a root plus every directly/recursively CHAININFO-linked range."""
    roots = [row for row in records if row["begin_rva"] == root_start_rva]
    if len(roots) != 1:
        raise ValueError("expected exactly one .pdata root at 0x%X, found %d" % (root_start_rva, len(roots)))
    result = [roots[0]]
    seen = {(roots[0]["begin_rva"], roots[0]["end_exclusive_rva"], roots[0]["unwind_info_rva"])}
    cursor = 0
    while cursor < len(result):
        parent = result[cursor]
        parent_key = (parent["begin_rva"], parent["end_exclusive_rva"], parent["unwind_info_rva"])
        for child in records:
            link = child["chained_parent"]
            if not link:
                continue
            link_key = (link["begin_rva"], link["end_exclusive_rva"], link["unwind_info_rva"])
            child_key = (child["begin_rva"], child["end_exclusive_rva"], child["unwind_info_rva"])
            if link_key == parent_key and child_key not in seen:
                seen.add(child_key)
                result.append(child)
        cursor += 1
    return sorted(result, key=lambda row: row["begin_rva"])


def decode_ranges(image: PeImage, ranges: list[dict]) -> list[dict]:
    try:
        import capstone
    except ImportError as error:
        raise SystemExit("Capstone 5.0.7 is required; install Research/tools/requirements.txt") from error
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    md.detail = True
    md.skipdata = False
    result = []
    for row in ranges:
        start = row["begin_rva"]
        end = row["end_exclusive_rva"]
        offset = image.rva_to_offset(start, end - start)
        instructions = [
            {"rva": hex(insn.address), "mnemonic": insn.mnemonic, "operands": insn.op_str}
            for insn in md.disasm(image.data[offset:offset + end - start], start)
        ]
        result.append({
            "begin_rva": hex(start),
            "end_exclusive_rva": hex(end),
            "unwind_info_rva": hex(row["unwind_info_rva"]),
            "unwind_flags": row["unwind_flags"],
            "chained_parent": (
                {
                    "begin_rva": hex(row["chained_parent"]["begin_rva"]),
                    "end_exclusive_rva": hex(row["chained_parent"]["end_exclusive_rva"]),
                    "unwind_info_rva": hex(row["chained_parent"]["unwind_info_rva"]),
                }
                if row["chained_parent"] else None
            ),
            "instruction_count": len(instructions),
            "instructions": instructions,
        })
    return result


def _ascii_string_rva(image: PeImage, text: str) -> int:
    needle = text.encode("ascii") + b"\0"
    offset = image.data.find(needle)
    if offset < 0:
        raise ValueError("missing ASCII string: " + text)
    matches = [
        section.virtual_address + offset - section.raw_offset
        for section in image.sections
        if section.raw_offset <= offset < section.raw_offset + section.raw_size
    ]
    if len(matches) != 1:
        raise ValueError("string is not in exactly one PE section: " + text)
    return matches[0]


def _read_pointer_name_table(image: PeImage, table_rva: int, max_entries: int = 64) -> list[dict]:
    entries = []
    offset = image.rva_to_offset(table_rva, 8)
    for index in range(max_entries):
        value = struct.unpack_from("<Q", image.data, offset + index * 8)[0]
        if value == 0:
            return entries
        name_rva = value - image.image_base
        name = image.read_c_string(value)
        if name is None:
            raise ValueError("table entry %d at 0x%X is not an ASCII FName string" % (index, table_rva + index * 8))
        entries.append({"index": index, "name": name, "name_rva": hex(name_rva), "pointer_rva": hex(table_rva + index * 8)})
    raise ValueError("pointer table has no null terminator within %d entries" % max_entries)


def _normalized_call_target(image: PeImage, operand) -> int | None:
    import capstone
    if operand.type != capstone.CS_OP_IMM:
        return None
    immediate = int(operand.imm)
    if image.section_for_rva(immediate):
        return immediate
    rva = immediate - image.image_base
    return rva if rva >= 0 and image.section_for_rva(rva) else None


def _instructions_for_ranges(image: PeImage, ranges: list[dict]):
    import capstone
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    md.detail = True
    decoded = []
    for row in ranges:
        start, end = row["begin_rva"], row["end_exclusive_rva"]
        offset = image.rva_to_offset(start, end - start)
        decoded.extend(md.disasm(image.data[offset:offset + end - start], start))
    return decoded


def _find_rip_target(insn, image: PeImage) -> int | None:
    import capstone
    for operand in insn.operands:
        if operand.type == capstone.CS_OP_MEM and operand.mem.base == capstone.x86_const.X86_REG_RIP:
            return insn.address + insn.size + operand.mem.disp
    return None


def _matching_callsite_instructions(instructions, target_rva: int, image: PeImage) -> list[dict]:
    import capstone
    result = []
    for insn in instructions:
        if not insn.group(capstone.CS_GRP_CALL) or not insn.operands:
            continue
        if _normalized_call_target(image, insn.operands[0]) == target_rva:
            result.append({"site_rva": hex(insn.address), "target_rva": hex(target_rva), "instruction": insn.mnemonic + " " + insn.op_str})
    return result


def build_report(executable: Path) -> dict:
    image = PeImage(executable)
    digest = sha256_file(image.path)
    if digest != EXPECTED_IMAGE_SHA256:
        raise ValueError("executable SHA256 does not match fixed target: " + digest)
    enum_name_rva = _ascii_string_rva(image, ENUM_NAME)

    records = _runtime_function_records(image)
    initializer_ranges = chained_ranges_for_root(records, INITIALIZER_ROOT_RVA)
    initializer_instructions = _instructions_for_ranges(image, initializer_ranges)
    enum_name_refs = []
    for insn in initializer_instructions:
        if _find_rip_target(insn, image) == enum_name_rva:
            enum_name_refs.append({"site_rva": hex(insn.address), "instruction": insn.mnemonic + " " + insn.op_str})

    builder_calls = _matching_callsite_instructions(initializer_instructions, ENUMERATOR_BUILDER_RVA, image)
    if len(builder_calls) != 1:
        raise ValueError("expected one enum-builder call from initializer, found %d" % len(builder_calls))
    call_site = int(builder_calls[0]["site_rva"], 16)
    # The call's setup operands are also retained in the disassembly. These
    # fixed-build instructions establish the table pointer and null override.
    setup_sites = [0xF65E4E, 0xF65E54, 0xF65E59, 0xF65E5C, call_site]
    setup_by_rva = {insn.address: insn for insn in initializer_instructions}
    setup_instructions = []
    for site in setup_sites:
        insn = setup_by_rva.get(site)
        if insn is None:
            raise ValueError("enum-builder setup instruction missing at 0x%X" % site)
        setup_instructions.append({"rva": hex(site), "mnemonic": insn.mnemonic, "operands": insn.op_str})
    table_instruction = setup_by_rva[0xF65E5C]
    table_rva = _find_rip_target(table_instruction, image)
    if table_rva is None:
        raise ValueError("could not resolve the enum-name table LEA")
    names = _read_pointer_name_table(image, table_rva)

    builder_ranges = chained_ranges_for_root(records, ENUMERATOR_BUILDER_ROOT_RVA)
    builder_instructions = _instructions_for_ranges(image, builder_ranges)
    builder_full_disassembly = decode_ranges(image, builder_ranges)
    call_text = {row["site_rva"]: row for row in builder_calls}[hex(call_site)]

    ordinal_evidence = {
        "optional_explicit_value_pointer_is_null_at_initializer_call": "xor r8d, r8d" in setup_instructions[2]["mnemonic"] + " " + setup_instructions[2]["operands"],
        "builder_copies_r8_to_rsi": any(insn.mnemonic == "mov" and insn.op_str == "rsi, r8" for insn in builder_instructions),
        "builder_fallback_uses_loop_index": any(insn.mnemonic == "movzx" and insn.op_str == "edi, bl" for insn in builder_instructions),
        "builder_stores_fallback_byte_in_record": any(insn.mnemonic == "mov" and insn.op_str == "byte ptr [rsp + 0x38], dil" for insn in builder_instructions),
        "builder_record_stride_is_16_bytes": any(insn.mnemonic == "shl" and insn.op_str == "rax, 4" for insn in builder_instructions),
        "builder_calls_virtual_setter_slot_0x200": any(insn.mnemonic == "call" and insn.op_str == "qword ptr [rax + 0x200]" for insn in builder_instructions),
        "builder_returns_zero_extended_bool": any(insn.mnemonic == "movzx" and insn.op_str == "eax, bl" for insn in builder_instructions),
    }
    if not all(ordinal_evidence.values()):
        raise ValueError("fixed-build enum construction evidence no longer matches expected instruction pattern")

    enumerator_entries = [
        {"name": entry["name"].split("::", 1)[1] if "::" in entry["name"] else entry["name"],
         "candidate_numeric_value": entry["index"]}
        for entry in names
    ]
    return {
        "schema": 1,
        "target": "target.json",
        "target_sha256": digest,
        "scope": {"game_process_started_or_attached": False, "executable": image.path.name},
        "method": "Resolve CHAININFO-linked .pdata fragments for the enum initializer and its local builder; decode the fixed executable instructions and the referenced null-terminated name-pointer table.",
        "enum": ENUM_NAME,
        "enum_name_string_rva": hex(enum_name_rva),
        "initializer": {
            "root_rva": hex(INITIALIZER_ROOT_RVA),
            "chain_ranges": decode_ranges(image, initializer_ranges),
            "enum_name_reference_instructions": enum_name_refs,
            "builder_call": call_text,
            "builder_call_setup": setup_instructions,
            "enumerator_name_table_rva": hex(table_rva),
            "enumerator_name_table": names,
        },
        "enumerator_builder": {
            "root_rva": hex(ENUMERATOR_BUILDER_ROOT_RVA),
            "chain_ranges": builder_full_disassembly,
            "instruction_evidence": ordinal_evidence,
            "behavior_inference": "The initializer passes a null explicit-values pointer. Across the chained builder body, the null-pointer branch copies the loop index byte (BL) into each 16-byte enumerator record; the helper then passes that array to a virtual setter. This is strong static evidence that the enum members receive sequential numeric values in name-table order.",
        },
        "candidate_numeric_value_mapping": enumerator_entries,
        "confidence": "strong-static-inference",
        "limits": [
            "The helper's virtual setter implementation is not symbolically named in this executable, so the numeric-value interpretation is recorded as a strong static inference rather than a runtime observation.",
            "This mapping does not establish the native/default value of the omitted Comparison field in CommunityMissionCondition instances.",
            "No live game process or memory was accessed.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("executable", type=Path, help="local fixed-version StateOfDecay2-Win64-Shipping.exe")
    parser.add_argument("--output", type=Path, default=DATABASE / "mission-condition-enum-native-registration.json")
    args = parser.parse_args()
    report = build_report(args.executable)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("PASS: decoded initializer/helper chains and %d sequential enum-value candidates" % len(report["candidate_numeric_value_mapping"]))


if __name__ == "__main__":
    main()
