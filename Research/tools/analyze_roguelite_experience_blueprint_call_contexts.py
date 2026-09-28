#!/usr/bin/env python3
"""Extract argument ASTs for serialized Blueprint experience-award calls.

This offline analyzer enriches the all-package call census with the serialized
argument expressions for the three registered AwardExperience targets. It
does not execute Blueprint bytecode or infer native runtime behavior.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DATABASE = ROOT / "Research" / "StateOfDecay2" / "16535856"
TARGETS = {
    "Function'CharacterBlueprintHelpers:AuthAwardExperience'",
    "Function'CharacterSkill:AwardExperience'",
    "Function'DaytonCharacter:AwardExperience'",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _target_name(node: dict) -> str | None:
    function = node.get("Function")
    return function.get("ObjectName") if isinstance(function, dict) else None


def _property_name(node) -> str | None:
    """Unwrap Blueprint variable/property nodes without depending on their metadata shape."""
    while isinstance(node, dict):
        if isinstance(node.get("Name"), str):
            return node["Name"]
        node = node.get("Variable")
    return None


def _local_references(node) -> set[str]:
    names = set()
    for row, _ in walk(node):
        if row.get("Inst") == "EX_LocalVariable":
            name = _property_name(row.get("Variable"))
            if name:
                names.add(name)
    return names


def _function_local_assignments(bytecode: list) -> dict[str, list[dict]]:
    assignments: dict[str, list[dict]] = {}
    for top_index, root_node in enumerate(bytecode):
        top_statement = root_node.get("StatementIndex") if isinstance(root_node, dict) else None
        for node, path in walk(root_node, (top_index,)):
            if node.get("Inst") not in ("EX_Let", "EX_LetBool", "EX_LetObj", "EX_LetValueOnPersistentFrame"):
                continue
            name = _property_name(node.get("Variable"))
            expression = node.get("Expression")
            if not name or expression is None:
                continue
            assignments.setdefault(name, []).append({
                "top_level_statement_index": top_statement,
                "ast_path": list(path),
                "expression": summarize_expression(expression),
                "referenced_local_variables": sorted(_local_references(expression)),
            })
    return assignments


def _related_assignments(parameters: list, assignment_map: dict[str, list[dict]]) -> list[dict]:
    pending = sorted(_local_references(parameters))
    seen = set()
    related = []
    while pending:
        name = pending.pop(0)
        if name in seen:
            continue
        seen.add(name)
        rows = assignment_map.get(name, [])
        if rows:
            related.append({"variable": name, "assignments": rows})
        for row in rows:
            pending.extend(ref for ref in row["referenced_local_variables"] if ref not in seen)
    return related


def summarize_expression(node, depth: int = 0):
    """Return a compact deterministic AST summary without serialized metadata noise."""
    if not isinstance(node, (dict, list)):
        return node
    if isinstance(node, list):
        return [summarize_expression(row, depth + 1) for row in node]
    if depth > 10:
        return {"truncated": True}

    result = {}
    if "Inst" in node:
        result["inst"] = node["Inst"]
    target = _target_name(node)
    if target:
        result["function"] = target
    variable = node.get("Variable")
    if isinstance(variable, dict) and variable.get("Name"):
        result["variable"] = variable["Name"]
    for key in ("Value", "Offset", "NextOffset", "EndGotoOffset"):
        value = node.get(key)
        if isinstance(value, (str, int, float, bool)):
            result[key[0].lower() + key[1:]] = value

    for key in (
        "Parameters", "IndexTerm", "Cases", "CaseIndexValueTerm", "CaseTerm",
        "DefaultTerm", "ObjectExpression", "ContextExpression", "Expression",
        "BooleanExpression", "ArrayExpression", "MapExpression", "SetExpression",
        "KeyExpression", "ValueExpression", "ReturnExpression",
    ):
        if key in node:
            result[key[0].lower() + key[1:]] = summarize_expression(node[key], depth + 1)
    return result or {"unrecognized_node_keys": sorted(node.keys())}


def walk(node, path=()):
    if isinstance(node, dict):
        yield node, path
        for key, value in node.items():
            yield from walk(value, path + (key,))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from walk(value, path + (index,))


def _load_asset(export_root: Path, asset_path: str) -> tuple[Path, list]:
    relative = Path(*asset_path.split("/"))
    source = export_root / relative.with_suffix(".json")
    data = json.loads(source.read_text(encoding="utf-8-sig"))
    if not isinstance(data, list):
        raise ValueError("export is not an object list: " + str(source))
    return source, data


def build_report(export_root: Path, call_report_path: Path) -> dict:
    source_report = json.loads(call_report_path.read_text(encoding="utf-8-sig"))
    if source_report.get("scope", {}).get("game_process_started_or_attached") not in (None, False):
        raise ValueError("source call report must not refer to a live game process")
    target_sha256 = source_report.get("target_sha256")
    if not target_sha256:
        target_sha256 = json.loads((DATABASE / "target.json").read_text(encoding="utf-8-sig")).get("sha256")
    if not isinstance(target_sha256, str) or len(target_sha256) != 64:
        raise ValueError("fixed target SHA256 is unavailable")
    census_rows = [
        row for row in source_report.get("call_references", [])
        if row.get("target") in TARGETS
    ]
    if not census_rows:
        raise ValueError("no selected AwardExperience calls in the source census")

    requested_counts = Counter((row["asset_path"], row["blueprint_function"], row["target"]) for row in census_rows)
    asset_paths = sorted({row["asset_path"] for row in census_rows})
    extracted = []
    asset_digests = {}
    for asset_path in asset_paths:
        source_path, objects = _load_asset(export_root, asset_path)
        asset_digests[asset_path] = sha256_file(source_path)
        function_names = {row["blueprint_function"] for row in census_rows if row["asset_path"] == asset_path}
        for function in objects:
            if function.get("Type") != "Function" or function.get("Name") not in function_names:
                continue
            bytecode = function.get("ScriptBytecode")
            if not isinstance(bytecode, list):
                continue
            assignment_map = _function_local_assignments(bytecode)
            for top_index, root_node in enumerate(bytecode):
                top_statement = root_node.get("StatementIndex") if isinstance(root_node, dict) else None
                for node, path in walk(root_node, (top_index,)):
                    target = _target_name(node)
                    if target not in TARGETS:
                        continue
                    extracted.append({
                        "asset_path": asset_path,
                        "blueprint_function": function["Name"],
                        "target": target,
                        "token": node.get("Inst"),
                        "top_level_statement_index": top_statement,
                        "ast_path": list(path),
                        "parameters": [summarize_expression(row) for row in node.get("Parameters", [])],
                        "related_local_assignments": _related_assignments(node.get("Parameters", []), assignment_map),
                    })

    observed_counts = Counter((row["asset_path"], row["blueprint_function"], row["target"]) for row in extracted)
    if observed_counts != requested_counts:
        missing = requested_counts - observed_counts
        extra = observed_counts - requested_counts
        raise ValueError("export/census call-count mismatch; missing=%r extra=%r" % (dict(missing), dict(extra)))

    target_counts = Counter(row["target"] for row in extracted)
    function_counts = Counter((row["asset_path"], row["blueprint_function"]) for row in extracted)
    return {
        "schema": 1,
        "target": source_report.get("target", "target.json"),
        "target_sha256": target_sha256,
        "source_call_census": call_report_path.name,
        "source_call_census_sha256": sha256_file(call_report_path),
        "method": "Read only selected cooked-export JSON files named by the all-package Blueprint census; recursively retain the serialized parameter AST for each matched native experience target.",
        "scope": {
            "game_process_started_or_attached": False,
            "export_root": "external temporary data",
            "selected_asset_count": len(asset_paths),
            "selected_function_count": len(function_counts),
            "serialized_award_call_count": len(extracted),
            "target_call_counts": dict(sorted(target_counts.items())),
            "selected_assets_sha256": asset_digests,
        },
        "call_sites": extracted,
        "limits": [
            "The argument AST shows serialized call-site expressions only; it does not resolve native parameter names, branch execution, ProcessEvent behavior, network authority, or native award semantics.",
            "Local assignments are included only when reached through local-variable references in the call arguments; control-flow reachability and branch execution are not simulated.",
            "These selected experience calls are not a complete census of every possible XP award route or native dynamic dispatch path.",
            "No game process or memory was accessed.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("export_root", type=Path, help="temporary directory containing cooked-export JSON")
    parser.add_argument("--call-report", type=Path, default=DATABASE / "community-full-uasset-roguelite-call-analysis.json")
    parser.add_argument("--output", type=Path, default=DATABASE / "roguelite-experience-blueprint-call-contexts.json")
    args = parser.parse_args()
    report = build_report(args.export_root, args.call_report)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("PASS: extracted %d serialized experience call ASTs from %d assets" % (
        report["scope"]["serialized_award_call_count"], report["scope"]["selected_asset_count"]
    ))


if __name__ == "__main__":
    main()
