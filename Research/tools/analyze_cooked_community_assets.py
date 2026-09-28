#!/usr/bin/env python3
"""Summarize cooked SoD2 Blueprint JSON exports without retaining game assets."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, deque
from pathlib import Path
from typing import Any, Iterable


SPECIFIC_COMMUNITY_SYMBOLS = re.compile(
    r"(?i)(bRecruitable|bHideRecruitability|PlayerEnclave|CommunityMembers|"
    r"NumCommunityMembers|LegacyEnclaveCap|bIgnoresPopulationCap|"
    r"bAddsCharactersToPlayerEnclave|RecruitCharacter|CanAddCharacter)"
)
RELEVANT_BLUEPRINT_CALL = re.compile(
    r"(?i)(canaddcharacter|tryaddcharacter|getcurrentpopulation|max.*community|"
    r"recruit|enclave|communitymember|communitymembers|addcharacter|restoreexiled|legacy|community)"
)
BLUEPRINT_CALL_TOKENS = {
    "EX_FinalFunction",
    "EX_LocalFinalFunction",
    "EX_CallMath",
    "EX_VirtualFunction",
    "EX_LocalVirtualFunction",
    "EX_CallMulticastDelegate",
}


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def select_specific_symbol_candidates(global_scan: dict[str, Any], path_candidates: dict[str, Any]) -> dict[str, Any]:
    """Select high-specificity symbol hits outside the filename/path selection."""
    excluded = {str(row.get("asset", "")).lower() for row in path_candidates.get("findings", [])}
    findings = []
    for row in global_scan.get("findings", []):
        asset = str(row.get("asset", ""))
        if asset.lower() in excluded:
            continue
        matching_symbols = [symbol for symbol in row.get("symbols", []) if SPECIFIC_COMMUNITY_SYMBOLS.search(str(symbol))]
        if matching_symbols:
            findings.append({
                "pak": row.get("pak"),
                "asset": asset,
                "uncompressed_size": row.get("uncompressed_size"),
                "symbols": matching_symbols,
            })
    findings.sort(key=lambda row: row["asset"].lower())
    return {
        "schema": 1,
        "method": "filtered from the full-pak string scan; exact high-specificity community/recruitment symbol names only",
        "source_report": "community-all-assets-global-scan.json",
        "excluded_path_candidate_report": "community-named-asset-candidates-scan.json",
        "symbol_regex": SPECIFIC_COMMUNITY_SYMBOLS.pattern,
        "pak_count": global_scan.get("pak_count"),
        "selected_uasset_count": len(findings),
        "selected_uncompressed_bytes": sum(int(row.get("uncompressed_size") or 0) for row in findings),
        "errors": [],
        "findings": findings,
    }


def match_export(asset: str, export_files: list[Path]) -> list[Path]:
    relative = asset[:-7] + ".json" if asset.lower().endswith(".uasset") else asset
    suffix = "/" + relative.replace("\\", "/").lower()
    return [path for path in export_files if path.as_posix().lower().endswith(suffix)]


def object_reference_name(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    match = re.search(r"'([^']*)'", str(value.get("ObjectName", "")))
    return match.group(1).split(":")[-1] if match else ""


def iter_event_references(value: Any) -> Iterable[tuple[str, int]]:
    if isinstance(value, dict):
        event_type = value.get("EventType")
        index = value.get("Index")
        if isinstance(event_type, dict) and isinstance(event_type.get("AbsoluteName"), str) and isinstance(index, int):
            yield event_type["AbsoluteName"].rsplit(".", 1)[-1], index
        for child in value.values():
            yield from iter_event_references(child)
    elif isinstance(value, list):
        for child in value:
            yield from iter_event_references(child)


def _condition_for_event(event: dict[str, Any], objects_by_name: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    return objects_by_name.get(object_reference_name(event.get("Condition")))


def _event_walk(
    event_arrays: dict[str, Any], starts: Iterable[tuple[str, int]]
) -> tuple[set[tuple[str, int]], list[tuple[str, int]], list[tuple[str, int]]]:
    pending = deque(starts)
    visited: set[tuple[str, int]] = set()
    invalid: list[tuple[str, int]] = []
    while pending:
        event_type, index = pending.popleft()
        key = (event_type, index)
        if key in visited:
            continue
        visited.add(key)
        rows = event_arrays.get(event_type)
        if not isinstance(rows, list) or index < 0 or index >= len(rows) or not isinstance(rows[index], dict):
            invalid.append(key)
            continue
        event = rows[index]
        for field in ("EventIndexes", "ElseEventIndexes"):
            pending.extend(iter_event_references(event.get(field, [])))
    return visited, invalid, sorted(visited)


def analyze_event_name_groups(event_arrays: dict[str, Any]) -> dict[str, Any]:
    """Inventory repeated EventName labels without treating them as graph edges."""
    counts_by_name_and_type: dict[str, Counter[str]] = {}
    named_event_record_count = 0
    for event_type, rows in event_arrays.items():
        if not isinstance(rows, list):
            continue
        for event in rows:
            if not isinstance(event, dict):
                continue
            raw_name = event.get("EventName")
            if raw_name is None:
                continue
            name = str(raw_name).strip()
            if not name or name.casefold() == "none":
                continue
            named_event_record_count += 1
            counts_by_name_and_type.setdefault(name, Counter())[str(event_type)] += 1

    same_type_duplicates = []
    cross_type_reuse = []
    repeated_names = 0
    for name, type_counts in sorted(counts_by_name_and_type.items()):
        total = sum(type_counts.values())
        if total > 1:
            repeated_names += 1
        for event_type, count in sorted(type_counts.items()):
            if count > 1:
                same_type_duplicates.append({
                    "event_name": name,
                    "event_type": event_type,
                    "event_count": count,
                })
        if len(type_counts) > 1:
            cross_type_reuse.append({
                "event_name": name,
                "event_types": sorted(type_counts),
                "event_count_by_type": dict(sorted(type_counts.items())),
            })

    return {
        "scope": "EventName values on top-level MissionAsset.Events rows in this package; None/empty values excluded",
        "named_event_record_count": named_event_record_count,
        "unique_named_event_count": len(counts_by_name_and_type),
        "names_reused_in_multiple_rows": repeated_names,
        "same_type_duplicate_group_count": len(same_type_duplicates),
        "cross_type_reuse_group_count": len(cross_type_reuse),
        "same_type_duplicate_examples": same_type_duplicates[:12],
        "cross_type_reuse_examples": cross_type_reuse[:12],
        "limits": [
            "Repeated names are descriptive/correlation evidence only; dispatch and grouping semantics are not established by this inventory.",
            "EventName equality is not added as an execution edge. Only explicit EventIndexes and ElseEventIndexes are traversed.",
        ],
    }


def _analyze_mission_asset(asset: str, objects: list[dict[str, Any]]) -> dict[str, Any] | None:
    mission_asset = next((item for item in objects if item.get("Type") == "MissionAsset"), None)
    if not mission_asset:
        return None
    properties = mission_asset.get("Properties", {})
    event_arrays = properties.get("Events", {})
    event_name_analysis = analyze_event_name_groups(event_arrays if isinstance(event_arrays, dict) else {})
    by_name = {item.get("Name"): item for item in objects if isinstance(item.get("Name"), str)}
    missions = properties.get("Missions", [])
    if not isinstance(missions, list):
        missions = []

    records: list[dict[str, Any]] = []
    reachable_member_conditions: Counter[str] = Counter()
    recruit_paths = 0
    invalid_event_references = 0
    for mission in missions:
        if not isinstance(mission, dict):
            continue
        roots: list[tuple[str, int]] = []
        for key, value in mission.items():
            if key.endswith("Events") or key.endswith("Event"):
                roots.extend(iter_event_references(value))
        visited, invalid, _ = _event_walk(event_arrays, roots)
        invalid_event_references += len(invalid)
        reached_conditions: list[dict[str, Any]] = []
        reached_recruits: list[dict[str, Any]] = []
        for event_type, index in sorted(visited):
            rows = event_arrays.get(event_type)
            if not isinstance(rows, list) or index < 0 or index >= len(rows):
                continue
            event = rows[index]
            if event_type == "RecruitCharacter":
                recruit_paths += 1
                reached_recruits.append({
                    "event_index": index,
                    "event_name": event.get("EventName"),
                    "enclave_name": event.get("EnclaveName"),
                    "character_name": event.get("CharacterName"),
                })
            if event_type == "Condition":
                condition = _condition_for_event(event, by_name)
                condition_properties = condition.get("Properties", {}) if condition else {}
                if (
                    condition
                    and condition.get("Type") == "CommunityMissionCondition"
                    and str(condition_properties.get("ComparisonStat", "")).endswith("CommunityMembers")
                ):
                    condition_name = str(condition.get("Name", ""))
                    reachable_member_conditions[condition_name] += 1
                    reached_conditions.append({
                        "event_index": index,
                        "event_name": event.get("EventName"),
                        "condition": condition_name,
                        "comparison": condition_properties.get("Comparison"),
                        "value": condition_properties.get("Value"),
                        "event_indexes": list(iter_event_references(event.get("EventIndexes", []))),
                        "else_event_indexes": list(iter_event_references(event.get("ElseEventIndexes", []))),
                    })
        if reached_conditions or reached_recruits:
            records.append({
                "mission": mission.get("Name"),
                "adds_characters_to_player_enclave": mission.get("bAddsCharactersToPlayerEnclave"),
                "ignores_population_cap": mission.get("bIgnoresPopulationCap"),
                "reachable_event_node_count": len(visited),
                "reachable_community_member_conditions": reached_conditions,
                "reachable_recruit_events": reached_recruits,
            })

    raw_conditions = [
        item for item in objects
        if item.get("Type") == "CommunityMissionCondition"
        and str(item.get("Properties", {}).get("ComparisonStat", "")).endswith("CommunityMembers")
    ]
    all_community_conditions = [
        item for item in objects if item.get("Type") == "CommunityMissionCondition"
    ]
    all_comparison_counts = Counter(
        str(item.get("Properties", {}).get("Comparison"))
        for item in all_community_conditions
    )
    all_comparison_missing_count = sum(
        "Comparison" not in item.get("Properties", {})
        for item in all_community_conditions
    )
    comparisons = Counter(
        str(item.get("Properties", {}).get("Comparison"))
        for item in raw_conditions
    )
    mission_rows = [item for item in missions if isinstance(item, dict)]
    additions = [item for item in mission_rows if item.get("bAddsCharactersToPlayerEnclave") is True]
    bypass_flags = [item for item in mission_rows if item.get("bIgnoresPopulationCap") is True]
    recruit_definitions = event_arrays.get("RecruitCharacter", [])
    return {
        "asset": asset,
        "mission_asset_name": mission_asset.get("Name"),
        "mission_record_count": len(mission_rows),
        "records_adding_characters_to_player_enclave_count": len(additions),
        "records_adding_characters_to_player_enclave": [item.get("Name") for item in additions],
        "records_ignoring_population_cap_count": len(bypass_flags),
        "records_ignoring_population_cap": [item.get("Name") for item in bypass_flags],
        "recruit_character_event_definition_count": len(recruit_definitions) if isinstance(recruit_definitions, list) else 0,
        "community_member_condition_count": len(raw_conditions),
        "community_member_comparison_counts": dict(sorted(comparisons.items())),
        "community_member_conditions_without_explicit_comparison": comparisons.get("None", 0),
        "all_community_mission_condition_count": len(all_community_conditions),
        "all_community_mission_condition_comparison_counts": dict(sorted(all_comparison_counts.items())),
        "all_community_mission_condition_comparison_missing_count": all_comparison_missing_count,
        "all_community_mission_condition_explicit_equal_count": sum(
            count for value, count in all_comparison_counts.items() if value.endswith("::Equal")
        ),
        "event_name_analysis": event_name_analysis,
        "mission_event_graph": {
            "scope": "Mission-record event references followed through EventIndexes and ElseEventIndexes only",
            "records_with_reachable_recruit_event": sum(bool(row["reachable_recruit_events"]) for row in records),
            "reachable_recruit_event_occurrences": recruit_paths,
            "records_with_reachable_community_member_condition": sum(bool(row["reachable_community_member_conditions"]) for row in records),
            "unique_reachable_community_member_conditions": len(reachable_member_conditions),
            "invalid_event_references": invalid_event_references,
            "records": records,
            "limits": [
                "Named EventName dispatch and mission lifecycle activation are not followed by this index-graph walk.",
                "A reachable node shows serialized graph connectivity, not runtime execution or whether the route is user-visible.",
                "A missing Comparison value is preserved as unknown; no class default is inferred.",
            ],
        },
    }


def _iter_blueprint_call_references(value: Any) -> Iterable[tuple[str, str, str | None]]:
    if isinstance(value, dict):
        token = value.get("Inst")
        if token in BLUEPRINT_CALL_TOKENS:
            target = value.get("Function")
            if token == "EX_CallMulticastDelegate":
                target = value.get("FunctionName")
            if isinstance(target, str):
                yield token, target, None
            elif isinstance(target, dict):
                yield token, str(target.get("ObjectName", "")), target.get("ObjectPath")
        for child in value.values():
            yield from _iter_blueprint_call_references(child)
    elif isinstance(value, list):
        for child in value:
            yield from _iter_blueprint_call_references(child)


def analyze_exports(
    export_dir: Path | list[Path],
    mission_selection: dict[str, Any],
    candidate_report: dict[str, Any] | list[dict[str, Any]],
    exporter_warnings: list[str] | None = None,
    mission_export_dir: Path | None = None,
) -> dict[str, Any]:
    export_directories = export_dir if isinstance(export_dir, list) else [export_dir]
    export_files = sorted({path for directory in export_directories for path in directory.rglob("*.json")})
    candidate_decode_errors: list[dict[str, str]] = []
    def decode_files(paths: list[Path], errors: list[dict[str, str]]) -> dict[Path, list[dict[str, Any]]]:
        result: dict[Path, list[dict[str, Any]]] = {}
        for path in paths:
            try:
                value = read_json(path)
                if not isinstance(value, list):
                    raise ValueError("export root is not an object list")
                result[path] = [item for item in value if isinstance(item, dict)]
            except (OSError, ValueError, json.JSONDecodeError) as error:
                errors.append({"file": path.as_posix(), "error": str(error)})
        return result
    candidate_decoded = decode_files(export_files, candidate_decode_errors)
    mission_directories = mission_export_dir or export_directories
    if isinstance(mission_directories, Path):
        mission_directories = [mission_directories]
    mission_export_files = sorted({path for directory in mission_directories for path in directory.rglob("*.json")})
    mission_decode_errors: list[dict[str, str]] = []
    mission_decoded = decode_files(mission_export_files, mission_decode_errors)

    mission_assets = mission_selection.get("assets", [])
    mission_results: list[dict[str, Any]] = []
    mission_missing: list[str] = []
    mission_ambiguous: list[str] = []
    for row in mission_assets:
        asset = str(row.get("asset", ""))
        hits = match_export(asset, list(mission_decoded))
        hits_with_mission = [path for path in hits if any(item.get("Type") == "MissionAsset" for item in mission_decoded[path])]
        if not hits_with_mission:
            if not hits:
                mission_missing.append(asset)
            else:
                mission_missing.append(asset + " (no MissionAsset export)")
            continue
        if len(hits_with_mission) > 1:
            mission_ambiguous.append(asset)
            continue
        summary = _analyze_mission_asset(asset, mission_decoded[hits_with_mission[0]])
        if summary:
            mission_results.append(summary)

    candidate_reports = candidate_report if isinstance(candidate_report, list) else [candidate_report]
    candidate_findings_by_asset = {
        str(row.get("asset", "")).lower(): row
        for report in candidate_reports
        for row in report.get("findings", [])
    }
    candidate_findings = list(candidate_findings_by_asset.values())
    candidate_matched: list[str] = []
    candidate_missing: list[str] = []
    for row in candidate_findings:
        asset = str(row.get("asset", ""))
        if match_export(asset, list(candidate_decoded)):
            candidate_matched.append(asset)
        else:
            candidate_missing.append(asset)

    candidate_objects = [item for rows in candidate_decoded.values() for item in rows]
    type_counts = Counter(item.get("Type", "") for item in candidate_objects)
    functions = [item for item in candidate_objects if item.get("Type") == "Function"]
    bytecode_functions = [item for item in functions if isinstance(item.get("ScriptBytecode"), list)]
    top_level_expressions = sum(len(item["ScriptBytecode"]) for item in bytecode_functions)
    bytecode_calls: list[dict[str, Any]] = []
    for path, rows in candidate_decoded.items():
        for function in rows:
            script = function.get("ScriptBytecode")
            if function.get("Type") != "Function" or not isinstance(script, list):
                continue
            outer_path = function.get("Outer", {}).get("ObjectPath")
            package_path = str(outer_path).rsplit(".", 1)[0] if outer_path else path.as_posix()
            for token, target_name, target_path in _iter_blueprint_call_references(script):
                if RELEVANT_BLUEPRINT_CALL.search(target_name):
                    bytecode_calls.append({
                        "asset_package": package_path,
                        "blueprint_function": function.get("Name"),
                        "token": token,
                        "target": target_name,
                        "target_path": target_path,
                    })
    bytecode_calls.sort(key=lambda row: (row["asset_package"], str(row["blueprint_function"]), row["token"], row["target"]))
    mission_objects = [item for rows in mission_decoded.values() for item in rows]
    mission_functions = [item for item in mission_objects if item.get("Type") == "Function"]
    mission_bytecode_functions = [item for item in mission_functions if isinstance(item.get("ScriptBytecode"), list)]
    mission_top_level_expressions = sum(len(item["ScriptBytecode"]) for item in mission_bytecode_functions)
    total_mission_records = sum(row["mission_record_count"] for row in mission_results)
    total_conditions = Counter()
    mission_record_adds = 0
    mission_record_ignores = 0
    event_graph_records = 0
    event_graph_recruit_events = 0
    event_graph_member_gates = 0
    event_graph_member_condition_occurrences = 0
    member_condition_records = 0
    all_community_condition_records = 0
    all_community_comparison_counts: Counter[str] = Counter()
    all_community_comparison_missing_count = 0
    all_community_explicit_equal_count = 0
    event_name_records = 0
    event_name_package_unique_count_sum = 0
    event_name_reused_names = 0
    event_name_same_type_duplicate_groups = 0
    event_name_cross_type_reuse_groups = 0
    event_name_reuse_examples: list[dict[str, Any]] = []
    for row in mission_results:
        total_conditions.update(row["community_member_comparison_counts"])
        mission_record_adds += row["records_adding_characters_to_player_enclave_count"]
        mission_record_ignores += row["records_ignoring_population_cap_count"]
        graph = row["mission_event_graph"]
        event_graph_records += graph["records_with_reachable_recruit_event"]
        event_graph_recruit_events += graph["reachable_recruit_event_occurrences"]
        event_graph_member_gates += graph["records_with_reachable_community_member_condition"]
        event_graph_member_condition_occurrences += sum(
            len(record.get("reachable_community_member_conditions", []))
            for record in graph["records"]
        )
        member_condition_records += row["community_member_condition_count"]
        all_community_condition_records += row["all_community_mission_condition_count"]
        all_community_comparison_counts.update(row["all_community_mission_condition_comparison_counts"])
        all_community_comparison_missing_count += row["all_community_mission_condition_comparison_missing_count"]
        all_community_explicit_equal_count += row["all_community_mission_condition_explicit_equal_count"]
        name_analysis = row["event_name_analysis"]
        event_name_records += name_analysis["named_event_record_count"]
        event_name_package_unique_count_sum += name_analysis["unique_named_event_count"]
        event_name_reused_names += name_analysis["names_reused_in_multiple_rows"]
        event_name_same_type_duplicate_groups += name_analysis["same_type_duplicate_group_count"]
        event_name_cross_type_reuse_groups += name_analysis["cross_type_reuse_group_count"]
        if (
            name_analysis["same_type_duplicate_group_count"]
            or name_analysis["cross_type_reuse_group_count"]
        ) and len(event_name_reuse_examples) < 20:
            event_name_reuse_examples.append({
                "asset": row["asset"],
                "same_type_duplicate_examples": name_analysis["same_type_duplicate_examples"][:3],
                "cross_type_reuse_examples": name_analysis["cross_type_reuse_examples"][:3],
            })

    return {
        "schema": 1,
        "target": "target.json",
        "method": "offline Ue4Export/CUE4Parse JSON summary; ReadScriptData enabled",
        "scope": {
            "full_source_assets_retained": False,
            "parser_output_directory_is_external_temporary_data": True,
            "candidate_asset_count": len(candidate_findings),
            "candidate_source_report_count": len(candidate_reports),
            "candidate_exports_matched": len(candidate_matched),
            "candidate_exports_missing": candidate_missing,
            "candidate_export_file_count": len(export_files),
            "candidate_decoded_object_count": len(candidate_objects),
            "candidate_function_count": len(functions),
            "candidate_function_bytecode_count": len(bytecode_functions),
            "candidate_top_level_bytecode_expression_count": top_level_expressions,
            "candidate_filtered_blueprint_call_reference_count": len(bytecode_calls),
            "candidate_filtered_blueprint_call_target_count": len({row["target"] for row in bytecode_calls}),
            "candidate_json_decode_errors": candidate_decode_errors,
            "mission_selection_asset_count": len(mission_assets),
            "mission_export_file_count": len(mission_export_files),
            "mission_export_function_count": len(mission_functions),
            "mission_export_function_bytecode_count": len(mission_bytecode_functions),
            "mission_export_top_level_bytecode_expression_count": mission_top_level_expressions,
            "mission_exports_with_missionasset": len(mission_results),
            "mission_selection_assets_without_missionasset": mission_missing,
            "mission_export_ambiguous_matches": mission_ambiguous,
            "mission_json_decode_errors": mission_decode_errors,
            "exporter_warnings": exporter_warnings or [],
        },
        "candidate_export_object_type_counts": dict(sorted(type_counts.items())),
        "candidate_blueprint_call_references": {
            "scope": "Serialized call tokens in parsed function expression trees; virtual function names retained as names, not resolved implementations.",
            "filter": RELEVANT_BLUEPRINT_CALL.pattern,
            "matched_reference_count": len(bytecode_calls),
            "unique_target_count": len({row["target"] for row in bytecode_calls}),
            "unique_targets": sorted({row["target"] for row in bytecode_calls}),
            "references": bytecode_calls,
            "limits": [
                "These are serialized Blueprint call references, not proof of runtime reachability or invocation order.",
                "Virtual calls name the target method but the concrete class implementation is not resolved here.",
                "The name filter includes broad community/enclave terms and must be reviewed with the asset and caller context.",
            ],
        },
        "mission_summary": {
            "mission_asset_package_count": len(mission_results),
            "mission_record_count": total_mission_records,
            "mission_records_adding_characters_to_player_enclave": mission_record_adds,
            "mission_records_flagged_ignores_population_cap": mission_record_ignores,
            "community_member_condition_records": member_condition_records,
            "community_member_condition_comparison_counts": dict(sorted(total_conditions.items())),
            "community_condition_comparison_coverage": {
                "condition_count": all_community_condition_records,
                "serialized_comparison_counts_including_missing": dict(sorted(all_community_comparison_counts.items())),
                "missing_comparison_count": all_community_comparison_missing_count,
                "explicit_equal_count": all_community_explicit_equal_count,
                "interpretation": "All explicit values observed in these selected MissionAssets are non-Equal. This is consistent with Equal being the class default for omitted fields, but the native class default object has not been decoded, so this remains an inference.",
            },
            "mission_records_with_reachable_recruit_event": event_graph_records,
            "reachable_recruit_event_occurrences": event_graph_recruit_events,
            "mission_records_with_reachable_community_member_condition": event_graph_member_gates,
            "reachable_community_member_condition_event_occurrences": event_graph_member_condition_occurrences,
            "event_name_inventory": {
                "scope": "per-package aggregates over top-level MissionAsset.Events rows; these labels are not graph edges",
                "named_event_record_count": event_name_records,
                "package_unique_name_count_sum": event_name_package_unique_count_sum,
                "packages_with_repeated_names": sum(
                    row["event_name_analysis"]["names_reused_in_multiple_rows"] > 0
                    for row in mission_results
                ),
                "reused_name_group_count_per_package_sum": event_name_reused_names,
                "same_type_duplicate_group_count_per_package_sum": event_name_same_type_duplicate_groups,
                "cross_type_reuse_group_count_per_package_sum": event_name_cross_type_reuse_groups,
                "examples": event_name_reuse_examples,
                "limits": [
                    "Names reused across records or event types are not assumed to imply one-to-one or broadcast dispatch.",
                    "The report preserves EventName on reached condition/recruit nodes but does not traverse by name.",
                ],
            },
            "packages": mission_results,
            "limits": [
                "Blueprint bytecode was parsed into expression trees but this report does not claim whole-program control-flow or native/virtual dispatch reconstruction.",
                "The event graph walk follows serialized EventIndexes and ElseEventIndexes from mission-record event arrays; named dispatch and dynamic activation are unresolved.",
                "Static data and graph connectivity do not prove runtime reachability, save behavior, or compatibility with the native capacity patch.",
            ],
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exports", required=True, action="append", type=Path, help="Directory containing Ue4Export JSON output; repeat to combine disjoint selections")
    parser.add_argument("--mission-exports", type=Path, help="Optional separate directory containing selected mission exports")
    parser.add_argument("--mission-selection", required=True, type=Path)
    parser.add_argument("--candidate-report", required=True, action="append", type=Path)
    parser.add_argument("--global-scan", type=Path, help="Optional complete .uasset string-scan report used to derive extra symbol candidates")
    parser.add_argument("--path-candidate-report", type=Path, help="Path-based candidate report to exclude from symbol selection")
    parser.add_argument("--symbol-candidates-output", type=Path, help="Where to write the derived exact-symbol candidate report")
    parser.add_argument("--exporter-revision", required=True, help="Ue4Export git revision used to create the JSON inputs")
    parser.add_argument("--parser-revision", required=True, help="CUE4Parse git revision used to create the JSON inputs")
    parser.add_argument("--parser-configuration", required=True, help="Relevant exporter/parser configuration, e.g. ReadScriptData=true")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--export-warning", action="append", default=[], help="Known parser warning; can be repeated")
    args = parser.parse_args()
    candidate_reports = [read_json(path) for path in args.candidate_report]
    if args.global_scan:
        if not args.path_candidate_report or not args.symbol_candidates_output:
            parser.error("--global-scan requires --path-candidate-report and --symbol-candidates-output")
        symbol_report = select_specific_symbol_candidates(
            read_json(args.global_scan), read_json(args.path_candidate_report)
        )
        args.symbol_candidates_output.parent.mkdir(parents=True, exist_ok=True)
        args.symbol_candidates_output.write_text(json.dumps(symbol_report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        if all(str(path.resolve()).lower() != str(args.symbol_candidates_output.resolve()).lower() for path in args.candidate_report):
            candidate_reports.append(symbol_report)
    report = analyze_exports(
        args.exports,
        read_json(args.mission_selection),
        candidate_reports,
        args.export_warning,
        args.mission_exports,
    )
    report["parser_provenance"] = {
        "exporter_revision": args.exporter_revision,
        "parser_revision": args.parser_revision,
        "configuration": args.parser_configuration,
        "input_json_directories_are_external_temporary_data": True,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    scope = report["scope"]
    summary = report["mission_summary"]
    print(
        "PASS: %d/%d candidate assets matched; %d/%d mission assets parsed; "
        "%d mission records, %d CommunityMembers conditions; %d JSON errors" % (
            scope["candidate_exports_matched"], scope["candidate_asset_count"],
            scope["mission_exports_with_missionasset"], scope["mission_selection_asset_count"],
            summary["mission_record_count"], summary["community_member_condition_records"],
            len(scope["mission_json_decode_errors"]),
        )
    )


if __name__ == "__main__":
    main()
