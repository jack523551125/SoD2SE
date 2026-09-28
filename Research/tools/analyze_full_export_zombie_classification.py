#!/usr/bin/env python3
"""Extract focused zombie enum, density-category, appearance, and plague-flag evidence.

This reads only an offline Ue4Export JSON tree. Enum display order and the
native zombie-variant byte mapping are recorded with their evidence limits,
while explicit DataTable rows, Blueprint branches, and assignments are kept as
serialized evidence. No XP or death semantics are inferred from these assets.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
DATABASE = ROOT / "Research" / "StateOfDecay2" / "16535856"
ENUM_VALUE = re.compile(rb"AllZombieTypes::NewEnumerator([0-9]+)")
PLAGUE_FLAG_TOKEN = re.compile(rb"(?:IsPlagueZombie|bIsBloodPlagueZombie)")


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def find_object(objects, object_type: str, name: str) -> dict:
    matches = [row for row in objects if row.get("Type") == object_type and row.get("Name") == name]
    if len(matches) != 1:
        raise ValueError("expected one %s object named %s, got %d" % (object_type, name, len(matches)))
    return matches[0]


def extract_enum_display_order(objects) -> dict:
    enum = find_object(objects, "UserDefinedEnum", "AllZombieTypes")
    display_names = enum.get("Properties", {}).get("DisplayNames", [])
    labels = [str(row.get("SourceString", "")) for row in display_names]
    name_map = enum.get("Names", {})
    return {
        "asset": "AI/AllZombieTypes.uasset",
        "display_names_in_serialized_order": labels,
        "enumerator_ordinal_mapping_candidates": [
            {
                "enumerator": "AllZombieTypes::NewEnumerator%d" % index,
                "ordinal": index,
                "display_name_candidate": label,
            }
            for index, label in enumerate(labels)
        ],
        "exported_names_map_entry_count": len(name_map) if isinstance(name_map, (dict, list)) else None,
        "exported_names_map_values": list(name_map.values()) if isinstance(name_map, dict) else None,
        "mapping_basis": "The candidates pair NewEnumeratorN with the Nth serialized DisplayNames item. The export's Names map is recorded separately and is not used to claim the mapping because this build's export has duplicate/zero values.",
    }


def extract_zombie_type_table(objects) -> dict:
    table = find_object(objects, "DataTable", "ZombieTypeDataTable")
    rows = table.get("Rows", {})
    extracted = []
    for row_name, properties in rows.items():
        class_paths = [
            str(value)
            for value in properties.values()
            if isinstance(value, str) and value.startswith("/Game/")
        ]
        extracted.append({"row_name": row_name, "class_paths": class_paths})
    return {
        "asset": "Missions/ZombieEncounter/ZombieTypeDataTable.uasset",
        "row_struct": table.get("Properties", {}).get("RowStruct", {}).get("ObjectName"),
        "row_count": len(rows),
        "rows": extracted,
    }


def extract_zombie_variants_table(objects) -> dict:
    table = find_object(objects, "DataTable", "ZombieVariants")
    rows = table.get("Rows", {})
    variant_key = next(
        (key for row in rows.values() for key in row if key.startswith("ZombieVariantType_")),
        None,
    )
    appearance_key = next(
        (key for row in rows.values() for key in row if key.startswith("ZombieAppearance_")),
        None,
    )
    plague_rows = []
    if variant_key:
        for row_name, row in rows.items():
            variant_type = row.get(variant_key)
            if variant_type == "EZombieVariantType::Plague":
                plague_rows.append({
                    "row_name": row_name,
                    "serialized_variant_type": variant_type,
                    "appearance_path": row.get(appearance_key) if appearance_key else None,
                })
    return {
        "asset": "Art/Characters/Zombie/ZombieVariants.uasset",
        "row_struct": table.get("Properties", {}).get("RowStruct", {}).get("ObjectName"),
        "row_count": len(rows),
        "variant_type_property": variant_key,
        "plague_variant_row_count": len(plague_rows),
        "plague_variant_rows": plague_rows,
    }


def extract_row_struct(objects) -> dict:
    struct_obj = find_object(objects, "UserDefinedStruct", "ZombieTypeStruct")
    prop = next(
        (row for row in objects if row.get("Type") == "AssetClassProperty"
         and row.get("Outer", {}).get("ObjectName") == "UserDefinedStruct'ZombieTypeStruct'"),
        {},
    )
    return {
        "asset": "Missions/ZombieEncounter/ZombieTypeStruct.uasset",
        "struct_flags": struct_obj.get("StructFlags"),
        "property_name": prop.get("Name"),
        "property_meta_class": prop.get("MetaClass", {}).get("ObjectName"),
    }


def extract_boons_banes_categories(objects) -> dict:
    default = find_object(objects, "MGR_AmbientSpawner_C", "Default__MGR_AmbientSpawner_C")
    reductions = default.get("Properties", {}).get("BaseDensityReductions", [])
    categories = [
        str(row.get("ZombieType"))
        for row in reductions
        if isinstance(row, dict) and row.get("ZombieType")
    ]
    return {
        "asset": "AmbientSpawn/MGR_AmbientSpawner.uasset",
        "serialized_property": "Default__MGR_AmbientSpawner_C.Properties.BaseDensityReductions[*].ZombieType",
        "base_density_reduction_category_count": len(categories),
        "base_density_reduction_categories": categories,
    }


def extract_bool_assignments(function: dict, expected_variable: str) -> list[dict]:
    assignments = []
    for instruction in function.get("ScriptBytecode", []):
        if instruction.get("Inst") != "EX_LetBool":
            continue
        variable = instruction.get("Variable", {}).get("Variable", {}).get("ObjectName")
        expression = instruction.get("Expression", {}).get("Inst")
        if variable == expected_variable:
            assignments.append({
                "statement_index": instruction.get("StatementIndex"),
                "variable": variable,
                "serialized_value_token": expression,
                "value_is_true": expression == "EX_True",
            })
    return assignments


def _object_name(value) -> str | None:
    if isinstance(value, dict):
        if isinstance(value.get("ObjectName"), str):
            return value["ObjectName"]
        if isinstance(value.get("Name"), str):
            return value["Name"]
        if "Variable" in value:
            return _object_name(value["Variable"])
    return None


def _expression_source(instruction: dict) -> str | None:
    expression = instruction.get("Expression", {})
    if not isinstance(expression, dict):
        return None
    if expression.get("Inst") == "EX_InstanceVariable":
        return _object_name(expression.get("Variable"))
    return expression.get("Inst")


def extract_generic_plague_variant_logic(objects) -> dict:
    function = find_object(objects, "Function", "SetSpecificCharacterAppearance")
    bytecode = function.get("ScriptBytecode", [])

    table_lookup = None
    for instruction in bytecode:
        if instruction.get("Inst") != "EX_LetBool":
            continue
        expression = instruction.get("Expression", {})
        context = expression.get("ContextExpression", {}) if isinstance(expression, dict) else {}
        if context.get("Inst") != "EX_FinalFunction":
            continue
        function_name = context.get("Function", {}).get("ObjectName")
        parameters = context.get("Parameters", [])
        table_arg = next(
            (row.get("Value", {}).get("ObjectName") for row in parameters
             if row.get("Inst") == "EX_ObjectConst" and "ZombieVariants" in row.get("Value", {}).get("ObjectName", "")),
            None,
        )
        if function_name == "Function'DataTableFunctionLibrary:GetDataTableRowFromName'" and table_arg:
            row_name_arg = next(
                (_object_name(row) for row in parameters if row.get("Inst") == "EX_InstanceVariable"),
                None,
            )
            table_lookup = {
                "function": function_name,
                "table": table_arg,
                "row_name_source": row_name_arg,
            }
            break
    if table_lookup is None:
        raise ValueError("SetSpecificCharacterAppearance does not contain expected ZombieVariants row lookup")

    comparisons = []
    for instruction in bytecode:
        if instruction.get("Inst") != "EX_LetBool":
            continue
        expression = instruction.get("Expression", {})
        if expression.get("Inst") != "EX_CallMath":
            continue
        if expression.get("Function", {}).get("ObjectName") != "Function'KismetMathLibrary:NotEqual_ByteByte'":
            continue
        parameters = expression.get("Parameters", [])
        if len(parameters) != 2 or parameters[1].get("Inst") != "EX_ByteConst":
            continue
        first = parameters[0]
        field_name = first.get("Property", {}).get("ObjectName")
        if first.get("Inst") == "EX_StructMemberContext" and isinstance(field_name, str) and field_name.startswith("ByteProperty'ZombieContentVariant:ZombieVariantType_"):
            comparisons.append({
                "statement_index": instruction.get("StatementIndex"),
                "result_local": _object_name(instruction.get("Variable")),
                "operator": "NotEqual_ByteByte",
                "variant_type_property": field_name,
                "byte_value": parameters[1].get("Value"),
            })
    if not comparisons:
        raise ValueError("SetSpecificCharacterAppearance has no recognized ZombieVariantType byte comparison")

    expected_flags = {
        "BoolProperty'DaytonZombieCharacter:bIsBloodPlagueZombie'",
        "BoolProperty'ZombieCharacter_C:IsPlagueZombie'",
    }
    numbered_comparisons = sorted(comparisons, key=lambda row: row.get("statement_index") or -1)
    matching = None
    for index, comparison in enumerate(numbered_comparisons):
        current_index = comparison.get("statement_index")
        next_index = numbered_comparisons[index + 1].get("statement_index") if index + 1 < len(numbered_comparisons) else None
        jump = next((
            instruction for instruction in bytecode
            if instruction.get("Inst") == "EX_JumpIfNot"
            and _object_name(instruction.get("BooleanExpression")) == comparison["result_local"]
            and isinstance(instruction.get("StatementIndex"), int)
            and isinstance(current_index, int)
            and instruction["StatementIndex"] > current_index
            and (not isinstance(next_index, int) or instruction["StatementIndex"] < next_index)
        ), None)
        if jump is None:
            continue
        branch_target = jump.get("CodeOffset")
        branch_instructions = [
            instruction for instruction in bytecode
            if isinstance(instruction.get("StatementIndex"), int)
            and isinstance(branch_target, int)
            and branch_target <= instruction["StatementIndex"] < branch_target + 40
        ]
        writes = []
        for instruction in branch_instructions:
            if instruction.get("Inst") != "EX_LetBool":
                continue
            target = _object_name(instruction.get("Variable"))
            if target == "IsPlagueZombie":
                target = "BoolProperty'ZombieCharacter_C:IsPlagueZombie'"
            value_token = instruction.get("Expression", {}).get("Inst")
            if target in expected_flags:
                writes.append({
                    "statement_index": instruction.get("StatementIndex"),
                    "variable": target,
                    "serialized_value_token": value_token,
                })
        if len({row["variable"] for row in writes if row["serialized_value_token"] == "EX_True"}) == 2:
            matching = (comparison, jump, writes)
            break
    if matching is None:
        raise ValueError("no ZombieVariantType equality branch writes both plague flags true")
    compare, jump, writes = matching
    branch_target = jump.get("CodeOffset")
    return {
        "asset": "Characters/Zombie/ZombieCharacter.uasset",
        "function": function.get("Name"),
        "table_lookup": table_lookup,
        "comparison": compare,
        "conditional_branch": {
            "statement_index": jump.get("StatementIndex"),
            "opcode": jump.get("Inst"),
            "code_offset": branch_target,
            "branch_condition": "The stored NotEqual result is false, so the compared byte equals byte_value.",
        },
        "equal_value_branch_flag_writes": writes,
        "interpretation": "Rows serialized as EZombieVariantType::Plague correlate with the byte-equality branch that writes both plague flags. The fixed-build native enum registrar independently provides a strong static ordinal inference of Slow=0, Unique=1, Fast=2, Armored=3, Plague=4; the native setter is virtual and unnamed, so the mapping remains an inference rather than runtime confirmation.",
    }


def extract_serialized_flag_inventory(export_root: Path, relative_paths: list[str]) -> dict:
    default_assignments = []
    bytecode_assignments = []
    for relative in sorted(relative_paths):
        objects = read_json(export_root / relative)
        for obj in objects:
            properties = obj.get("Properties", {})
            if not isinstance(properties, dict):
                continue
            for field in ("IsPlagueZombie", "bIsBloodPlagueZombie"):
                if field in properties:
                    default_assignments.append({
                        "asset": relative,
                        "object": obj.get("Name"),
                        "field": field,
                        "serialized_value": properties[field],
                    })
            if obj.get("Type") != "Function":
                continue
            for field_name in (
                "BoolProperty'ZombieCharacter_C:IsPlagueZombie'",
                "BoolProperty'DaytonZombieCharacter:bIsBloodPlagueZombie'",
            ):
                for assignment in extract_bool_assignments(obj, field_name):
                    bytecode_assignments.append({
                        "asset": relative,
                        "function": obj.get("Name"),
                        "field": field_name,
                        "statement_index": assignment.get("statement_index"),
                        "serialized_value_token": assignment.get("serialized_value_token"),
                        "value_is_true": assignment.get("value_is_true"),
                        "source": _expression_source(next(
                            row for row in obj.get("ScriptBytecode", [])
                            if row.get("StatementIndex") == assignment.get("statement_index")
                        )),
                    })
    return {
        "candidate_asset_count": len(relative_paths),
        "candidate_assets": sorted(relative_paths),
        "default_object_flag_values": default_assignments,
        "bytecode_flag_assignments": bytecode_assignments,
    }


def extract_explicit_plague_flag_evidence(export_root: Path) -> dict:
    normal_objects = read_json(
        export_root / "StateOfDecay2/Content/Characters/Zombie/Presets/Zombie_Plague.json"
    )
    normal_cdo = find_object(normal_objects, "Zombie_Plague_C", "Default__Zombie_Plague_C")
    normal_flag = normal_cdo.get("Properties", {}).get("IsPlagueZombie")

    special_asset_paths = {
        "BpBloater": "Characters/Bloater/BloodBloater.json",
        "BpFeral": "Characters/Feral/BloodFeral.json",
        "BpScreamer": "Characters/Screamer/BloodScreamer.json",
        "BpJuggernaut": "Characters/Juggernaut/BloodPlagueJuggCharacter.json",
    }
    special_rows = []
    expected_variable = "BoolProperty'DaytonZombieCharacter:bIsBloodPlagueZombie'"
    for row_name, relative_path in special_asset_paths.items():
        objects = read_json(export_root / "StateOfDecay2/Content" / relative_path)
        functions = [
            row for row in objects
            if row.get("Type") == "Function" and row.get("Name") == "UserConstructionScript"
        ]
        if len(functions) != 1:
            raise ValueError("expected one UserConstructionScript in " + relative_path)
        function = functions[0]
        bytecode = function.get("ScriptBytecode", [])
        assignments = extract_bool_assignments(function, expected_variable)
        parent_call = next(
            (
                instruction.get("Function", {}).get("ObjectName")
                for instruction in bytecode
                if instruction.get("Inst") == "EX_FinalFunction"
            ),
            None,
        )
        special_rows.append({
            "data_table_row": row_name,
            "asset": "StateOfDecay2/Content/" + relative_path.replace("\\", "/"),
            "blueprint_class_name": next(
                (row.get("Name") for row in objects if row.get("Type") == "BlueprintGeneratedClass"),
                None,
            ),
            "construction_function": function.get("Name"),
            "parent_construction_call": parent_call,
            "explicit_assignments": assignments,
        })

    return {
        "normal_plague_preset": {
            "asset": "Characters/Zombie/Presets/Zombie_Plague.uasset",
            "class": "Zombie_Plague_C",
            "default_object": normal_cdo.get("Name"),
            "field": "IsPlagueZombie",
            "serialized_value": normal_flag,
        },
        "blood_plague_special_presets": special_rows,
        "limits": [
            "IsPlagueZombie and bIsBloodPlagueZombie are separate serialized properties; this report does not assert they are aliases or mutually exclusive.",
            "The special-preset evidence is Blueprint construction bytecode, not a runtime observation of victim objects or death-event payloads.",
        ],
    }


def scan_enum_usage(export_root: Path) -> dict:
    asset_roots = sorted((path for path in export_root.iterdir() if path.is_dir()), key=lambda path: path.name.casefold())
    if not asset_roots:
        raise ValueError("full export root must contain provider asset subtrees")
    counts: dict[int, int] = {}
    files_by_value: dict[int, set[str]] = {}
    bytes_scanned = 0
    files_seen = 0
    errors = []
    plague_flag_assets: set[str] = set()
    for asset_root in asset_roots:
        for path in asset_root.rglob("*.json"):
            files_seen += 1
            try:
                raw = path.read_bytes()
            except OSError as error:
                errors.append({"path": str(path), "error": type(error).__name__})
                continue
            bytes_scanned += len(raw)
            relative = path.relative_to(export_root).as_posix()
            if PLAGUE_FLAG_TOKEN.search(raw):
                plague_flag_assets.add(relative)
            for match in ENUM_VALUE.finditer(raw):
                ordinal = int(match.group(1))
                counts[ordinal] = counts.get(ordinal, 0) + 1
                files_by_value.setdefault(ordinal, set()).add(relative)
    return {
        "json_files_seen": files_seen,
        "json_bytes_scanned": bytes_scanned,
        "decode_errors": len(errors),
        "errors": errors,
        "serialized_reference_count": sum(counts.values()),
        "enumerator_reference_counts": {
            "AllZombieTypes::NewEnumerator%d" % ordinal: count
            for ordinal, count in sorted(counts.items())
        },
        "assets_by_enumerator": {
            "AllZombieTypes::NewEnumerator%d" % ordinal: sorted(paths)
            for ordinal, paths in sorted(files_by_value.items())
        },
        "plague_flag_asset_paths": sorted(plague_flag_assets),
    }


def build_report(export_root: Path, target_path: Path) -> dict:
    enum_objects = read_json(export_root / "StateOfDecay2/Content/AI/AllZombieTypes.json")
    table_objects = read_json(export_root / "StateOfDecay2/Content/Missions/ZombieEncounter/ZombieTypeDataTable.json")
    struct_objects = read_json(export_root / "StateOfDecay2/Content/Missions/ZombieEncounter/ZombieTypeStruct.json")
    ambient_objects = read_json(export_root / "StateOfDecay2/Content/AmbientSpawn/MGR_AmbientSpawner.json")
    zombie_variants_objects = read_json(export_root / "StateOfDecay2/Content/Art/Characters/Zombie/ZombieVariants.json")
    zombie_character_objects = read_json(export_root / "StateOfDecay2/Content/Characters/Zombie/ZombieCharacter.json")
    usage = scan_enum_usage(export_root)
    plague_inventory = extract_serialized_flag_inventory(export_root, usage["plague_flag_asset_paths"])
    target = read_json(target_path)
    return {
        "schema": 1,
        "target": "target.json",
        "target_sha256": str(target.get("sha256", "")).upper(),
        "native_enum_registration_report": "zombie-variant-enum-native-registration.json",
        "native_plague_flag_name_reference_report": "zombie-plague-flag-native-name-references.json",
        "method": "Parse exact serialized Ue4Export JSON assets and scan every JSON under every immediate provider-asset subtree for AllZombieTypes::NewEnumeratorN and plague-flag tokens; root-level analysis sidecars are excluded.",
        "scope": {
            "game_process_started_or_attached": False,
            "export_root_name": export_root.name,
            "provider_asset_roots": sorted(path.name for path in export_root.iterdir() if path.is_dir()),
            "enum_usage_json_files": usage["json_files_seen"],
            "enum_usage_json_bytes_scanned": usage["json_bytes_scanned"],
            "enum_usage_decode_errors": usage["decode_errors"],
        },
        "all_zombie_types_enum": extract_enum_display_order(enum_objects),
        "enum_usage": usage,
        "zombie_type_struct": extract_row_struct(struct_objects),
        "zombie_type_data_table": extract_zombie_type_table(table_objects),
        "zombie_variants_data_table": extract_zombie_variants_table(zombie_variants_objects),
        "generic_plague_variant_logic": extract_generic_plague_variant_logic(zombie_character_objects),
        "serialized_plague_flag_inventory": plague_inventory,
        "boons_banes_density_categories": extract_boons_banes_categories(ambient_objects),
        "explicit_plague_flag_evidence": extract_explicit_plague_flag_evidence(export_root),
        "interpretation": [
            "ZombieTypeDataTable serializes preset-class paths, including separate Plague, BpJuggernaut, BpBloater, BpScreamer and BpFeral rows. This is class/spawn data, not proof that every death event carries or uses this row name.",
            "Zombie_Plague_C defaults IsPlagueZombie to true; all four Bp special presets' serialized UserConstructionScript bytecode calls the parent constructor and writes DaytonZombieCharacter.bIsBloodPlagueZombie=true. These explicit blueprint flags refine asset-level blood-plague classification but do not prove the reward path reads them.",
            "ZombieVariants has 28 serialized appearance rows, including three rows labeled EZombieVariantType::Plague. ZombieCharacter_C:SetSpecificCharacterAppearance reads this table using its ZombieVariant instance property, compares the variant-type byte to 4, and the equality branch writes IsPlagueZombie=true and bIsBloodPlagueZombie=true. The fixed-build native enum registrar provides a strong static inference of Slow=0, Unique=1, Fast=2, Armored=3, Plague=4, independently supporting the byte-4/Plague match; the virtual setter remains unnamed and the map is not runtime-confirmed.",
            "AllZombieTypes display labels and NewEnumeratorN ordinal pairing are recorded as candidates based on array order; do not conflate this AI targeting enum with award or death classification.",
            "Boons/Banes BaseDensityReductions lists zombie-type categories for density settings only; its enum taxonomy is not proven equivalent to the spawn table or experience classification.",
        ],
        "limits": [
            "No runtime victim UObject/class observation, death event payload, XP class branch, or blood-plague flag combination has been verified.",
            "The fixed-build native EZombieVariantType ordinal map is a strong inference from native registration order and an unnamed virtual setter, not runtime confirmation; it identifies the byte-4 branch as Plague but does not prove which victim fields a death event supplies or whether XP reads either plague flag.",
            "No crosswalk is inferred between AllZombieTypes, EBoonsBanesZombieType, ZombieTypeDataTable row names, or reward categories.",
            "The display-name ordinal pairing is candidate evidence from serialization order; the exporter's Names map is retained verbatim because its values are not usable as a unique ordinal map in this dump.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("export_root", type=Path, help="root of the offline full Ue4Export JSON tree")
    parser.add_argument("--target", type=Path, default=DATABASE / "target.json")
    parser.add_argument("--output", type=Path, default=DATABASE / "roguelite-enemy-classification-static.json")
    args = parser.parse_args()
    report = build_report(args.export_root, args.target)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        "PASS: %d enum references across %d JSONs; %d zombie class rows; %d density categories"
        % (
            report["enum_usage"]["serialized_reference_count"],
            report["scope"]["enum_usage_json_files"],
            report["zombie_type_data_table"]["row_count"],
            report["boons_banes_density_categories"]["base_density_reduction_category_count"],
        )
    )


if __name__ == "__main__":
    main()
