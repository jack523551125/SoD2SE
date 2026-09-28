"""Census serialized CommunityMissionCondition objects in a full Ue4Export tree."""
import argparse
import json
import re
from collections import Counter
from pathlib import Path


TOKEN = b'"Type": "CommunityMissionCondition"'
DEFAULT_OBJECT_TOKEN = b"Default__CommunityMissionCondition"
COMPARISON_ENUM_NAME_TOKEN = b'"Name": "EMissionConditionComparison"'
CONDITION_STRUCT_NAME_TOKEN = b'"Name": "CommunityMissionCondition"'


def walk_objects(value):
    if isinstance(value, dict):
        if value.get("Type") == "CommunityMissionCondition":
            yield value
        for child in value.values():
            yield from walk_objects(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_objects(child)


def walk_all_objects(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk_all_objects(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_all_objects(child)


def analyze(export_root, target_sha256=None):
    export_root = Path(export_root).resolve()
    asset_roots = sorted((path for path in export_root.iterdir() if path.is_dir()), key=lambda path: path.name.casefold())
    if not asset_roots:
        raise ValueError("full export root must contain provider asset subtrees")
    json_files = sorted(
        path
        for asset_root in asset_roots
        for path in asset_root.rglob("*.json")
    )
    comparisons = Counter()
    stats = Counter()
    package_rows = []
    missing = []
    candidate_file_count = 0
    decode_errors = []
    bytes_scanned = 0
    object_count = 0
    default_object_name_hits = 0
    comparison_enum_declarations = 0
    condition_struct_declarations = 0

    for path in json_files:
        try:
            payload = path.read_bytes()
        except OSError as error:
            decode_errors.append({"path": path.relative_to(export_root).as_posix(), "error": str(error)})
            continue
        bytes_scanned += len(payload)
        default_object_name_hits += payload.count(DEFAULT_OBJECT_TOKEN)
        declaration_candidates = (
            COMPARISON_ENUM_NAME_TOKEN in payload
            or CONDITION_STRUCT_NAME_TOKEN in payload
        )
        if TOKEN not in payload:
            if not declaration_candidates:
                continue
        if declaration_candidates:
            try:
                declaration_document = json.loads(payload.decode("utf-8-sig"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                decode_errors.append({"path": path.relative_to(export_root).as_posix(), "error": str(error)})
            else:
                for declaration in walk_all_objects(declaration_document):
                    if declaration.get("Name") == "EMissionConditionComparison" and declaration.get("Type") == "UserDefinedEnum":
                        comparison_enum_declarations += 1
                    if declaration.get("Name") == "CommunityMissionCondition" and declaration.get("Type") == "UserDefinedStruct":
                        condition_struct_declarations += 1
        if TOKEN not in payload:
            continue
        candidate_file_count += 1
        try:
            document = json.loads(payload.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            decode_errors.append({"path": path.relative_to(export_root).as_posix(), "error": str(error)})
            continue

        relative_path = path.relative_to(export_root).as_posix()
        package_count = 0
        for obj in walk_objects(document):
            package_count += 1
            object_count += 1
            properties = obj.get("Properties") or {}
            stat = properties.get("ComparisonStat")
            comparison = properties.get("Comparison")
            stat_key = stat or "<missing>"
            comparison_key = comparison or "<missing>"
            stats[stat_key] += 1
            comparisons[(stat_key, comparison_key)] += 1
            if comparison is None:
                missing.append({
                    "asset": relative_path,
                    "object": obj.get("Name"),
                    "comparison_stat": stat,
                    "value": properties.get("Value"),
                })
        if package_count:
            package_rows.append({"asset": relative_path, "object_count": package_count})

    serialized_comparisons = [
        {"comparison_stat": stat, "comparison": comparison, "count": count}
        for (stat, comparison), count in sorted(comparisons.items())
    ]
    return {
        "schema": 1,
        "target": "target.json",
        "target_sha256": target_sha256.upper() if target_sha256 else None,
        "method": (
            "Read JSON files under each immediate provider asset subtree as UTF-8 with optional BOM, "
            "excluding root-level analysis sidecars; parse files containing the exact CommunityMissionCondition "
            "Type field and count serialized Properties without inferring defaults."
        ),
        "scope": {
            "export_root_name": export_root.name,
            "provider_asset_roots": [path.name for path in asset_roots],
            "json_files_seen": len(json_files),
            "json_bytes_scanned": bytes_scanned,
            "candidate_files": candidate_file_count,
            "json_decode_errors": len(decode_errors),
            "game_process_started_or_attached": False,
            "class_default_inferred": False,
        },
        "static_definition_search": {
            "searched_same_full_json_tree": True,
            "default_object_name_token": "Default__CommunityMissionCondition",
            "default_object_name_hit_count": default_object_name_hits,
            "comparison_enum_definition_type": "UserDefinedEnum",
            "comparison_enum_definition_count": comparison_enum_declarations,
            "condition_struct_definition_type": "UserDefinedStruct",
            "condition_struct_definition_count": condition_struct_declarations,
            "interpretation": "This export tree contains no direct cooked UEnum/UStruct definition or named class-default object for the condition's missing Comparison values; absence does not establish what native/default-struct initialization supplies.",
        },
        "summary": {
            "condition_object_count": object_count,
            "comparison_stat_counts": dict(sorted(stats.items())),
            "comparison_field_present_count": object_count - len(missing),
            "comparison_field_missing_count": len(missing),
            "comparison_by_stat": serialized_comparisons,
            "missing_by_stat": dict(sorted(Counter(row["comparison_stat"] or "<missing>" for row in missing).items())),
        },
        "packages": package_rows,
        "missing_comparison_objects": missing,
        "errors": decode_errors,
        "limits": [
            "The report describes serialized exported object properties only; a missing Comparison field does not establish the native class-default value.",
            "This census includes all packages in the supplied export tree, not only MissionAsset packages; object counts must not be compared as if the selections were identical.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("export_root", type=Path, help="Root directory containing the full exported JSON tree")
    parser.add_argument("output", type=Path, help="Output JSON report path")
    parser.add_argument("--target-sha256", required=True, help="SHA256 from the matching fixed-build target.json")
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9A-Fa-f]{64}", args.target_sha256):
        parser.error("--target-sha256 must be a 64-character SHA256")
    report = analyze(args.export_root, args.target_sha256)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("CommunityMissionCondition objects: %d; missing Comparison: %d; JSON decode errors: %d" % (
        report["summary"]["condition_object_count"],
        report["summary"]["comparison_field_missing_count"],
        report["scope"]["json_decode_errors"],
    ))


if __name__ == "__main__":
    main()
