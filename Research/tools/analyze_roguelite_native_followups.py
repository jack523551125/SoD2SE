#!/usr/bin/env python3
"""Resolve direct .pdata callers of anonymous or chain-fragment roguelite targets.

This focused follow-up expands the selected-target census by one layer around
anonymous function entries already exposed by the kill/experience/identity
analysis. It remains a static direct-call report; it does not infer gameplay
semantics from caller relationships.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from analyze_all_pdata_direct_call_xrefs import analyze_all_pdata_direct_call_xrefs, sha256_file
from pe_static import PeImage


ROOT = Path(__file__).resolve().parents[2]
DATABASE = ROOT / "Research" / "StateOfDecay2" / "16535856"

FOCUS_SOURCES = [
    {
        "target_rva": "0x3c92e4",
        "candidate_reason": "unnamed caller of OnZombieKilled internal target 0x253ed0",
        "upstream_native_function": "OnZombieKilled",
    },
    {
        "target_rva": "0x3292c7",
        "candidate_reason": "unnamed caller of AuthOnZombieKilled internal target 0x3dbfe0",
        "upstream_native_function": "AuthOnZombieKilled",
    },
    {
        "target_rva": "0x29a690",
        "candidate_reason": "unnamed caller of GetCharacterWhoHitMost internal target 0x3be4e0",
        "upstream_native_function": "GetCharacterWhoHitMost",
    },
    {
        "target_rva": "0x2bbd8b",
        "candidate_reason": "unnamed function with six direct calls to 0x29a690 in the bounded follow-up scan",
        "upstream_native_function": "GetCharacterWhoHitMost",
    },
    {
        "target_rva": "0x1cf9ca",
        "target_kind": "roguelite-followup-chaininfo-fragment-start",
        "candidate_reason": "CHAININFO-linked subrange start in the 0x1cf910 AwardExperience helper chain; the fragment calls internal target 0x19ef80",
        "upstream_native_function": "AwardExperience",
    },
    {
        "target_rva": "0x461993",
        "candidate_reason": "unnamed caller of AwardExperience internal target 0x19ef80",
        "upstream_native_function": "AwardExperience",
    },
    {
        "target_rva": "0x1e53ab",
        "candidate_reason": "unnamed caller of AwardExperience internal target 0x1cf910",
        "upstream_native_function": "AwardExperience",
    },
    {
        "target_rva": "0x276e80",
        "candidate_reason": "unnamed caller of AwardExperience internal target 0x1cf910 and GetSurvivorByID helper 0x27eef0",
        "upstream_native_function": "AwardExperience; GetSurvivorByID",
    },
]


def build_target_info() -> dict[int, dict]:
    return {
        int(source["target_rva"], 16): {
            "target_kinds": [source.get("target_kind", "roguelite-followup-anonymous-entry")],
            "source_native_functions": [source["upstream_native_function"]],
        }
        for source in FOCUS_SOURCES
    }


def build_report(executable: Path) -> dict:
    try:
        import capstone
    except ImportError as error:
        raise SystemExit("Capstone 5.0.7 is required; install Research/tools/requirements.txt") from error

    image = PeImage(executable)
    report = analyze_all_pdata_direct_call_xrefs(image, build_target_info(), capstone)
    report["report_name"] = "roguelite-native-followup-direct-xrefs.json"
    report["target"] = "target.json"
    report["target_sha256"] = sha256_file(image.path)
    report["focus_sources"] = FOCUS_SOURCES
    report["source_report"] = "native-full-pdata-direct-xrefs.json"
    report["limits"].append(
        "The target list is a focused one-hop follow-up of previously observed anonymous-function or CHAININFO-fragment addresses; it is not a transitive call-graph closure."
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("executable", type=Path, help="local fixed-version StateOfDecay2-Win64-Shipping.exe")
    parser.add_argument("--output", type=Path, default=DATABASE / "roguelite-native-followup-direct-xrefs.json")
    args = parser.parse_args()

    report = build_report(args.executable)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    scope = report["scope"]
    print(
        "PASS: %d .pdata bodies decoded, %d direct calls and %d tail jumps to %d anonymous/chain-fragment targets; %d partial ranges"
        % (
            scope["decoded_function_bodies"],
            scope["direct_call_edges"],
            scope["tail_jump_edges"],
            scope["selected_target_count"],
            scope["partially_decoded_function_bodies"],
        )
    )


if __name__ == "__main__":
    main()
