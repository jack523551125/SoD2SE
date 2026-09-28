#!/usr/bin/env python3
"""Statically map selected Iggy runtime exports and their fragmented x64 control flow."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
from collections import deque
from pathlib import Path
from typing import Any, Callable

from capstone import CS_ARCH_X86, CS_GRP_JUMP, CS_GRP_RET, CS_MODE_64, Cs
from capstone.x86_const import X86_INS_JMP, X86_OP_IMM

from pe_static import PeImage


PINNED_DLL_SHA256 = "09049ffc7b48639c72336bb809035fa1c1b827e898693fbc2968165bd23940a6"
SELECTED_EXPORTS = (
    "IggyLibraryCreateFromMemory",
    "IggyPlayerCreateFromMemory",
    "IggyPlayerCallFunctionRS",
    "IggyPlayerCallMethodRS",
    "IggyPlayerDispatchEventRS",
    "IggyPlayerGetFocusableObjects",
    "IggyPlayerSetFocusRS",
    "IggyValueRefCreateEmptyObject",
    "IggyValueRefCreateArray",
    "IggyValueRefFromPath",
    "IggyValuePathSetParent",
)


def read_export_rows(image: PeImage) -> list[dict[str, Any]]:
    data = image.data
    pe_offset = struct.unpack_from("<I", data, 0x3C)[0]
    optional = pe_offset + 24
    directory_rva, directory_size = struct.unpack_from("<II", data, optional + 112)
    if not directory_rva or directory_size < 40:
        raise ValueError("DLL has no complete export directory")
    directory = image.rva_to_offset(directory_rva, 40)
    fields = struct.unpack_from("<IIHHIIIIIII", data, directory)
    ordinal_base, function_count, name_count = fields[5], fields[6], fields[7]
    functions_rva, names_rva, ordinals_rva = fields[8], fields[9], fields[10]
    if function_count > 100000 or name_count > function_count:
        raise ValueError("Implausible DLL export count")
    functions = struct.unpack_from(
        "<" + "I" * function_count,
        data,
        image.rva_to_offset(functions_rva, function_count * 4),
    )
    name_rvas = struct.unpack_from(
        "<" + "I" * name_count,
        data,
        image.rva_to_offset(names_rva, name_count * 4),
    )
    name_ordinals = struct.unpack_from(
        "<" + "H" * name_count,
        data,
        image.rva_to_offset(ordinals_rva, name_count * 2),
    )
    rows = []
    for name_rva, ordinal_index in zip(name_rvas, name_ordinals):
        name_offset = image.rva_to_offset(name_rva)
        name_end = data.find(b"\0", name_offset, name_offset + 1024)
        if name_end < 0:
            raise ValueError("Unterminated DLL export name")
        name = data[name_offset:name_end].decode("ascii")
        function_rva = functions[ordinal_index]
        rows.append(
            {
                "name": name,
                "ordinal": ordinal_base + ordinal_index,
                "rva": function_rva,
                "is_forwarder": directory_rva <= function_rva < directory_rva + directory_size,
            }
        )
    return rows


def trace_x64_cfg(
    start_rva: int,
    *,
    read_code: Callable[[int, int], bytes],
    is_executable: Callable[[int], bool],
    max_blocks: int = 512,
    max_instructions: int = 12000,
) -> dict[str, Any]:
    """Follow bounded direct conditional/unconditional branches, without running code."""
    md = Cs(CS_ARCH_X86, CS_MODE_64)
    md.detail = True
    pending = deque([start_rva])
    visited: set[int] = set()
    instructions: dict[int, Any] = {}
    branches: list[dict[str, Any]] = []
    calls: list[dict[str, Any]] = []
    block_count = 0
    while pending and block_count < max_blocks and len(instructions) < max_instructions:
        address = pending.popleft()
        block_count += 1
        while len(instructions) < max_instructions and address not in visited:
            if not is_executable(address):
                break
            code = read_code(address, 15)
            instruction = next(md.disasm(code, address, count=1), None)
            if instruction is None:
                break
            visited.add(address)
            instructions[address] = instruction
            if instruction.mnemonic == "call" and instruction.operands:
                operand = instruction.operands[0]
                if operand.type == X86_OP_IMM:
                    calls.append(
                        {"site_rva": instruction.address, "target_rva": operand.imm}
                    )
            if instruction.group(CS_GRP_JUMP):
                target = None
                if instruction.operands and instruction.operands[0].type == X86_OP_IMM:
                    target = instruction.operands[0].imm
                branches.append(
                    {
                        "site_rva": instruction.address,
                        "target_rva": target,
                        "mnemonic": instruction.mnemonic,
                        "unconditional": instruction.id == X86_INS_JMP,
                    }
                )
                if target is not None and is_executable(target):
                    pending.append(target)
                if instruction.id == X86_INS_JMP:
                    break
            if instruction.group(CS_GRP_RET) or instruction.mnemonic in {"int3", "ud2"}:
                break
            address = instruction.address + instruction.size
    if pending:
        raise ValueError("Control-flow walk exceeded configured static-analysis bounds")
    return {
        "instruction_count": len(instructions),
        "basic_block_count": block_count,
        "instructions": instructions,
        "direct_calls": sorted(calls, key=lambda row: row["site_rva"]),
        "branches": sorted(branches, key=lambda row: row["site_rva"]),
    }


def contiguous_instruction_ranges(instructions: dict[int, Any]) -> list[dict[str, int]]:
    addresses = sorted(instructions)
    if not addresses:
        return []
    ranges: list[dict[str, int]] = []
    start = previous = addresses[0]
    count = 1
    for address in addresses[1:]:
        if address == previous + instructions[previous].size:
            previous = address
            count += 1
            continue
        ranges.append(
            {"start_rva": start, "end_rva": previous + instructions[previous].size, "instruction_count": count}
        )
        start = previous = address
        count = 1
    ranges.append(
        {"start_rva": start, "end_rva": previous + instructions[previous].size, "instruction_count": count}
    )
    return ranges


def build_report(dll_path: Path) -> dict[str, Any]:
    image = PeImage(dll_path)
    dll_sha256 = hashlib.sha256(image.data).hexdigest()
    if dll_sha256 != PINNED_DLL_SHA256:
        raise ValueError(f"Iggy runtime DLL hash mismatch: expected {PINNED_DLL_SHA256}, got {dll_sha256}")
    export_rows = read_export_rows(image)
    exports_by_name = {row["name"]: row for row in export_rows}
    missing = set(SELECTED_EXPORTS).difference(exports_by_name)
    if missing:
        raise ValueError("Pinned Iggy DLL is missing exports: " + ", ".join(sorted(missing)))

    def read_code(rva: int, length: int) -> bytes:
        section = image.section_for_rva(rva)
        if section is None or not section.is_executable:
            return b""
        bounded_length = min(length, section.virtual_address + section.raw_size - rva)
        if bounded_length <= 0:
            return b""
        offset = image.rva_to_offset(rva, bounded_length)
        return image.data[offset : offset + bounded_length]

    analyzed = []
    exported_rvas = {row["rva"]: row["name"] for row in export_rows}
    for name in SELECTED_EXPORTS:
        export = exports_by_name[name]
        if export["is_forwarder"]:
            raise ValueError(f"Expected code export {name} is a forwarder")
        cfg = trace_x64_cfg(
            export["rva"],
            read_code=read_code,
            is_executable=lambda rva: bool(
                (section := image.section_for_rva(rva)) and section.is_executable
            ),
        )
        pdata = image.function_containing(export["rva"])
        direct_calls = []
        for call in cfg["direct_calls"]:
            target = call["target_rva"]
            target_function = image.function_containing(target)
            direct_calls.append(
                {
                    "site_rva": call["site_rva"],
                    "target_rva": target,
                    "target_export": exported_rvas.get(target),
                    "target_pdata_range": (
                        [target_function[0], target_function[1]] if target_function else None
                    ),
                }
            )
        analyzed.append(
            {
                "name": name,
                "export_rva": export["rva"],
                "entry_pdata_range": list(pdata) if pdata else None,
                "reachable_instruction_count": cfg["instruction_count"],
                "reachable_code_ranges": contiguous_instruction_ranges(cfg["instructions"]),
                "direct_calls": direct_calls,
                "direct_branch_count": len(cfg["branches"]),
            }
        )

    export_names = [row["name"] for row in export_rows]
    display_tree_mutation_terms = re.compile(
        r"(?:display.?object|movieclip|sprite|child|button)", re.IGNORECASE
    )
    explicit_mutation_verbs = re.compile(
        r"(?:add|create|insert|attach|remove|delete|append|push)", re.IGNORECASE
    )
    named_display_mutation_candidates = [
        name
        for name in export_names
        if display_tree_mutation_terms.search(name) and explicit_mutation_verbs.search(name)
    ]
    focus_export = next(row for row in analyzed if row["name"] == "IggyPlayerGetFocusableObjects")
    focus_insns = trace_x64_cfg(
        exports_by_name["IggyPlayerGetFocusableObjects"]["rva"],
        read_code=read_code,
        is_executable=lambda rva: bool(
            (section := image.section_for_rva(rva)) and section.is_executable
        ),
    )["instructions"]
    focus_instruction_text = {
        f"0x{address:X}": f"{instruction.mnemonic} {instruction.op_str}"
        for address, instruction in focus_insns.items()
    }
    expected_focus_patterns = {
        "count_initialized_to_zero": any(
            text == "xor r11d, r11d" for text in focus_instruction_text.values()
        )
        and "mov dword ptr [rbx], r11d" in focus_instruction_text.values(),
        "optional_player_context_pointer_copied": "mov rax, qword ptr [rcx + 0x29f8]" in focus_instruction_text.values()
        and "mov qword ptr [rdx], rax" in focus_instruction_text.values(),
        "focus_record_stride_24_bytes": "add r8, 0x18" in focus_instruction_text.values(),
        "output_copies_existing_object_fields": all(
            any(text == f"mov eax, dword ptr [rcx + 0x{offset:x}]" for text in focus_instruction_text.values())
            for offset in (0xC8, 0xCC, 0xD0, 0xD4)
        ),
        "walks_existing_object_links": all(
            any(
                text == f"mov rax, qword ptr [rcx + {offset}]"
                or text == f"mov rax, qword ptr [rcx + 0x{offset:x}]"
                for text in focus_instruction_text.values()
            )
            for offset in (0x8, 0x10)
        ),
    }
    if not all(expected_focus_patterns.values()):
        failed = ", ".join(name for name, matched in expected_focus_patterns.items() if not matched)
        raise ValueError(
            "Pinned GetFocusableObjects implementation did not match static expectations: "
            + failed
        )
    for name, call_target in (
        ("IggyPlayerCallFunctionRS", 0xB2520),
        ("IggyPlayerCallMethodRS", 0xB29C0),
    ):
        row = next(item for item in analyzed if item["name"] == name)
        if call_target not in {call["target_rva"] for call in row["direct_calls"]}:
            raise ValueError(f"{name} did not reach the expected internal call dispatcher")
    return {
        "schema": 1,
        "target_build": 16535856,
        "dll_name": dll_path.name,
        "dll_sha256": dll_sha256,
        "export_count": len(export_rows),
        "scope": "Read-only x64 export/control-flow analysis; no DLL loading, invocation, injection, or game-process access.",
        "export_surface": {
            "script_call_exports": [
                name for name in ("IggyPlayerCallFunctionRS", "IggyPlayerCallMethodRS") if name in exports_by_name
            ],
            "focus_exports": [
                name for name in ("IggyPlayerGetFocusableObjects", "IggyPlayerSetFocusRS") if name in exports_by_name
            ],
            "movie_creation_exports": [
                name for name in ("IggyLibraryCreateFromMemory", "IggyPlayerCreateFromMemory") if name in exports_by_name
            ],
            "explicit_display_tree_mutation_name_candidates": named_display_mutation_candidates,
            "name_scan_limitation": "Export-name absence does not rule out script-call-based mutation or undocumented interfaces.",
        },
        "analyzed_exports": analyzed,
        "focus_enumeration_observations": {
            "export_rva": focus_export["export_rva"],
            "static_patterns_verified": expected_focus_patterns,
            "interpretation": "The function traverses existing runtime objects and writes focus records to caller-provided storage; it is an enumeration/focus facility, not evidence of a display-object constructor or insertion API.",
        },
        "capability_conclusion": "The pinned DLL exposes generic script function/method dispatch, movie creation from memory, and focus enumeration/set APIs. Static export names reveal no explicit display-tree add/create/insert API, but this does not prove that a script-call route is impossible. No current evidence supplies the required mod-page display object, callback code, or safe asset insertion contract.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dll", type=Path, required=True, help="Pinned iggy_w64.dll")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = build_report(args.dll)
    except (OSError, ValueError, struct.error) as error:
        parser.error(str(error))
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"PASS: mapped {len(report['analyzed_exports'])} pinned Iggy API exports and their direct control flow")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
