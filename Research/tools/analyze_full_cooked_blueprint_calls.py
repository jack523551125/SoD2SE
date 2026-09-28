#!/usr/bin/env python3
"""Census filtered serialized Blueprint call references across cooked JSON exports.

This is an offline text-JSON analysis helper. It does not start or attach to the
game and does not claim to reconstruct virtual dispatch or runtime reachability.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Iterable, Pattern

from analyze_cooked_community_assets import RELEVANT_BLUEPRINT_CALL, _iter_blueprint_call_references


CAPACITY_TARGETS = (
    "CanAddCharacter",
    "CanAddCharacters",
    "TryAddCharacter",
    "TryAddCharacterRecord",
)


def _virtual_asset_path(json_path: Path, export_root: Path) -> str:
    return json_path.relative_to(export_root).with_suffix(".uasset").as_posix()


def _normalized_path(value: str) -> str:
    return value.replace("\\", "/").casefold()


def analyze_export_directory(
    export_root: Path,
    warning_assets: Iterable[str] = (),
    target_pattern: Pattern[str] = RELEVANT_BLUEPRINT_CALL,
) -> dict:
    files = sorted(export_root.rglob("*.json"))
    warning_paths = {_normalized_path(path) for path in warning_assets}
    decode_errors = []
    object_count = 0
    function_count = 0
    bytecode_function_count = 0
    top_level_expression_count = 0
    call_references = []
    target_counts = Counter()
    capacity_target_counts = Counter({name: 0 for name in CAPACITY_TARGETS})
    warning_file_call_reference_count = 0

    for path in files:
        try:
            value = json.loads(path.read_text(encoding="utf-8-sig"))
            if not isinstance(value, list):
                raise ValueError("export root is not an object list")
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
            decode_errors.append({"file": path.as_posix(), "error": str(error)})
            continue

        asset_path = _virtual_asset_path(path, export_root)
        has_export_warning = _normalized_path(asset_path) in warning_paths
        object_count += sum(isinstance(item, dict) for item in value)
        for item in value:
            if not isinstance(item, dict) or item.get("Type") != "Function":
                continue
            function_count += 1
            script = item.get("ScriptBytecode")
            if not isinstance(script, list):
                continue
            bytecode_function_count += 1
            top_level_expression_count += len(script)
            for token, target, target_path in _iter_blueprint_call_references(script):
                target = str(target)
                if not target_pattern.search(target):
                    continue
                reference = {
                    "asset_path": asset_path,
                    "blueprint_function": item.get("Name"),
                    "token": token,
                    "target": target,
                    "target_path": target_path,
                    "asset_has_export_warning": has_export_warning,
                }
                call_references.append(reference)
                target_counts[target] += 1
                target_symbol = target.rsplit(":", 1)[-1].rstrip("'")
                for candidate in CAPACITY_TARGETS:
                    if target_symbol.casefold() == candidate.casefold():
                        capacity_target_counts[candidate] += 1
                if has_export_warning:
                    warning_file_call_reference_count += 1

    call_references.sort(key=lambda row: (
        str(row["asset_path"]).casefold(),
        str(row["blueprint_function"]),
        row["token"],
        row["target"],
    ))
    return {
        "schema": 1,
        "method": "Offline census of serialized Ue4Export Blueprint expression trees; filters call tokens by the supplied target regex.",
        "target_filter": target_pattern.pattern,
        "scope": {
            "export_root": "external temporary data",
            "json_files_seen": len(files),
            "json_decode_error_count": len(decode_errors),
            "decoded_object_count": object_count,
            "function_count": function_count,
            "function_bytecode_count": bytecode_function_count,
            "top_level_bytecode_expression_count": top_level_expression_count,
            "filtered_call_reference_count": len(call_references),
            "filtered_call_target_count": len(target_counts),
            "call_references_in_exporter_warning_assets": warning_file_call_reference_count,
            "decode_errors": decode_errors,
        },
        "capacity_native_wrapper_reference_counts": dict(capacity_target_counts),
        "target_reference_counts": dict(sorted(target_counts.items())),
        "call_references": call_references,
        "limits": [
            "Serialized call tokens are evidence of references only; they do not prove runtime execution, caller completeness, or campaign reachability.",
            "EX_VirtualFunction names are not resolved to native or Blueprint implementations.",
            "ProcessEvent, delegates outside the parsed expression forms, native indirect calls, data-driven dispatch, and save/load semantics are not reconstructed.",
            "Packages with exporter warnings may have incomplete serialization even when their JSON file decodes.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exports", required=True, type=Path, help="Root of the external Ue4Export JSON output")
    parser.add_argument("--warning-report", required=True, type=Path, help="Full cooked-export audit JSON with warning paths")
    parser.add_argument("--output", required=True, type=Path, help="Path to the compact reference census JSON")
    parser.add_argument(
        "--target-pattern",
        help="Override the default recruitment/community call-target filter with a Python regular expression",
    )
    args = parser.parse_args()
    warning_report = json.loads(args.warning_report.read_text(encoding="utf-8"))
    warning_assets = [
        row["asset_virtual_path"]
        for row in warning_report.get("scope", {}).get("warning_assets", [])
        if row.get("asset_virtual_path")
    ]
    try:
        target_pattern = re.compile(args.target_pattern) if args.target_pattern else RELEVANT_BLUEPRINT_CALL
    except re.error as error:
        parser.error("invalid --target-pattern: %s" % error)
    report = analyze_export_directory(args.exports, warning_assets, target_pattern)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    scope = report["scope"]
    print(
        "PASS: %d JSON files, %d decode errors, %d filtered call references, %d capacity-wrapper references" % (
            scope["json_files_seen"],
            scope["json_decode_error_count"],
            scope["filtered_call_reference_count"],
            sum(report["capacity_native_wrapper_reference_counts"].values()),
        )
    )


if __name__ == "__main__":
    main()
