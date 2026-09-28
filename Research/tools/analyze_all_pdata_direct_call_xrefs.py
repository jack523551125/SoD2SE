#!/usr/bin/env python3
"""Decode every .pdata-bounded executable body for calls into selected targets.

This is a static-only complement to the bounded caller search in
``analyze_native_bodies.py``. It decodes each executable exception-directory
range once, so high-fanout E8 byte candidates do not cause the caller set to be
silently truncated. It does not resolve indirect, virtual, reflected, or
delegate dispatch.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path

from pe_static import PeImage


ROOT = Path(__file__).resolve().parents[2]
DATABASE = ROOT / "Research" / "StateOfDecay2" / "16535856"
MAX_BODY_BYTES = 256 * 1024


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _normalize_immediate(imm: int, image: PeImage) -> int | None:
    if image.section_for_rva(imm):
        return imm
    candidate = imm - image.image_base
    if candidate >= 0 and image.section_for_rva(candidate):
        return candidate
    return None


def analyze_all_pdata_direct_call_xrefs(image: PeImage, target_info: dict, capstone_module) -> dict:
    """Find direct CALL/JMP edges to ``target_info`` within every bounded body."""
    target_rvas = set(target_info)
    if not target_rvas:
        raise ValueError("at least one xref target RVA is required")

    names_by_rva: dict[int, set[str]] = defaultdict(set)
    for pair in image.iter_native_pairs():
        names_by_rva[int(pair["func_rva"], 16)].add(str(pair["name"]))

    md = capstone_module.Cs(capstone_module.CS_ARCH_X86, capstone_module.CS_MODE_64)
    md.detail = True
    md.skipdata = False
    direct_calls: dict[int, list[dict]] = {target: [] for target in target_rvas}
    tail_jumps: dict[int, list[dict]] = {target: [] for target in target_rvas}
    skipped_ranges: list[dict] = []
    partial_decode_ranges: list[dict] = []
    executable_ranges = 0
    decoded_bodies = 0
    decoded_bytes = 0
    instruction_count = 0
    direct_call_instruction_count = 0
    direct_jump_instruction_count = 0
    body_sizes = Counter()

    for start, end in image.function_ranges:
        size = end - start
        section = image.section_for_rva(start, size)
        if section is None or not section.is_executable:
            continue
        executable_ranges += 1
        body_sizes[min(size // 256, 1024)] += 1
        if size > MAX_BODY_BYTES:
            skipped_ranges.append({"start_rva": hex(start), "end_exclusive": hex(end), "reason": "body-size-limit", "size": size})
            continue
        try:
            offset = image.rva_to_offset(start, size)
        except ValueError as error:
            skipped_ranges.append({"start_rva": hex(start), "end_exclusive": hex(end), "reason": str(error), "size": size})
            continue

        body = image.data[offset : offset + size]
        body_decoded = 0
        decoded_bodies += 1
        for insn in md.disasm(body, start):
            instruction_count += 1
            body_decoded += insn.size
            if not insn.group(capstone_module.CS_GRP_CALL) and not insn.group(capstone_module.CS_GRP_JUMP):
                continue
            if not insn.operands or insn.operands[0].type != capstone_module.CS_OP_IMM:
                continue
            target = _normalize_immediate(insn.operands[0].imm, image)
            if target not in target_rvas:
                continue
            row = {
                "site_rva": hex(insn.address),
                "caller_function_range_rva": {"start": hex(start), "end_exclusive": hex(end)},
                "caller_is_function_entry": start in names_by_rva,
                "registered_names_at_caller": sorted(names_by_rva.get(start, set())),
            }
            if insn.group(capstone_module.CS_GRP_CALL):
                direct_call_instruction_count += 1
                direct_calls[target].append(row)
            elif insn.mnemonic == "jmp":
                direct_jump_instruction_count += 1
                tail_jumps[target].append(row)
        decoded_bytes += body_decoded
        if body_decoded != size:
            partial_decode_ranges.append({
                "start_rva": hex(start),
                "end_exclusive": hex(end),
                "body_size": size,
                "decoded_bytes": body_decoded,
                "decode_coverage": round(body_decoded / size, 4) if size else 1.0,
            })

    # Preserve full caller lists: the target set is bounded and the complete
    # results are useful to review generated thunks and high-fanout helpers.
    targets = []
    for target in sorted(target_rvas):
        calls = sorted(direct_calls[target], key=lambda row: (int(row["site_rva"], 16), row["registered_names_at_caller"]))
        jumps = sorted(tail_jumps[target], key=lambda row: (int(row["site_rva"], 16), row["registered_names_at_caller"]))
        meta = target_info[target]
        targets.append({
            "target_rva": hex(target),
            "target_kinds": sorted(meta.get("target_kinds", [])),
            "registered_names_at_target": sorted(names_by_rva.get(target, set())),
            "source_native_functions": sorted(meta.get("source_native_functions", [])),
            "direct_call_count": len(calls),
            "direct_callers": calls,
            "tail_jump_count": len(jumps),
            "tail_jump_callers": jumps,
        })

    return {
        "schema": 1,
        "method": "Capstone-decoded every executable .pdata function range once and retained direct immediate CALL and JMP edges whose target is in the selected RVA set.",
        "scope": {
            "game_process_started_or_attached": False,
            "selected_target_count": len(targets),
            "executable_pdata_function_ranges": executable_ranges,
            "decoded_function_bodies": decoded_bodies,
            "skipped_function_bodies": len(skipped_ranges),
            "partially_decoded_function_bodies": len(partial_decode_ranges),
            "decoded_bytes": decoded_bytes,
            "instruction_count": instruction_count,
            "direct_call_edges": sum(row["direct_call_count"] for row in targets),
            "tail_jump_edges": sum(row["tail_jump_count"] for row in targets),
            "target_count_with_direct_calls": sum(bool(row["direct_call_count"]) for row in targets),
            "target_count_with_tail_jumps": sum(bool(row["tail_jump_count"]) for row in targets),
        },
        "targets": targets,
        "skipped_function_bodies": skipped_ranges,
        "partially_decoded_function_bodies": partial_decode_ranges,
        "limits": [
            "Direct edges are confirmed only inside decoded executable .pdata ranges; code outside those ranges is not covered.",
            "Indirect and virtual calls, ProcessEvent, delegates, reflected dispatch, and data-driven control flow are not resolved.",
            "A caller's registered name identifies a native UFunction entry only when its body start matches an extracted FNameNativePtrPair; unnamed callers remain RVA-only.",
            "Call edges establish references, not execution, authority, parameter meaning, or save/load semantics.",
        ],
    }


def _load_target_info(native_report: dict) -> dict[int, dict]:
    info = {}
    for row in native_report.get("direct_call_xrefs", {}).get("targets", []):
        rva = int(row["target_rva"], 16)
        info[rva] = {
            "target_kinds": row.get("target_kinds", []),
            "source_native_functions": row.get("source_native_functions", []),
        }
    return info


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("executable", type=Path, help="local fixed-version StateOfDecay2-Win64-Shipping.exe")
    parser.add_argument("--database", type=Path, default=DATABASE, help="fixed-version research directory")
    parser.add_argument("--native-body-report", type=Path, help="selected target/xref report; defaults to native-body-analysis.json")
    parser.add_argument("--output", type=Path, help="output path; defaults to native-full-pdata-direct-xrefs.json")
    args = parser.parse_args()

    try:
        import capstone
    except ImportError as error:
        raise SystemExit("Capstone 5.0.7 is required; install Research/tools/requirements.txt") from error

    body_report_path = args.native_body_report or args.database / "native-body-analysis.json"
    output_path = args.output or args.database / "native-full-pdata-direct-xrefs.json"
    native_report = json.loads(body_report_path.read_text(encoding="utf-8"))
    image = PeImage(args.executable)
    expected_hash = str(native_report.get("target_sha256", "")).upper()
    actual_hash = sha256_file(image.path)
    if not expected_hash or expected_hash != actual_hash:
        raise SystemExit("executable SHA256 does not match native-body-analysis.json")

    report = analyze_all_pdata_direct_call_xrefs(image, _load_target_info(native_report), capstone)
    report["target"] = "target.json"
    report["target_sha256"] = actual_hash
    report["native_body_source_report"] = body_report_path.name
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    scope = report["scope"]
    print(
        "PASS: %d .pdata bodies decoded, %d direct calls and %d tail jumps to %d selected targets; %d partial ranges" % (
            scope["decoded_function_bodies"],
            scope["direct_call_edges"],
            scope["tail_jump_edges"],
            scope["selected_target_count"],
            scope["partially_decoded_function_bodies"],
        )
    )


if __name__ == "__main__":
    main()
