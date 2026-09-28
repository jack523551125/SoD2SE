#!/usr/bin/env python3
"""Scan focused anonymous progression entries for non-branch address refs.

The scan checks decoded executable .pdata instructions for immediate and
RIP-relative references, then scans non-executable section bytes for absolute
VA and 32-bit RVA patterns. Matches are candidates, not proof of a callable
function pointer or runtime use.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import struct

from analyze_all_pdata_direct_call_xrefs import sha256_file
from analyze_roguelite_native_followups import FOCUS_SOURCES
from pe_static import PeImage


ROOT = Path(__file__).resolve().parents[2]
DATABASE = ROOT / "Research" / "StateOfDecay2" / "16535856"
FOCUS_RVAS = {int(row["target_rva"], 16) for row in FOCUS_SOURCES}


def normalize_address(value: int, image: PeImage) -> int | None:
    if image.section_for_rva(value):
        return value
    rva = value - image.image_base
    if rva >= 0 and image.section_for_rva(rva):
        return rva
    return None


def _find_all(haystack: bytes, needle: bytes):
    start = 0
    while True:
        offset = haystack.find(needle, start)
        if offset < 0:
            return
        yield offset
        start = offset + 1


def scan_data_pointer_patterns(image: PeImage, target_rvas: set[int]) -> dict[int, dict[str, list[dict]]]:
    """Find literal VA qwords and RVA dwords outside executable/unwind data."""
    found = {
        target: {"absolute_va_qword_candidates": [], "rva_dword_candidates": []}
        for target in target_rvas
    }
    exception_section = None
    exception_rva = getattr(image, "exception_rva", 0)
    section_for_rva = getattr(image, "section_for_rva", None)
    if exception_rva and section_for_rva:
        exception_section = section_for_rva(exception_rva)
    for section in image.sections:
        if section.is_executable or not section.raw_size or section == exception_section:
            continue
        data = image.data[section.raw_offset : section.raw_offset + section.raw_size]
        for target in target_rvas:
            needles = (
                ("absolute_va_qword_candidates", struct.pack("<Q", image.image_base + target), "absolute-va-qword-pattern"),
                ("rva_dword_candidates", struct.pack("<I", target), "rva-dword-pattern"),
            )
            for key, needle, encoding in needles:
                for offset in _find_all(data, needle):
                    found[target][key].append({
                        "section": section.name,
                        "site_rva": hex(section.virtual_address + offset),
                        "byte_offset": offset,
                        "encoding_candidate": encoding,
                        "target_is_executable": image.is_executable_va(image.image_base + target),
                    })
    return found


def scan_instruction_references(image: PeImage, capstone_module, target_rvas: set[int]) -> dict[int, list[dict]]:
    """Find non-CALL/JMP immediate and RIP-relative operand references."""
    md = capstone_module.Cs(capstone_module.CS_ARCH_X86, capstone_module.CS_MODE_64)
    md.detail = True
    md.skipdata = False
    found = {target: [] for target in target_rvas}
    for start, end in image.function_ranges:
        size = end - start
        section = image.section_for_rva(start, size)
        if section is None or not section.is_executable:
            continue
        try:
            offset = image.rva_to_offset(start, size)
        except ValueError:
            continue
        body = image.data[offset : offset + size]
        for insn in md.disasm(body, start):
            if insn.group(capstone_module.CS_GRP_CALL) or insn.group(capstone_module.CS_GRP_JUMP):
                continue
            for operand_index, operand in enumerate(insn.operands):
                rva = None
                reference_kind = None
                if operand.type == capstone_module.CS_OP_IMM:
                    rva = normalize_address(operand.imm, image)
                    reference_kind = "immediate-address"
                elif (
                    operand.type == capstone_module.CS_OP_MEM
                    and operand.mem.base == capstone_module.x86_const.X86_REG_RIP
                ):
                    rva = insn.address + insn.size + operand.mem.disp
                    reference_kind = "rip-relative-address"
                if rva not in target_rvas:
                    continue
                found[rva].append({
                    "site_rva": hex(insn.address),
                    "instruction": insn.mnemonic + " " + insn.op_str,
                    "operand_index": operand_index,
                    "reference_kind": reference_kind,
                    "function_start_rva": hex(start),
                })
    return found


def build_report(executable: Path) -> dict:
    try:
        import capstone
    except ImportError as error:
        raise SystemExit("Capstone 5.0.7 is required; install Research/tools/requirements.txt") from error

    image = PeImage(executable)
    instruction_refs = scan_instruction_references(image, capstone, FOCUS_RVAS)
    data_refs = scan_data_pointer_patterns(image, FOCUS_RVAS)
    source_by_rva = {int(row["target_rva"], 16): row for row in FOCUS_SOURCES}
    targets = []
    for rva in sorted(FOCUS_RVAS):
        targets.append({
            **source_by_rva[rva],
            "non_branch_instruction_reference_count": len(instruction_refs[rva]),
            "non_branch_instruction_references": instruction_refs[rva],
            **data_refs[rva],
        })
    return {
        "schema": 1,
        "target": "target.json",
        "target_sha256": sha256_file(image.path),
        "scope": {
            "game_process_started_or_attached": False,
            "executable_pdata_function_ranges": sum(
                1 for start, end in image.function_ranges
                if (section := image.section_for_rva(start, end - start)) and section.is_executable
            ),
            "target_count": len(targets),
            "excluded_exception_directory_section": next(
                (section.name for section in image.sections
                 if image.exception_rva and image.section_for_rva(image.exception_rva) == section),
                None,
            ),
        },
        "method": "Capstone scan of every executable .pdata body for non-branch immediate/RIP-relative references, plus raw literal VA qword and RVA dword pattern scans of non-executable sections.",
        "targets": targets,
        "limits": [
            "Literal VA/RVA matches are byte-pattern candidates and may be unrelated data; they are not proof of a function pointer or call.",
            "The scan does not resolve relative-pointer encodings other than RIP-relative instruction operands, relocations, vtables, delegates, ProcessEvent, or runtime-created references.",
            "Instructions outside executable .pdata ranges are not decoded by the instruction-reference pass.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("executable", type=Path, help="local fixed-version StateOfDecay2-Win64-Shipping.exe")
    parser.add_argument("--output", type=Path, default=DATABASE / "roguelite-native-followup-address-references.json")
    args = parser.parse_args()
    report = build_report(args.executable)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    positive = sum(
        row["non_branch_instruction_reference_count"]
        + len(row["absolute_va_qword_candidates"])
        + len(row["rva_dword_candidates"])
        for row in report["targets"]
    )
    print("PASS: scanned %d anonymous entries; found %d instruction/data reference candidates" % (len(report["targets"]), positive))


if __name__ == "__main__":
    main()
