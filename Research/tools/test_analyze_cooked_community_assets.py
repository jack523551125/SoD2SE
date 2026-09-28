import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from analyze_cooked_community_assets import (
    analyze_exports,
    analyze_event_name_groups,
    select_specific_symbol_candidates,
    _iter_blueprint_call_references,
)


def _mission_package(comparison="EMissionConditionComparison::LessOrEqual"):
    return [
        {
            "Type": "MissionAsset",
            "Name": "Sample",
            "Properties": {
                "Events": {
                    "Condition": [
                        {
                            "Condition": {
                                "ObjectName": "CommunityMissionCondition'Sample:CommunityMissionCondition_0'",
                                "ObjectPath": "Game/Content/Story/Sample.0",
                            },
                            "EventName": "CommunitySizeGate",
                            "EventIndexes": [{"EventType": {"AbsoluteName": "Missions.RecruitCharacter"}, "Index": 0}],
                            "ElseEventIndexes": [],
                        },
                        {
                            "EventName": "CommunitySizeGate",
                            "EventIndexes": [],
                            "ElseEventIndexes": [],
                            "Condition": {
                                "ObjectName": "CommunityMissionCondition'Sample:CommunityMissionCondition_0'",
                                "ObjectPath": "Game/Content/Story/Sample.0",
                            },
                        },
                    ],
                    "RecruitCharacter": [{
                        "EventName": "DifferentEvent",
                        "EnclaveName": "PlayerCommunity",
                        "CharacterName": "NPC01",
                    }],
                },
                "Missions": [
                    {
                        "Name": "Branch_AddMember",
                        "bAddsCharactersToPlayerEnclave": True,
                        "bIgnoresPopulationCap": False,
                        "OnBranchEvents": [{"EventType": {"AbsoluteName": "Missions.Condition"}, "Index": 0}],
                    }
                ],
            },
        },
        {
            "Type": "CommunityMissionCondition",
            "Name": "CommunityMissionCondition_0",
            "Properties": {
                "ComparisonStat": "ECommunityConditionStat::CommunityMembers",
                "Value": 11.0,
                **({"Comparison": comparison} if comparison is not None else {}),
            },
        },
    ]


