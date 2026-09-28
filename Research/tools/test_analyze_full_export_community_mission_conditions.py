import json
import tempfile
import unittest
from pathlib import Path

from analyze_full_export_community_mission_conditions import analyze


class FullExportCommunityMissionConditionTests(unittest.TestCase):
    def test_counts_nested_conditions_and_missing_defaults_without_guessing(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            provider_root = root / "StateOfDecay2" / "Content"
            provider_root.mkdir(parents=True)
            (provider_root / "a.json").write_text(
                '\ufeff' + json.dumps([
                    {
                        "Type": "MissionRecord",
                        "Conditions": [
                            {
                                "Type": "CommunityMissionCondition",
                                "Name": "Explicit",
                                "Properties": {
                                    "ComparisonStat": "ECommunityConditionStat::CommunityMembers",
                                    "Comparison": "EMissionConditionComparison::LessOrEqual",
                                    "Value": 7,
                                },
                            },
                            {
                                "Type": "CommunityMissionCondition",
                                "Name": "Implicit",
                                "Properties": {
                                    "ComparisonStat": "ECommunityConditionStat::CommunityMembers",
                                    "Value": 11,
                                },
                            },
                        ],
                    }
                ]),
                encoding="utf-8",
            )
            (provider_root / "unrelated.json").write_text('{"Type":"Other"}', encoding="utf-8")
            (provider_root / "definitions.json").write_text(json.dumps([
                {"Type": "UserDefinedEnum", "Name": "EMissionConditionComparison"},
                {"Type": "UserDefinedStruct", "Name": "CommunityMissionCondition"},
                {"Name": "Default__CommunityMissionCondition"},
            ]), encoding="utf-8")
            (root / "root-analysis-sidecar.json").write_text('{"Type":"CommunityMissionCondition"}', encoding="utf-8")

            report = analyze(root)

        self.assertEqual(report["scope"]["json_files_seen"], 3)
        self.assertEqual(report["scope"]["provider_asset_roots"], ["StateOfDecay2"])
        self.assertEqual(report["scope"]["candidate_files"], 1)
        self.assertEqual(report["summary"]["condition_object_count"], 2)
        self.assertEqual(report["summary"]["comparison_field_present_count"], 1)
        self.assertEqual(report["summary"]["comparison_field_missing_count"], 1)
        self.assertEqual(report["summary"]["missing_by_stat"], {"ECommunityConditionStat::CommunityMembers": 1})
        self.assertFalse(report["scope"]["class_default_inferred"])
        self.assertEqual(report["static_definition_search"]["default_object_name_hit_count"], 1)
        self.assertEqual(report["static_definition_search"]["comparison_enum_definition_count"], 1)
        self.assertEqual(report["static_definition_search"]["condition_struct_definition_count"], 1)
        self.assertEqual(report["errors"], [])


if __name__ == "__main__":
    unittest.main()
