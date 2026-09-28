#!/usr/bin/env python3
"""Cross-check decoded full-.pdata call edges against raw relative-call bytes."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import struct

from pe_static import PeImage
from analyze_all_pdata_direct_call_xrefs import sha256_file


ROOT = Path(__file__).resolve().parents[2]
DATABASE = ROOT / "Research" / "StateOfDecay2" / "16535856"


def scan_raw_relative_sites(image: PeImage, target_rvas: set[int]) -> dict[int, dict[int, set[int]]]:
    """Return {opcode: {target_rva: {site_rva}}} for raw E8/E9 byte patterns."""
    found = {0xE8: {target: set() for target in target_rvas}, 0xE9: {target: set() for target in target_rvas}}
    for section in image.sections:
        if not section.is_executable or section.raw_size < 5:
            continue
        code = image.data[section.raw_offset : section.raw_offset + section.raw_size]
        for opcode in (0xE8, 0xE9):
            needle = bytes([opcode])
            index = code.find(needle)
            while 0 <= index <= len(code) - 5:
                target = section.virtual_address + index + 5 + struct.unpack_from("<i", code, index + 1)[0]
                if target in target_rvas:
                    found[opcode][target].add(section.virtual_address + index)
                index = code.find(needle, index + 1)
    return found


def audit_report(image: PeImage, decoded_report: dict) -> dict:
    target_rows = decoded_report.get("targets", [])
    target_rvas = {int(row["target_rva"], 16) for row in target_rows}
    raw = scan_raw_relative_sites(image, target_rvas)
    partial_ranges = {
        (int(row["start_rva"], 16), int(row["end_exclusive"], 16))
        for row in decoded_report.get("partially_decoded_function_bodies", [])
    }

    target_audits = []
    unmatched_raw_e9 = []
    for row in target_rows:
        target = int(row["target_rva"], 16)
        decoded_calls = {int(caller["site_rva"], 16) for caller in row.get("direct_callers", [])}
        decoded_jumps = {int(caller["site_rva"], 16) for caller in row.get("tail_jump_callers", [])}
        raw_calls = raw[0xE8][target]
        raw_jumps = raw[0xE9][target]
        missing_calls = sorted(raw_calls - decoded_calls)
        extra_calls = sorted(decoded_calls - raw_calls)
        missing_jumps = sorted(raw_jumps - decoded_jumps)
        extra_jumps = sorted(decoded_jumps - raw_jumps)
        for site in missing_jumps:
            function_range = image.function_containing(site)
            partial = bool(function_range and function_range in partial_ranges)
            unmatched_raw_e9.append({
                "target_rva": hex(target),
                "site_rva": hex(site),
                "caller_function_range_rva": (
                    {"start": hex(function_range[0]), "end_exclusive": hex(function_range[1])}
                    if function_range else None
                ),
                "inside_partially_decoded_function": partial,
            })
        target_audits.append({
            "target_rva": hex(target),
            "raw_e8_candidate_count": len(raw_calls),
            "decoded_direct_call_count": len(decoded_calls),
            "raw_e8_sites_all_match_decoded_calls": not missing_calls and not extra_calls,
            "unmatched_raw_e8_sites": [hex(site) for site in missing_calls],
            "decoded_calls_without_raw_e8": [hex(site) for site in extra_calls],
            "raw_e9_candidate_count": len(raw_jumps),
            "decoded_tail_jump_count": len(decoded_jumps),
            "unmatched_raw_e9_count": len(missing_jumps),
            "decoded_tail_jumps_without_raw_e9": [hex(site) for site in extra_jumps],
        })

    return {
        "schema": 1,
        "target": "target.json",
        "target_sha256": sha256_file(image.path),
        "source_report": decoded_report.get("report_name", "native-full-pdata-direct-xrefs.json"),
        "method": "Independent raw E8/E9 rel32 byte scan of executable sections compared with Capstone-decoded direct CALL/JMP sites in every executable .pdata function body.",
        "scope": {
            "game_process_started_or_attached": False,
            "target_count": len(target_rows),
            "raw_e8_candidate_count": sum(len(sites) for sites in raw[0xE8].values()),
            "decoded_e8_call_count": sum(row["direct_call_count"] for row in target_rows),
            "unmatched_raw_e8_site_count": sum(len(row["unmatched_raw_e8_sites"]) for row in target_audits),
            "decoded_calls_without_raw_e8_count": sum(len(row["decoded_calls_without_raw_e8"]) for row in target_audits),
            "raw_e9_candidate_count": sum(len(sites) for sites in raw[0xE9].values()),
            "decoded_e9_tail_jump_count": sum(row["tail_jump_count"] for row in target_rows),
            "unmatched_raw_e9_site_count": len(unmatched_raw_e9),
            "unmatched_raw_e9_inside_partial_body_count": sum(row["inside_partially_decoded_function"] for row in unmatched_raw_e9),
            "all_e8_candidates_match_decoded_calls": all(row["raw_e8_sites_all_match_decoded_calls"] for row in target_audits),
        },
        "targets": target_audits,
        "unmatched_raw_e9_sites": unmatched_raw_e9,
        "limits": [
            "Raw E8/E9 byte signatures are candidate locations only; only the Capstone-decoded matching instruction rows count as confirmed edges.",
            "The comparison applies only to the selected %d target RVAs and executable sections of this fixed EXE." % len(target_rows),
            "Indirect calls, virtual dispatch, ProcessEvent, delegates, and call semantics remain outside this audit.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("executable", type=Path, help="local fixed-version StateOfDecay2-Win64-Shipping.exe")
    parser.add_argument("--database", type=Path, default=DATABASE, help="fixed-version research directory")
    parser.add_argument("--xref-report", type=Path, help="full-.pdata call report; defaults to native-full-pdata-direct-xrefs.json")
    parser.add_argument("--output", type=Path, help="output path; defaults to native-full-pdata-direct-xrefs-audit.json")
    args = parser.parse_args()

    xref_path = args.xref_report or args.database / "native-full-pdata-direct-xrefs.json"
    output_path = args.output or args.database / "native-full-pdata-direct-xrefs-audit.json"
    decoded = json.loads(xref_path.read_text(encoding="utf-8"))
    if decoded.get("target_sha256", "").upper() != sha256_file(args.executable):
        raise SystemExit("executable SHA256 does not match full-.pdata direct-call report")
    report = audit_report(PeImage(args.executable), decoded)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    scope = report["scope"]
    print(
        "PASS: %d E8 candidates match %d decoded calls; %d E9 candidates vs %d decoded tail jumps (%d raw-only)" % (
            scope["raw_e8_candidate_count"],
            scope["decoded_e8_call_count"],
            scope["raw_e9_candidate_count"],
            scope["decoded_e9_tail_jump_count"],
            scope["unmatched_raw_e9_site_count"],
        )
    )


if __name__ == "__main__":
    main()
