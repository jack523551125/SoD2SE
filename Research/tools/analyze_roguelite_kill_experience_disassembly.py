#!/usr/bin/env python3
"""Record focused machine-code call and indirect-dispatch evidence offline.

The report contains decoded call operands and selected object-relative memory
displacements for fixed Update 38.2 entries. It deliberately does not name
anonymous objects, guess function signatures, or infer gameplay semantics.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from analyze_mission_condition_enum_native_registration import (
    _runtime_function_records,
    chained_ranges_for_root,
)
from pe_static import PeImage


ROOT = Path(__file__).resolve().parents[2]
DATABASE = ROOT / "Research" / "StateOfDecay2" / "16535856"
FOCUS = [
    {"label": "AuthAwardExperience", "rva": 0xA8AFD0, "registration": "native UFunction"},
    {"label": "AwardExperience (0xA8C600)", "rva": 0xA8C600, "registration": "native UFunction"},
    {"label": "AwardExperience (0xA8C680)", "rva": 0xA8C680, "registration": "native UFunction"},
    {"label": "anonymous AuthAwardExperience helper", "rva": 0x19E900, "registration": "anonymous native helper target"},
    {"label": "anonymous AwardExperience helper", "rva": 0x19EF80, "registration": "anonymous native helper target"},
    {"label": "AwardExperience internal helper (0x1CF910)", "rva": 0x1CF910, "registration": "anonymous native helper target"},
    {"label": "OnZombieKilled", "rva": 0xAEFD50, "registration": "native UFunction"},
    {"label": "AuthOnZombieKilled", "rva": 0xA8B590, "registration": "native UFunction"},
    {"label": "KilledZombie", "rva": 0xADA660, "registration": "native UFunction"},
    {"label": "anonymous caller of OnZombieKilled helper", "rva": 0x3C92E4, "registration": "anonymous .pdata entry"},
    {"label": "anonymous caller of AuthOnZombieKilled helper", "rva": 0x3292C7, "registration": "anonymous .pdata entry"},
    {"label": "anonymous AwardExperience caller", "rva": 0x461993, "registration": "anonymous .pdata entry"},
    {"label": "anonymous AwardExperience caller", "rva": 0x1E53AB, "registration": "anonymous .pdata entry"},
    {"label": "anonymous AwardExperience caller", "rva": 0x276E80, "registration": "anonymous .pdata entry"},
]
FOCUSED_DISPLACEMENTS = {0x20, 0xB00, 0xB88}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _target_rva(immediate: int, image: PeImage) -> int | None:
    if image.section_for_rva(immediate):
        return immediate
    candidate = immediate - image.image_base
    if candidate >= 0 and image.section_for_rva(candidate):
        return candidate
    return None


def summarize_entry(image: PeImage, decoder, capstone, runtime_records: list, entry: dict) -> dict:
    rva = entry["rva"]
    function_range = image.function_containing(rva)
    if function_range is None:
        raise ValueError("focused address has no executable .pdata range: 0x%X" % rva)
    chain_ranges = chained_ranges_for_root(runtime_records, rva)
    if not chain_ranges:
        raise ValueError("focused address has no unwind range chain: 0x%X" % rva)
    decoded = []
    for range_row in chain_ranges:
        start = range_row["begin_rva"]
        end = range_row["end_exclusive_rva"]
        size = end - start
        section = image.section_for_rva(start, size)
        if not section or not section.is_executable:
            raise ValueError("focused range resolves outside executable section: 0x%X" % start)
        offset = image.rva_to_offset(start, size)
        range_decoded = list(decoder.disasm(image.data[offset : offset + size], start))
        decoded_bytes = sum(instruction.size for instruction in range_decoded)
        if decoded_bytes != size:
            raise ValueError("partial decode for focused range 0x%X-0x%X" % (start, end))
        decoded.extend(range_decoded)

    direct_calls = []
    indirect_calls = []
    focused_memory_displacements = []
    for instruction in decoded:
        if instruction.group(capstone.CS_GRP_CALL):
            if instruction.operands and instruction.operands[0].type == capstone.CS_OP_IMM:
                target_rva = _target_rva(instruction.operands[0].imm, image)
                direct_calls.append({
                    "site_rva": hex(instruction.address),
                    "target_rva": hex(target_rva) if target_rva is not None else None,
                    "operand": instruction.op_str,
                })
            else:
                indirect_calls.append({
                    "site_rva": hex(instruction.address),
                    "operand": instruction.op_str,
                })
        for operand in instruction.operands:
            if operand.type != capstone.CS_OP_MEM or operand.mem.disp not in FOCUSED_DISPLACEMENTS:
                continue
            focused_memory_displacements.append({
                "site_rva": hex(instruction.address),
                "mnemonic": instruction.mnemonic,
                "operand": instruction.op_str,
                "base_register": instruction.reg_name(operand.mem.base) if operand.mem.base else None,
                "displacement": hex(operand.mem.disp),
            })

    return {
        **entry,
        "rva": hex(rva),
        "pdata_range_rva": {
            "start": hex(function_range[0]),
            "end_exclusive": hex(function_range[1]),
        },
        "pdata_ranges_rva": [
            {"start": hex(row["begin_rva"]), "end_exclusive": hex(row["end_exclusive_rva"])}
            for row in chain_ranges
        ],
        "decoded_pdata_range_count": len(chain_ranges),
        "instruction_count": len(decoded),
        "direct_calls": direct_calls,
        "indirect_calls": indirect_calls,
        "selected_memory_displacement_references": focused_memory_displacements,
    }


def build_report(executable: Path) -> dict:
    try:
        import capstone
    except ImportError as error:
        raise SystemExit("Capstone 5.0.7 is required; install Research/tools/requirements.txt") from error

    image = PeImage(executable)
    decoder = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    decoder.detail = True
    runtime_records = _runtime_function_records(image)
    return {
        "schema": 1,
        "target": "target.json",
        "target_sha256": sha256_file(image.path),
        "method": "Decode the listed .pdata function ranges and CHAININFO-linked fragments with Capstone; record direct/indirect CALL operands and selected displacement references. No live process is accessed.",
        "scope": {
            "game_process_started_or_attached": False,
            "function_count": len(FOCUS),
            "selected_displacements": [hex(value) for value in sorted(FOCUSED_DISPLACEMENTS)],
        },
        "functions": [summarize_entry(image, decoder, capstone, runtime_records, entry) for entry in FOCUS],
        "limits": [
            "Anonymous entries and object-relative offsets are not assigned class, member, parameter, or gameplay meanings.",
            "CHAININFO fragments are combined by unwind metadata. The report captures direct and indirect call sites only within the listed functions; it is not a transitive or complete call graph.",
            "A matching direct call relationship does not prove kill attribution, XP reward semantics, authority, or de-duplication behavior.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("executable", type=Path, help="local fixed-version StateOfDecay2-Win64-Shipping.exe")
    parser.add_argument("--output", type=Path, default=DATABASE / "roguelite-kill-experience-disassembly.json")
    args = parser.parse_args()
    report = build_report(args.executable)
    expected = json.loads((DATABASE / "target.json").read_text(encoding="utf-8"))["sha256"].upper()
    if report["target_sha256"] != expected:
        raise SystemExit("executable SHA256 does not match Research/StateOfDecay2/16535856/target.json")
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    direct_count = sum(len(row["direct_calls"]) for row in report["functions"])
    indirect_count = sum(len(row["indirect_calls"]) for row in report["functions"])
    print("PASS: %d focused function bodies; %d direct and %d indirect calls" % (len(report["functions"]), direct_count, indirect_count))


if __name__ == "__main__":
    main()
