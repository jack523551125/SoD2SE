#!/usr/bin/env python3
"""Instruction-confirm incoming direct calls to fixed-build recruitment helpers.

The scanner uses raw E8/E9 bytes only to locate candidate caller functions.
Every reported edge must decode to an exact x64 call/jump target inside a
PE .pdata-bounded executable body. It reads the local EXE and never starts,
attaches to, or writes to the game.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
import struct
import sys
from pathlib import Path

from pe_static import PeImage


ROOT = Path(__file__).resolve().parents[2]
DATABASE = ROOT / "Research" / "StateOfDecay2" / "16535856"
TARGETS = (
    {"id": "can-add-character", "name": "CanAddCharacter implementation", "rva": 0x276360},
    {"id": "can-add-characters", "name": "CanAddCharacters implementation", "rva": 0x2763A0},
    {"id": "population-count-helper", "name": "shared population-count helper", "rva": 0x27D150},
    {"id": "remaining-availability", "name": "remaining recruitment availability", "rva": 0x27ADC0},
    {"id": "soft-cap-query", "name": "population soft-cap query", "rva": 0x281540},
    {"id": "try-add-character", "name": "TryAddCharacter append routine", "rva": 0x290630},
    {"id": "try-add-character-record", "name": "TryAddCharacterRecord append routine", "rva": 0x290710},
    {"id": "restore-exiled-character", "name": "restore exiled character routine", "rva": 0x290F50},
    {"id": "transfer-character", "name": "transfer character routine", "rva": 0x2919D0},
)
MAX_BODY_BYTES = 256 * 1024


def _target_rva(immediate: int, image: PeImage) -> int | None:
    if image.section_for_rva(immediate):
        return immediate
    rva = immediate - image.image_base
    return rva if rva >= 0 and image.section_for_rva(rva) else None


def raw_candidates(image: PeImage, target_rvas: set[int]):
    """Find possible rel32 call/jump sites; results are not edges until decoded."""
    candidates = {target: [] for target in target_rvas}
    for section in image.sections:
        if not section.is_executable or section.raw_size < 5:
            continue
        code = image.data[section.raw_offset : section.raw_offset + section.raw_size]
        for offset in range(len(code) - 4):
            opcode = code[offset]
            if opcode not in (0xE8, 0xE9):
                continue
            site_rva = section.virtual_address + offset
            destination = site_rva + 5 + struct.unpack_from("<i", code, offset + 1)[0]
            if destination in candidates:
                candidates[destination].append((opcode, site_rva))
    return candidates


def audit(image: PeImage, capstone_module, target_rows=TARGETS) -> dict:
    target_rvas = {row["rva"] for row in target_rows}
    candidates = raw_candidates(image, target_rvas)
    candidate_functions: dict[tuple[int, int], set[int]] = defaultdict(set)
    unbounded = {target: [] for target in target_rvas}
    for target_rva, sites in candidates.items():
        for _opcode, site_rva in sites:
            function = image.function_containing(site_rva)
            if function is None:
                unbounded[target_rva].append(site_rva)
            else:
                candidate_functions[function].add(target_rva)

    names_by_rva: dict[int, set[str]] = defaultdict(set)
    for row in image.iter_native_pairs():
        names_by_rva[int(row["func_rva"], 16)].add(row["name"])

    md = capstone_module.Cs(capstone_module.CS_ARCH_X86, capstone_module.CS_MODE_64)
    md.detail = True
    calls = {target: [] for target in target_rvas}
    jumps = {target: [] for target in target_rvas}
    skipped = {target: [] for target in target_rvas}
    decoded_functions = 0
    for (start, end), targets_in_function in sorted(candidate_functions.items()):
        if end - start > MAX_BODY_BYTES:
            for target in targets_in_function:
                skipped[target].append({"function_start_rva": hex(start), "reason": "body-size-limit"})
            continue
        try:
            offset = image.rva_to_offset(start, end - start)
        except ValueError:
            for target in targets_in_function:
                skipped[target].append({"function_start_rva": hex(start), "reason": "range-not-file-backed"})
            continue
        decoded_functions += 1
        for instruction in md.disasm(image.data[offset : offset + end - start], start):
            if not instruction.operands or not (
                instruction.group(capstone_module.CS_GRP_CALL)
                or instruction.group(capstone_module.CS_GRP_JUMP)
            ):
                continue
            operand = instruction.operands[0]
            if operand.type != capstone_module.CS_OP_IMM:
                continue
            target_rva = _target_rva(operand.imm, image)
            if target_rva not in targets_in_function:
                continue
            edge = {
                "site_rva": hex(instruction.address),
                "caller_range_rva": {"start": hex(start), "end_exclusive": hex(end)},
                "caller_names_at_entry": sorted(names_by_rva.get(start, set())),
                "instruction": instruction.mnemonic,
            }
            if instruction.group(capstone_module.CS_GRP_CALL):
                calls[target_rva].append(edge)
            elif instruction.group(capstone_module.CS_GRP_JUMP):
                jumps[target_rva].append(edge)

    results = []
    for row in target_rows:
        target_rva = row["rva"]
        target_function = image.function_containing(target_rva)
        raw_call_sites = [hex(site) for opcode, site in candidates[target_rva] if opcode == 0xE8]
        raw_jump_sites = [hex(site) for opcode, site in candidates[target_rva] if opcode == 0xE9]
        confirmed_calls = sorted(calls[target_rva], key=lambda edge: int(edge["site_rva"], 16))
        confirmed_jumps = sorted(jumps[target_rva], key=lambda edge: int(edge["site_rva"], 16))
        unresolved = sorted(unbounded[target_rva])
        results.append(
            {
                **row,
                "target_function_range_rva": (
                    {"start": hex(target_function[0]), "end_exclusive": hex(target_function[1])}
                    if target_function else None
                ),
                "target_in_pdata_function": target_function is not None,
                "raw_e8_candidate_count": len(raw_call_sites),
                "verified_direct_call_count": len(confirmed_calls),
                "verified_direct_callers": confirmed_calls,
                "raw_e9_candidate_count": len(raw_jump_sites),
                "verified_tail_jump_count": len(confirmed_jumps),
                "verified_tail_jumps": confirmed_jumps,
                "raw_candidates_without_pdata_range": [hex(site) for site in unresolved],
                "candidate_functions_skipped": sorted(skipped[target_rva], key=lambda item: item["function_start_rva"]),
                "complete_for_bounded_direct_edges": (
                    target_function is not None and not unresolved and not skipped[target_rva]
                ),
            }
        )

    return {
        "schema": 1,
        "target": "target.json",
        "target_sha256": hashlib.sha256(image.data).hexdigest().upper(),
        "method": "Raw E8/E9 bytes locate possible callers; Capstone must confirm an exact direct CALL/JMP immediate at that instruction boundary inside a .pdata-bounded executable function body.",
        "limits": [
            "Only direct relative CALL and tail-JMP edges are included; indirect, virtual, ProcessEvent, delegate, and data-driven dispatch are unresolved.",
            "A complete direct-edge result does not prove call semantics, ownership, save/load behavior, or runtime reachability.",
            "Raw opcode matches are candidate locations only and are excluded unless Capstone confirms the instruction and exact target.",
        ],
        "statistics": {
            "target_count": len(results),
            "decoded_candidate_caller_functions": decoded_functions,
            "verified_direct_calls": sum(row["verified_direct_call_count"] for row in results),
            "verified_tail_jumps": sum(row["verified_tail_jump_count"] for row in results),
            "raw_candidates_without_pdata_range": sum(len(row["raw_candidates_without_pdata_range"]) for row in results),
        },
        "targets": results,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("executable", type=Path, help="local fixed-version SoD2 EXE")
    parser.add_argument("--database", type=Path, default=DATABASE)
    parser.add_argument("--output", type=Path, help="defaults to community-recruitment-native-xrefs.json")
    args = parser.parse_args(argv)
    try:
        import capstone
    except ImportError as error:
        parser.error("Capstone is required for instruction-boundary verification (%s)" % error)

    target_doc = json.loads((args.database / "target.json").read_text(encoding="utf-8"))
    image = PeImage(args.executable)
    digest = hashlib.sha256(image.data).hexdigest().upper()
    if digest != str(target_doc.get("sha256", "")).upper():
        parser.error("EXE SHA256 does not match the fixed research target")
    report = audit(image, capstone)
    output = args.output or (args.database / "community-recruitment-native-xrefs.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        "PASS: %d recruitment targets, %d direct calls and %d tail jumps verified; wrote %s"
        % (len(report["targets"]), report["statistics"]["verified_direct_calls"],
           report["statistics"]["verified_tail_jumps"], output)
    )
    print("Static file analysis only; no game process was started or attached.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
