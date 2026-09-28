import json
import tempfile
import unittest
from pathlib import Path

from analyze_roguelite_experience_blueprint_call_contexts import build_report


class ExperienceBlueprintCallContextTests(unittest.TestCase):
    def test_extracts_call_arguments_and_transitive_local_assignments(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            export_root = root / "exports"
            asset_path = "StateOfDecay2/Content/TestAsset.uasset"
            export_path = export_root / "StateOfDecay2" / "Content" / "TestAsset.json"
            export_path.parent.mkdir(parents=True)
            target = "Function'CharacterBlueprintHelpers:AuthAwardExperience'"
            export_path.write_text(json.dumps([
                {
                    "Type": "Function",
                    "Name": "AwardTestExperience",
                    "ScriptBytecode": [
                        {
                            "Inst": "EX_Let",
                            "StatementIndex": 4,
                            "Variable": {"Inst": "EX_LocalVariable", "Variable": {"Name": "AwardTag"}},
                            "Expression": {"Inst": "EX_NameConst", "Value": "Fighting_Zombie_Close_Lethal"},
                        },
                        {
                            "Inst": "EX_Context",
                            "StatementIndex": 9,
                            "ContextExpression": {
                                "Inst": "EX_FinalFunction",
                                "Function": {"ObjectName": target},
                                "Parameters": [
                                    {"Inst": "EX_LocalVariable", "Variable": {"Name": "Attacker"}},
                                    {"Inst": "EX_LocalVariable", "Variable": {"Name": "AwardTag"}},
                                ],
                            },
                        },
                    ],
                }
            ]), encoding="utf-8")
            census = {
                "target": "target.json",
                "target_sha256": "A" * 64,
                "scope": {"game_process_started_or_attached": False},
                "call_references": [{
                    "asset_path": asset_path,
                    "blueprint_function": "AwardTestExperience",
                    "target": target,
                    "token": "EX_FinalFunction",
                }],
            }
            census_path = root / "census.json"
            census_path.write_text(json.dumps(census), encoding="utf-8")

            report = build_report(export_root, census_path)

        self.assertEqual(report["scope"]["serialized_award_call_count"], 1)
        site = report["call_sites"][0]
        self.assertEqual(site["parameters"][1]["variable"], "AwardTag")
        self.assertEqual(site["top_level_statement_index"], 9)
        self.assertEqual(site["related_local_assignments"][0]["variable"], "AwardTag")
        self.assertEqual(
            site["related_local_assignments"][0]["assignments"][0]["expression"]["value"],
            "Fighting_Zombie_Close_Lethal",
        )

    def test_summarizes_switch_value_cases(self):
        from analyze_roguelite_experience_blueprint_call_contexts import summarize_expression

        summary = summarize_expression({
            "Inst": "EX_SwitchValue",
            "IndexTerm": {"Inst": "EX_LocalVariable", "Variable": {"Name": "IsLethal"}},
            "Cases": [
                {"CaseIndexValueTerm": {"Inst": "EX_False"}, "CaseTerm": {"Inst": "EX_NameConst", "Value": "Nonlethal"}},
                {"CaseIndexValueTerm": {"Inst": "EX_True"}, "CaseTerm": {"Inst": "EX_NameConst", "Value": "Lethal"}},
            ],
        })
        self.assertEqual(summary["inst"], "EX_SwitchValue")
        self.assertEqual(summary["indexTerm"]["variable"], "IsLethal")
        self.assertEqual(summary["cases"][0]["caseTerm"]["value"], "Nonlethal")
        self.assertEqual(summary["cases"][1]["caseTerm"]["value"], "Lethal")


if __name__ == "__main__":
    unittest.main()