class AnalyzeCookedCommunityAssetsTests(unittest.TestCase):
    def test_specific_symbol_selection_excludes_path_selected_assets(self):
        report = select_specific_symbol_candidates(
            {
                "pak_count": 35,
                "findings": [
                    {"asset": "UI/RecruitScreen.uasset", "uncompressed_size": 10, "symbols": ["RecruitCharacter"]},
                    {"asset": "EnclaveGeneration/RecruitA.uasset", "uncompressed_size": 20, "symbols": ["bRecruitable"]},
                    {"asset": "Characters/Unrelated.uasset", "uncompressed_size": 30, "symbols": ["Health"]},
                ],
            },
            {"findings": [{"asset": "ui/recruitscreen.uasset"}]},
        )
        self.assertEqual(report["selected_uasset_count"], 1)
        self.assertEqual(report["selected_uncompressed_bytes"], 20)
        self.assertEqual(report["findings"][0]["asset"], "EnclaveGeneration/RecruitA.uasset")

    def test_bytecode_call_extractor_keeps_virtual_names_and_final_function_targets(self):
        calls = list(_iter_blueprint_call_references([
            {"Inst": "EX_VirtualFunction", "Function": "CanAddCharacter"},
            {"Inst": "EX_FinalFunction", "Function": {"ObjectName": "Function'CommunityComponent:GetEnclave'", "ObjectPath": "/Script/DaytonGame"}},
            {"Inst": "EX_LocalVariable", "Variable": {"Name": "CommunityMembers"}},
        ]))
        self.assertEqual(calls, [
            ("EX_VirtualFunction", "CanAddCharacter", None),
            ("EX_FinalFunction", "Function'CommunityComponent:GetEnclave'", "/Script/DaytonGame"),
        ])

    def test_follows_condition_to_recruit_and_preserves_comparison(self):
        with tempfile.TemporaryDirectory() as temp:
            export_dir = Path(temp)
            package_path = export_dir / "StateOfDecay2" / "Content" / "Story" / "Sample.json"
            package_path.parent.mkdir(parents=True)
            package_path.write_text(json.dumps(_mission_package()), encoding="utf-8")
            report = analyze_exports(
                export_dir,
                {"assets": [{"asset": "Story/Sample.uasset"}]},
                {"findings": [{"asset": "Story/Sample.uasset"}]},
            )

        package = report["mission_summary"]["packages"][0]
        record = package["mission_event_graph"]["records"][0]
        self.assertEqual(package["mission_record_count"], 1)
        self.assertEqual(package["community_member_comparison_counts"], {"EMissionConditionComparison::LessOrEqual": 1})
        self.assertEqual(record["reachable_community_member_conditions"][0]["value"], 11.0)
        self.assertEqual(record["reachable_community_member_conditions"][0]["event_name"], "CommunitySizeGate")
        self.assertEqual(record["reachable_recruit_events"][0]["character_name"], "NPC01")
        self.assertEqual(record["reachable_recruit_events"][0]["event_name"], "DifferentEvent")
        self.assertEqual(package["event_name_analysis"]["same_type_duplicate_group_count"], 1)
        self.assertEqual(package["event_name_analysis"]["cross_type_reuse_group_count"], 0)
        self.assertEqual(report["mission_summary"]["event_name_inventory"]["named_event_record_count"], 3)
        condition_coverage = report["mission_summary"]["community_condition_comparison_coverage"]
        self.assertEqual(condition_coverage["condition_count"], 1)
        self.assertEqual(condition_coverage["explicit_equal_count"], 0)
        self.assertEqual(report["mission_summary"]["mission_records_with_reachable_recruit_event"], 1)

    def test_event_name_inventory_reports_collisions_without_linking_them(self):
        summary = analyze_event_name_groups({
            "Condition": [
                {"EventName": "Shared", "EventIndexes": []},
                {"EventName": "Shared", "EventIndexes": []},
                {"EventName": "None"},
            ],
            "RecruitCharacter": [{"EventName": "Shared"}],
        })
        self.assertEqual(summary["named_event_record_count"], 3)
        self.assertEqual(summary["unique_named_event_count"], 1)
        self.assertEqual(summary["same_type_duplicate_group_count"], 1)
        self.assertEqual(summary["cross_type_reuse_group_count"], 1)
        self.assertTrue(any("not added as an execution edge" in item for item in summary["limits"]))

    def test_missing_comparison_is_not_guessed(self):
        with tempfile.TemporaryDirectory() as temp:
            export_dir = Path(temp)
            package_path = export_dir / "Story" / "Sample.json"
            package_path.parent.mkdir(parents=True)
            package_path.write_text(json.dumps(_mission_package(comparison=None)), encoding="utf-8")
            report = analyze_exports(
                export_dir,
                {"assets": [{"asset": "Story/Sample.uasset"}]},
                {"findings": [{"asset": "Story/Sample.uasset"}]},
            )

        package = report["mission_summary"]["packages"][0]
        condition = package["mission_event_graph"]["records"][0]["reachable_community_member_conditions"][0]
        self.assertIsNone(condition["comparison"])
        self.assertEqual(package["community_member_conditions_without_explicit_comparison"], 1)
        self.assertEqual(report["mission_summary"]["community_condition_comparison_coverage"]["missing_comparison_count"], 1)

    def test_export_coverage_is_separate_from_missionasset_presence(self):
        with tempfile.TemporaryDirectory() as temp:
            export_dir = Path(temp)
            package_path = export_dir / "GameSystems" / "Enclave" / "CommunityScreenLayoutMode.json"
            package_path.parent.mkdir(parents=True)
            package_path.write_text(json.dumps([{"Type": "Enum", "Name": "CommunityScreenLayoutMode"}]), encoding="utf-8")
            report = analyze_exports(
                export_dir,
                {"assets": [{"asset": "GameSystems/Enclave/CommunityScreenLayoutMode.uasset"}]},
                {"findings": [{"asset": "GameSystems/Enclave/CommunityScreenLayoutMode.uasset"}]},
            )

        self.assertEqual(report["scope"]["candidate_exports_matched"], 1)
        self.assertEqual(report["mission_summary"]["mission_asset_package_count"], 0)
        self.assertEqual(report["scope"]["mission_selection_assets_without_missionasset"], ["GameSystems/Enclave/CommunityScreenLayoutMode.uasset (no MissionAsset export)"])


if __name__ == "__main__":
    unittest.main()
