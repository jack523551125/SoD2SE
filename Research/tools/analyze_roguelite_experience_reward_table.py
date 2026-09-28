#!/usr/bin/env python3
"""Summarize the cooked ExperienceRewards table and match call-site tags.

This static report records each reward row's skill-specific XP values and
links rows to the serialized Blueprint call contexts already extracted.
Matching a call-site name to a table row does not prove native lookup or award
execution semantics.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DATABASE = ROOT / "Research" / "StateOfDecay2" / "16535856"
DEFAULT_TABLE = Path("StateOfDecay2/Content/GameSystems/Skills/ExperienceRewards.uasset")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def walk_nodes(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk_nodes(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_nodes(child)


def _call_site_tag_candidates(site: dict) -> set[str]:
    roots = [site.get("parameters", []), site.get("related_local_assignments", [])]
    literals = [
        node.get("value")
        for root in roots
        for node in walk_nodes(root)
        if node.get("inst") in {"EX_NameConst", "EX_StringConst"}
        and isinstance(node.get("value"), str)
    ]
    tags = {
        node.get("value")
        for root in roots
        for node in walk_nodes(root)
        if node.get("inst") == "EX_NameConst" and isinstance(node.get("value"), str)
    }
    prefixes = {value for value in literals if value.endswith("Zombie_")}
    suffixes = {value for value in literals if value in {"Lethal", "Nonlethal"}}
    tags.update(prefix + suffix for prefix in prefixes for suffix in suffixes)
    return tags


def _parse_rows(table: dict) -> list[dict]:
    rows = table.get("Rows")
    if not isinstance(rows, dict):
        raise ValueError("ExperienceRewards export has no Rows map")
    parsed = []
    for row_name, row in sorted(rows.items()):
        skills = row.get("Skills") if isinstance(row, dict) else None
        if not isinstance(skills, list):
            raise ValueError("reward row has no Skills array: " + str(row_name))
        skill_rows = []
        for skill in skills:
            award_to = skill.get("AwardTo") if isinstance(skill, dict) else None
            definition = award_to.get("ObjectName") if isinstance(award_to, dict) else None
            experience = skill.get("Experience") if isinstance(skill, dict) else None
            if not isinstance(definition, str) or not isinstance(experience, (int, float)):
                raise ValueError("invalid skill reward row in " + str(row_name))
            if not math.isfinite(float(experience)):
                raise ValueError("non-finite skill XP in " + str(row_name))
            skill_rows.append({
                "skill_definition": definition,
                "experience": float(experience),
            })
        parsed.append({"row_name": row_name, "skills": skill_rows})
    return parsed


def build_report(export_root: Path, call_context_path: Path) -> dict:
    table_path = export_root / DEFAULT_TABLE.with_suffix(".json")
    table_objects = json.loads(table_path.read_text(encoding="utf-8-sig"))
    if not isinstance(table_objects, list) or len(table_objects) != 1:
        raise ValueError("ExperienceRewards export must contain one DataTable object")
    table = table_objects[0]
    if table.get("Type") != "DataTable" or table.get("Name") != "ExperienceRewards":
        raise ValueError("selected export is not the ExperienceRewards DataTable")
    row_struct = table.get("Properties", {}).get("RowStruct", {}).get("ObjectName")
    if row_struct != "ScriptStruct'ExperienceReward'":
        raise ValueError("ExperienceRewards RowStruct does not match expected type")

    call_report = json.loads(call_context_path.read_text(encoding="utf-8-sig"))
    if call_report.get("scope", {}).get("game_process_started_or_attached") is not False:
        raise ValueError("call-context report is not marked as static-only")
    rows = _parse_rows(table)
    row_by_name = {row["row_name"]: row for row in rows}
    tag_references: dict[str, list[dict]] = defaultdict(list)
    for site in call_report.get("call_sites", []):
        for tag in _call_site_tag_candidates(site):
            tag_references[tag].append({
                "asset_path": site.get("asset_path"),
                "blueprint_function": site.get("blueprint_function"),
                "target": site.get("target"),
                "top_level_statement_index": site.get("top_level_statement_index"),
            })

    for row in rows:
        references = tag_references.get(row["row_name"], [])
        row["call_site_reference_count"] = len(references)
        row["call_site_references"] = references
    referenced_tags = sorted(tag_references)
    return {
        "schema": 1,
        "target": call_report.get("target", "target.json"),
        "target_sha256": call_report.get("target_sha256"),
        "source_call_context_report": call_context_path.name,
        "source_call_context_sha256": sha256_file(call_context_path),
        "source_table_asset": "StateOfDecay2/Content/GameSystems/Skills/ExperienceRewards.uasset",
        "source_table_sha256": sha256_file(table_path),
        "method": "Parse the cooked ExperienceRewards DataTable rows and join exact row names to Name literals or explicitly reconstructed prefix/suffix strings in selected serialized Blueprint award-call ASTs.",
        "scope": {
            "game_process_started_or_attached": False,
            "table_row_struct": row_struct,
            "reward_table_row_count": len(rows),
            "call_context_site_count": len(call_report.get("call_sites", [])),
            "call_site_tag_candidate_count": len(referenced_tags),
            "matched_call_tag_count": sum(tag in row_by_name for tag in referenced_tags),
            "unmatched_call_tag_candidates": [tag for tag in referenced_tags if tag not in row_by_name],
        },
        "referenced_call_tags": {
            tag: {
                "table_row_found": tag in row_by_name,
                "call_site_reference_count": len(tag_references[tag]),
                "table_skill_rewards": row_by_name[tag]["skills"] if tag in row_by_name else [],
                "call_site_references": tag_references[tag],
            }
            for tag in referenced_tags
        },
        "reward_rows": rows,
        "limits": [
            "Exact tag-name matches and DataTable reward values establish a serialized data relationship, not proof that a particular native implementation performs the lookup or applies the row at runtime.",
            "Experience values belong to the listed CharacterSkillDefinition rows; this table does not define the proposed mod's survivor-level XP curve or zombie-class base rewards.",
            "The source is an external temporary cooked-export tree; the report records the selected DataTable asset hash and does not redistribute the asset.",
            "No game process or memory was accessed.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("export_root", type=Path, help="temporary directory containing cooked-export JSON")
    parser.add_argument("--call-context-report", type=Path, default=DATABASE / "roguelite-experience-blueprint-call-contexts.json")
    parser.add_argument("--output", type=Path, default=DATABASE / "roguelite-experience-reward-table.json")
    args = parser.parse_args()
    report = build_report(args.export_root, args.call_context_report)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    scope = report["scope"]
    print("PASS: parsed %d ExperienceRewards rows; %d/%d call-tag candidates matched" % (
        scope["reward_table_row_count"], scope["matched_call_tag_count"], scope["call_site_tag_candidate_count"]
    ))


if __name__ == "__main__":
    main()
