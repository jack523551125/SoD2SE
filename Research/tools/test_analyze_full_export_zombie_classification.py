import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from analyze_full_export_zombie_classification import (
    extract_bool_assignments,
    extract_enum_display_order,
    extract_generic_plague_variant_logic,
    extract_zombie_type_table,
    extract_zombie_variants_table,
    scan_enum_usage,
)


class AnalyzeFullExportZombieClassificationTests(unittest.TestCase):
    def test_enum_ordinal_mapping_uses_display_order_not_corrupt_name_map_values(self):
        result = extract_enum_display_order([{
            "Type": "UserDefinedEnum",
            "Name": "AllZombieTypes",
            "Properties": {"DisplayNames": [
                {"SourceString": "Generic"},
                {"SourceString": "Screamer"},
                {"SourceString": "Bloater"},
            ]},
            "Names": {"one": 0, "two": 0, "three": 0},
        }])

        self.assertEqual(
            [row["display_name_candidate"] for row in result["enumerator_ordinal_mapping_candidates"]],
            ["Generic", "Screamer", "Bloater"],
        )
        self.assertEqual(result["exported_names_map_values"], [0, 0, 0])

    def test_data_table_retains_exact_row_to_class_paths(self):
        result = extract_zombie_type_table([{
            "Type": "DataTable",
            "Name": "ZombieTypeDataTable",
            "Properties": {"RowStruct": {"ObjectName": "UserDefinedStruct'ZombieTypeStruct'"}},
            "Rows": {
                "Plague": {"ClassAsset": "/Game/Zombie_Plague_C"},
                "BpFeral": {"ClassAsset": "/Game/Blood_Feral_C"},
            },
        }])

        self.assertEqual(result["row_count"], 2)
        self.assertEqual(result["rows"][1]["class_paths"], ["/Game/Blood_Feral_C"])

    def test_zombie_variant_table_extracts_only_serialized_plague_rows(self):
        result = extract_zombie_variants_table([{
            "Type": "DataTable",
            "Name": "ZombieVariants",
            "Properties": {"RowStruct": {"ObjectName": "UserDefinedStruct'ZombieContentVariant'"}},
            "Rows": {
                "MalePlague01": {
                    "ZombieVariantType_1": "EZombieVariantType::Plague",
                    "ZombieAppearance_2": "/Game/PlagueAppearance",
                },
                "MaleRegular01": {
                    "ZombieVariantType_1": "EZombieVariantType::Slow",
                    "ZombieAppearance_2": "/Game/RegularAppearance",
                },
            },
        }])

        self.assertEqual(result["row_count"], 2)
        self.assertEqual(result["plague_variant_row_count"], 1)
        self.assertEqual(result["plague_variant_rows"][0]["row_name"], "MalePlague01")

    def test_generic_appearance_function_ties_byte_branch_to_both_plague_flag_writes(self):
        flag_a = "BoolProperty'ZombieCharacter_C:IsPlagueZombie'"
        flag_b = "BoolProperty'DaytonZombieCharacter:bIsBloodPlagueZombie'"

        def compare(index, byte_value):
            return {
                "Inst": "EX_LetBool", "StatementIndex": index,
                "Variable": {"Inst": "EX_LocalVariable", "Variable": {"Name": "SwitchResult"}},
                "Expression": {
                    "Inst": "EX_CallMath",
                    "Function": {"ObjectName": "Function'KismetMathLibrary:NotEqual_ByteByte'"},
                    "Parameters": [
                        {"Inst": "EX_StructMemberContext", "Property": {
                            "ObjectName": "ByteProperty'ZombieContentVariant:ZombieVariantType_test'"
                        }},
                        {"Inst": "EX_ByteConst", "Value": byte_value},
                    ],
                },
            }

        function = {
            "Type": "Function", "Name": "SetSpecificCharacterAppearance",
            "ScriptBytecode": [
                {
                    "Inst": "EX_LetBool", "StatementIndex": 1,
                    "Expression": {
                        "Inst": "EX_Context",
                        "ContextExpression": {
                            "Inst": "EX_FinalFunction",
                            "Function": {"ObjectName": "Function'DataTableFunctionLibrary:GetDataTableRowFromName'"},
                            "Parameters": [
                                {"Inst": "EX_ObjectConst", "Value": {"ObjectName": "DataTable'ZombieVariants'"}},
                                {"Inst": "EX_InstanceVariable", "Variable": {"Name": "ZombieVariant"}},
                            ],
                        },
                    },
                },
                compare(10, 3),
                {"Inst": "EX_JumpIfNot", "StatementIndex": 20, "BooleanExpression": {
                    "Inst": "EX_LocalVariable", "Variable": {"Name": "SwitchResult"}
                }, "CodeOffset": 200},
                compare(30, 4),
                {"Inst": "EX_JumpIfNot", "StatementIndex": 40, "BooleanExpression": {
                    "Inst": "EX_LocalVariable", "Variable": {"Name": "SwitchResult"}
                }, "CodeOffset": 300},
                {"Inst": "EX_LetBool", "StatementIndex": 300, "Variable": {
                    "Inst": "EX_InstanceVariable", "Variable": {"ObjectName": flag_a}
                }, "Expression": {"Inst": "EX_True"}},
                {"Inst": "EX_LetBool", "StatementIndex": 310, "Variable": {
                    "Inst": "EX_InstanceVariable", "Variable": {"ObjectName": flag_b}
                }, "Expression": {"Inst": "EX_True"}},
            ],
        }

        result = extract_generic_plague_variant_logic([function])

        self.assertEqual(result["table_lookup"]["row_name_source"], "ZombieVariant")
        self.assertEqual(result["comparison"]["byte_value"], 4)
        self.assertEqual(
            {row["variable"] for row in result["equal_value_branch_flag_writes"]},
            {flag_a, flag_b},
        )

    def test_censuses_enum_tokens_and_package_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            asset = root / "StateOfDecay2" / "Content" / "AI" / "Tree.json"
            asset.parent.mkdir(parents=True)
            asset.write_text(
                json.dumps({
                    "a": "AllZombieTypes::NewEnumerator3",
                    "b": "AllZombieTypes::NewEnumerator3",
                    "field": "BoolProperty'DaytonZombieCharacter:bIsBloodPlagueZombie'",
                }),
                encoding="utf-8",
            )
            result = scan_enum_usage(root)

        self.assertEqual(result["json_files_seen"], 1)
        self.assertEqual(result["serialized_reference_count"], 2)
        self.assertEqual(result["plague_flag_asset_paths"], ["StateOfDecay2/Content/AI/Tree.json"])
        self.assertEqual(result["enumerator_reference_counts"]["AllZombieTypes::NewEnumerator3"], 2)
        self.assertEqual(
            result["assets_by_enumerator"]["AllZombieTypes::NewEnumerator3"],
            ["StateOfDecay2/Content/AI/Tree.json"],
        )

    def test_extracts_only_explicit_true_assignment_to_requested_flag(self):
        function = {"ScriptBytecode": [
            {
                "Inst": "EX_LetBool",
                "StatementIndex": 10,
                "Variable": {"Variable": {"ObjectName": "BoolProperty'DaytonZombieCharacter:bIsBloodPlagueZombie'"}},
                "Expression": {"Inst": "EX_True"},
            },
            {
                "Inst": "EX_LetBool",
                "StatementIndex": 20,
                "Variable": {"Variable": {"ObjectName": "BoolProperty'Other:Flag'"}},
                "Expression": {"Inst": "EX_False"},
            },
        ]}
        rows = extract_bool_assignments(function, "BoolProperty'DaytonZombieCharacter:bIsBloodPlagueZombie'")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["statement_index"], 10)
        self.assertEqual(rows[0]["serialized_value_token"], "EX_True")
        self.assertIs(rows[0]["value_is_true"], True)


if __name__ == "__main__":
    unittest.main()
