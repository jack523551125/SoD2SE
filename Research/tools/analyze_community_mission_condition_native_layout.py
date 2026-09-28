#!/usr/bin/env python3
"""Recover fixed-build CommunityMissionCondition registration/layout evidence.

This follows only offline PE instructions and CHAININFO ranges. It records the
property names, registration offsets, class-name references, and size arguments
that compose the native initializer. The association of the first two fields
with the class is a static initializer-chain inference; this does not recover a
class-default object or prove the value used for an omitted property.
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
from pe_static import PeImage


ROOT = Path(__file__).resolve().parents[2]
DATABASE = ROOT / "Research" / "StateOfDecay2" / "16535856"
EXPECTED_IMAGE_SHA256 = "EBF0A73E164BAA701F74655585F262F8E38A32B1F6DC5057303489BA5B333ECE"

COMMUNITY_INITIALIZER_RVA = 0xFC7C40
COMMUNITY_CLASS_REGISTRATION_RVA = 0xA2F8F0
BASE_CLASS_REGISTRATION_RVA = 0xA42DF0
BASE_PROPERTY_INITIALIZER_RVA = 0xF32160
ENUM_INITIALIZER_RVA = 0xF65D90
CLASS_REGISTRATION_HELPER_RVA = 0x11A4680
PROPERTY_CONSTRUCTION_HELPER_RVA = 0x12043F0
PROPERTY_OFFSET_HELPER_RVA = 0x11D27C0


def _instruction_map(instructions) -> dict[int, object]:
    return {instruction.address: instruction for instruction in instructions}


def _rip_target(instruction) -> int | None:
    import capstone

    for operand in instruction.operands:
        if operand.type == capstone.CS_OP_MEM and operand.mem.base == capstone.x86_const.X86_REG_RIP:
            return instruction.address + instruction.size + operand.mem.disp
    return None


def _call_target(instruction) -> int | None:
    import capstone

    if instruction.mnemonic != "call" or not instruction.operands:
        return None
    operand = instruction.operands[0]
    if operand.type == capstone.CS_OP_IMM:
        return int(operand.imm)
    return None


def _wide_c_string(image: PeImage, rva: int, max_chars: int = 180) -> str:
    offset = image.rva_to_offset(rva, 2)
    raw = image.data[offset:offset + max_chars * 2]
    return raw.decode("utf-16le", errors="strict").split("\0", 1)[0]


def parse_r9d_offset_assignment(mnemonic: str, operands: str,
                                zeroed_registers: set[str] | None = None) -> int:
    """Parse the small immediate/zero-based LEA forms used for these offsets."""
    zeroed_registers = zeroed_registers or set()
    if mnemonic == "mov" and operands.startswith("r9d, "):
        return int(operands.split(",", 1)[1].strip(), 0)
    if mnemonic == "lea" and operands.startswith("r9d, ["):
        match = re.fullmatch(r"r9d, \[(r[a-z0-9]+) \+ (0x[0-9a-fA-F]+|\d+)\]", operands)
        if not match:
            raise ValueError("unsupported r9d offset LEA: " + operands)
        base, displacement = match.groups()
        if base not in zeroed_registers:
            raise ValueError("r9d offset LEA base is not proven zero: " + base)
        return int(displacement, 0)
    raise ValueError("unsupported r9d offset assignment: " + mnemonic + " " + operands)


def _registration_record(image: PeImage, instructions, root: int, name_ref_site: int,
                         expected_name: str) -> dict:
    by_rva = _instruction_map(instructions)
    name_ref = by_rva[name_ref_site]
    name_rva = _rip_target(name_ref)
    referenced_text = _wide_c_string(image, name_rva) if name_rva is not None else None
    full_text = _wide_c_string(image, name_rva - 2) if name_rva is not None and name_rva >= 2 else None
    if referenced_text != expected_name.removeprefix("U") or full_text != expected_name:
        raise ValueError("class-name LEA does not resolve to " + expected_name)

    helper_calls = [
        instruction for instruction in instructions
        if _call_target(instruction) == CLASS_REGISTRATION_HELPER_RVA
    ]
    if len(helper_calls) != 1:
        raise ValueError("expected one generic class-registration helper call at 0x%X" % root)
    helper_call = helper_calls[0]
    helper_index = list(instructions).index(helper_call)
    setup = list(instructions)[:helper_index]
    size_instruction = next((instruction for instruction in reversed(setup)
                             if instruction.mnemonic == "mov"
                             and instruction.op_str.startswith("dword ptr [rsp + 0x20], "))
                            , None)
    flags_instruction = next((instruction for instruction in reversed(setup)
                              if instruction.mnemonic == "mov"
                              and instruction.op_str.startswith("dword ptr [rsp + 0x28], "))
                             , None)
    if size_instruction is None or flags_instruction is None:
        raise ValueError("class-registration size/flags arguments missing at 0x%X" % root)
    size_match = re.search(r",\s*(0x[0-9a-fA-F]+|\d+)$", size_instruction.op_str)
    flags_match = re.search(r",\s*(0x[0-9a-fA-F]+|\d+)$", flags_instruction.op_str)
    if not size_match or not flags_match:
        raise ValueError("class-registration argument is not an immediate at 0x%X" % root)
    return {
        "root_rva": hex(root),
        "class_name": expected_name,
        "class_name_reference": {
            "site_rva": hex(name_ref.address),
            "name_rva": hex(name_rva),
            "referenced_suffix": referenced_text,
            "instruction": name_ref.mnemonic + " " + name_ref.op_str,
        },
        "registered_size_argument_candidate": int(size_match.group(1), 0),
        "class_flags_argument_candidate": int(flags_match.group(1), 0),
        "helper_call": {
            "site_rva": hex(helper_call.address),
            "target_rva": hex(_call_target(helper_call)),
            "instruction": helper_call.mnemonic + " " + helper_call.op_str,
        },
    }


def _field_offset_from_r9d_assignment(instructions, assignment_site: int,
                                      attach_call_site: int) -> tuple[int, str]:
    by_rva = _instruction_map(instructions)
    assignment = by_rva[assignment_site]
    call = by_rva[attach_call_site]
    if _call_target(call) != PROPERTY_OFFSET_HELPER_RVA:
        raise ValueError("property-offset helper call mismatch at 0x%X" % attach_call_site)
    zeroed_registers = set()
    if any(
            instruction.address < assignment_site
            and instruction.mnemonic == "xor"
            and instruction.op_str == "edi, edi"
            for instruction in instructions
        ):
        # Both generated registration bodies clear EDI before these LEAs.
        zeroed_registers.add("rdi")
    value = parse_r9d_offset_assignment(assignment.mnemonic, assignment.op_str, zeroed_registers)
    return value, assignment.mnemonic + " " + assignment.op_str


def _field_record(image: PeImage, instructions, name_site: int, offset_site: int,
                  attach_call_site: int, property_name: str,
                  enum_initializer_site: int | None = None) -> dict:
    by_rva = _instruction_map(instructions)
    name_instruction = by_rva[name_site]
    name_rva = _rip_target(name_instruction)
    if name_rva is None or image.read_c_string(image.image_base + name_rva) != property_name:
        raise ValueError("property-name LEA does not resolve to " + property_name)
    offset, offset_instruction = _field_offset_from_r9d_assignment(
        instructions, offset_site, attach_call_site
    )
    construction_calls = [
        instruction for instruction in instructions
        if _call_target(instruction) == PROPERTY_CONSTRUCTION_HELPER_RVA
        and instruction.address > name_site
        and instruction.address < attach_call_site
    ]
    if not construction_calls:
        raise ValueError("property construction call not found for " + property_name)
    record = {
        "name": property_name,
        "name_reference": {
            "site_rva": hex(name_site),
            "name_rva": hex(name_rva),
            "instruction": name_instruction.mnemonic + " " + name_instruction.op_str,
        },
        "offset_candidate": offset,
        "offset_setup": {
            "site_rva": hex(offset_site),
            "instruction": offset_instruction,
        },
        "property_offset_attach_call": {
            "site_rva": hex(attach_call_site),
            "target_rva": hex(PROPERTY_OFFSET_HELPER_RVA),
            "instruction": by_rva[attach_call_site].mnemonic + " " + by_rva[attach_call_site].op_str,
        },
    }
    if enum_initializer_site is not None:
        enum_init = by_rva[enum_initializer_site]
        enum_target = _call_target(enum_init)
        if enum_target != ENUM_INITIALIZER_RVA:
            raise ValueError("Comparison enum initializer call mismatch")
        record["enum_initializer_call"] = {
            "site_rva": hex(enum_initializer_site),
            "target_rva": hex(enum_target),
            "instruction": enum_init.mnemonic + " " + enum_init.op_str,
        }
    return record


def build_report(executable: Path) -> dict:
    image = PeImage(executable)
    digest = sha256_file(image.path)
    if digest != EXPECTED_IMAGE_SHA256:
        raise ValueError("executable SHA256 does not match fixed target: " + digest)

    records = _runtime_function_records(image)
    ranges = {
        root: chained_ranges_for_root(records, root)
        for root in (
            COMMUNITY_INITIALIZER_RVA,
            COMMUNITY_CLASS_REGISTRATION_RVA,
            BASE_CLASS_REGISTRATION_RVA,
            BASE_PROPERTY_INITIALIZER_RVA,
        )
    }
    decoded = {root: _instructions_for_ranges(image, body) for root, body in ranges.items()}
    community_init = decoded[COMMUNITY_INITIALIZER_RVA]
    community_calls = [
        {"site_rva": hex(instruction.address), "target_rva": hex(_call_target(instruction)),
         "instruction": instruction.mnemonic + " " + instruction.op_str}
        for instruction in community_init if instruction.mnemonic == "call"
        and _call_target(instruction) in {BASE_PROPERTY_INITIALIZER_RVA, COMMUNITY_CLASS_REGISTRATION_RVA}
    ]
    expected_calls = {
        BASE_PROPERTY_INITIALIZER_RVA: "0xfc7c71",
        COMMUNITY_CLASS_REGISTRATION_RVA: "0xfc7c82",
    }
    if {int(row["target_rva"], 16): row["site_rva"] for row in community_calls} != {
        target: site for target, site in expected_calls.items()
    }:
        raise ValueError("CommunityMissionCondition initializer dependency calls changed")

    base_registration = _registration_record(
        image, decoded[BASE_CLASS_REGISTRATION_RVA], BASE_CLASS_REGISTRATION_RVA,
        0xA42E24, "UMissionCondition"
    )
    community_registration = _registration_record(
        image, decoded[COMMUNITY_CLASS_REGISTRATION_RVA], COMMUNITY_CLASS_REGISTRATION_RVA,
        0xA2F92B, "UCommunityMissionCondition"
    )
    fields = [
        _field_record(
            image, decoded[BASE_PROPERTY_INITIALIZER_RVA],
            0xF321E5, 0xF32226, 0xF32238, "Value"
        ),
        _field_record(
            image, decoded[BASE_PROPERTY_INITIALIZER_RVA],
            0xF3226D, 0xF322A7, 0xF322BB, "Comparison",
            enum_initializer_site=0xF32292,
        ),
        _field_record(
            image, community_init,
            0xFC7CB5, 0xFC7D06, 0xFC7D18, "ComparisonStat"
        ),
    ]
    community_size = community_registration["registered_size_argument_candidate"]
    if [row["offset_candidate"] for row in fields] != [0x2C, 0x28, 0x30]:
        raise ValueError("unexpected CommunityMissionCondition field offsets")
    if community_size != 0x38 or max(row["offset_candidate"] for row in fields) >= community_size:
        raise ValueError("field offsets do not fit the class-registration size candidate")

    return {
        "schema": 1,
        "target": "target.json",
        "target_sha256": digest,
        "scope": {
            "game_process_started_or_attached": False,
            "executable_name": image.path.name,
        },
        "method": "Decode the fixed-build class initializer, native class-name registration stubs, and field property-offset construction calls over CHAININFO-linked .pdata ranges.",
        "community_initializer": {
            "root_rva": hex(COMMUNITY_INITIALIZER_RVA),
            "direct_dependency_calls": community_calls,
            "association_note": "The initializer calls the Value/Comparison property initializer before registering UCommunityMissionCondition, then registers ComparisonStat in the same body. The source does not expose a symbolic field-owner token for the first two descriptors, so their association is a static initializer-chain inference.",
        },
        "class_registrations": {
            "UMissionCondition": base_registration,
            "UCommunityMissionCondition": community_registration,
        },
        "field_layout_candidates": fields,
        "layout_inference": {
            "candidate_class": "UCommunityMissionCondition",
            "candidate_size_argument": community_size,
            "field_offsets_by_name": {row["name"]: row["offset_candidate"] for row in fields},
            "confidence": "strong-static-initializer-chain-inference",
            "reason": "The named Comparison, Value, and ComparisonStat registrations attach at offsets 0x28, 0x2c, and 0x30; the same initializer prepares the first two descriptors, registers UCommunityMissionCondition, and attaches ComparisonStat; the class-registration size argument is 0x38.",
        },
        "default_value_status": {
            "Comparison": "unresolved",
            "reason": "Property offset and enum type registration do not reveal a CDO value. This report does not identify the CDO constructor callback semantics or decode a default object value.",
        },
        "limits": [
            "The generic class-registration helper is identified by its direct instruction target, but C++ type hierarchy and constructor callback roles are not reconstructed here.",
            "The property owner of Value and Comparison is associated with UCommunityMissionCondition by initializer composition; the serialized property descriptors do not provide a symbolic owner label in this report.",
            "The class-size immediate is recorded as a registration argument candidate, not a runtime sizeof observation.",
            "No class-default object value is recovered; the omitted Comparison semantics remain unresolved.",
            "No live game process or memory was accessed.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("executable", type=Path, help="local fixed-version StateOfDecay2-Win64-Shipping.exe")
    parser.add_argument("--output", type=Path, default=DATABASE / "community-mission-condition-native-layout.json")
    args = parser.parse_args()
    report = build_report(args.executable)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("PASS: decoded UCommunityMissionCondition registration chain and 3 field-offset candidates; default Comparison remains unresolved")


if __name__ == "__main__":
    main()
