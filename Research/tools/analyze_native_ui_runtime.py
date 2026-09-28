#!/usr/bin/env python3
"""Statically decode UI player wrappers in the fixed SoD2 executable.

The report records bounded instruction ranges and direct call edges only. It
does not invoke game code or claim undocumented UFunction semantics.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from pe_static import PeImage


FUNCTIONS = {
    "create_movie_player": 0xA9D3A0,
    "create_movie_player_filter": 0x7CB060,
    "movie_player_class_helper": 0x7CC2E0,
    "push_movie_player": 0xAFC220,
    "push_movie_player_internal": 0x7DFB80,
    "get_movie_source_path_info": 0xAC1870,
    "pass_input_to_iggy": 0xAF1D10,
}

REQUIRED_DIRECT_CALLS = {
    "create_movie_player": {0x7CB060},
    "create_movie_player_filter": {0x7CC2E0, 0xA2F090},
    "push_movie_player": {0x7DFB80},
    "push_movie_player_internal": {0x7CC2E0, 0xA2F090},
    "get_movie_source_path_info": {0x74CB20, 0x1B540D0, 0x10AB810},
    "pass_input_to_iggy": {0x759C60},
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def direct_call_targets(instructions, call_group: int, immediate_operand: int) -> list[int]:
    targets = []
    for instruction in instructions:
        if not instruction.group(call_group) or not instruction.operands:
            continue
        operand = instruction.operands[0]
        if operand.type == immediate_operand:
            targets.append(operand.imm)
    return targets


def check_required_calls(summaries: dict) -> None:
    for name, expected in REQUIRED_DIRECT_CALLS.items():
        actual = {int(value, 16) for value in summaries[name]["direct_call_targets"]}
        missing = expected - actual
        if missing:
            raise ValueError(
                "%s no longer has expected direct call edge(s): %s"
                % (name, ", ".join(hex(value) for value in sorted(missing)))
            )


def analyze(executable: Path, database: Path, capstone_module) -> dict:
    target = json.loads((database / "target.json").read_text(encoding="utf-8"))
    actual_sha = sha256_file(executable)
    expected_sha = str(target.get("sha256", "")).upper()
    if not expected_sha or actual_sha != expected_sha:
        raise ValueError("Executable SHA256 does not match fixed target.json")

    image = PeImage(executable)
    decoder = capstone_module.Cs(capstone_module.CS_ARCH_X86, capstone_module.CS_MODE_64)
    decoder.detail = True
    result = {}
    for name, rva in FUNCTIONS.items():
        function_range = image.function_containing(rva)
        if function_range is None or function_range[0] != rva:
            raise ValueError("Expected .pdata function entry not found for %s" % name)
        start, end = function_range
        offset = image.rva_to_offset(start, end - start)
        code = image.data[offset:offset + end - start]
        instructions = list(decoder.disasm(code, start))
        decoded_size = sum(item.size for item in instructions)
        if decoded_size != len(code):
            raise ValueError("Incomplete instruction decode for %s" % name)
        direct_calls = direct_call_targets(
            instructions,
            capstone_module.CS_GRP_CALL,
            capstone_module.CS_OP_IMM,
        )
        observed_offsets = sorted({
            operand.mem.disp
            for instruction in instructions
            for operand in instruction.operands
            if operand.type == capstone_module.CS_OP_MEM
            and operand.mem.disp
            and decoder.reg_name(operand.mem.base) not in {"rip", "rsp", "rbp"}
        })
        result[name] = {
            "function_rva": hex(start),
            "function_end_exclusive_rva": hex(end),
            "function_size": len(code),
            "prologue_guard": code[:16].hex(),
            "instruction_count": len(instructions),
            "decode_coverage": 1.0,
            "direct_call_targets": [hex(value) for value in direct_calls],
            "register_based_memory_displacements": [hex(value) for value in observed_offsets],
        }

    check_required_calls(result)
    return {
        "schema": 1,
        "target_build": target.get("steam_build_id"),
        "target_executable_sha256": actual_sha,
        "method": "Capstone x86-64 disassembly bounded by PE .pdata ranges; no execution or process attachment.",
        "scope": "UI runtime candidate wrappers and their direct internal calls; not a complete call graph or parameter-contract recovery.",
        "functions": result,
        "limits": [
            "Direct call edges and memory offsets do not identify all argument types, ownership, or semantic predicates.",
            "Undocumented internal targets remain unnamed unless independently resolved.",
            "This static report does not prove that a custom Iggy or Blueprint asset can be loaded or displayed.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("executable", type=Path)
    parser.add_argument("--database", type=Path, default=Path(__file__).resolve().parents[1] / "StateOfDecay2" / "16535856")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    try:
        import capstone
    except ImportError as error:
        parser.error("Capstone is required; install Research/tools/requirements.txt (%s)" % error)
    try:
        report = analyze(args.executable, args.database, capstone)
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        parser.error(str(error))
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("PASS: fixed-build UI wrappers decoded; semantics remain gated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
