import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from analyze_full_cooked_blueprint_calls import analyze_export_directory


class AnalyzeFullCookedBlueprintCallsTests(unittest.TestCase):
    def test_counts_serialized_capacity_call_and_marks_warned_asset(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            asset = root / "StateOfDecay2" / "Content" / "UI" / "CommunityPanel.json"
            asset.parent.mkdir(parents=True)
            asset.write_text(json.dumps([
                {
                    "Type": "Function",
                    "Name": "UpdatePanel",
                    "ScriptBytecode": [
                        {
                            "Inst": "EX_FinalFunction",
                            "Function": {
                                "ObjectName": "Function'Enclave:CanAddCharacter'",
                                "ObjectPath": "/Script/DaytonGame",
                            },
                        },
                        {
                            "Inst": "EX_VirtualFunction",
                            "Function": {"ObjectName": "SomeOtherFunction"},
                        },
                    ],
                }
            ]), encoding="utf-8-sig")

            report = analyze_export_directory(
                root,
                ["stateofdecay2/content/ui/communitypanel.uasset"],
            )

        self.assertEqual(report["scope"]["json_files_seen"], 1)
        self.assertEqual(report["scope"]["json_decode_error_count"], 0)
        self.assertEqual(report["scope"]["filtered_call_reference_count"], 1)
        self.assertEqual(report["scope"]["call_references_in_exporter_warning_assets"], 1)
        self.assertEqual(report["capacity_native_wrapper_reference_counts"]["CanAddCharacter"], 1)
        self.assertEqual(report["capacity_native_wrapper_reference_counts"]["CanAddCharacters"], 0)
        self.assertTrue(report["call_references"][0]["asset_has_export_warning"])

    def test_reports_invalid_json_without_stopping_other_exports(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "broken.json").write_text("{", encoding="utf-8")
            report = analyze_export_directory(root)

        self.assertEqual(report["scope"]["json_files_seen"], 1)
        self.assertEqual(report["scope"]["json_decode_error_count"], 1)
        self.assertEqual(report["scope"]["filtered_call_reference_count"], 0)

    def test_supports_custom_target_filter_for_experience_and_event_research(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            asset = root / "Game" / "Example.json"
            asset.parent.mkdir(parents=True)
            asset.write_text(json.dumps([
                {
                    "Type": "Function",
                    "Name": "AwardOnDeath",
                    "ScriptBytecode": [
                        {
                            "Inst": "EX_FinalFunction",
                            "Function": {"ObjectName": "Function'Experience:AwardExperience'"},
                        }
                    ],
                }
            ]), encoding="utf-8-sig")

            report = analyze_export_directory(root, target_pattern=re.compile(r"(?i)AwardExperience"))

        self.assertEqual(report["scope"]["filtered_call_reference_count"], 1)
        self.assertEqual(report["scope"]["filtered_call_target_count"], 1)
        self.assertEqual(report["target_filter"], r"(?i)AwardExperience")


if __name__ == "__main__":
    unittest.main()
