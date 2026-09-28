import json
import tempfile
import unittest
from pathlib import Path

from analyze_roguelite_experience_reward_table import build_report


class ExperienceRewardTableTests(unittest.TestCase):
    def test_matches_call_tag_and_preserves_per_skill_xp(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            table_path = root / "StateOfDecay2" / "Content" / "GameSystems" / "Skills" / "ExperienceRewards.json"
            table_path.parent.mkdir(parents=True)
            table_path.write_text(json.dumps([{
                "Type": "DataTable",
                "Name": "ExperienceRewards",
                "Properties": {"RowStruct": {"ObjectName": "ScriptStruct'ExperienceReward'"}},
                "Rows": {
                    "Wits_StealthKills": {
                        "Skills": [{
                            "Experience": 50.0,
                            "AwardTo": {"ObjectName": "CharacterSkillDefinition'StealthDefinition'"},
                        }],
                    },
                },
            }]), encoding="utf-8")
            call_context_path = root / "call-contexts.json"
            call_context_path.write_text(json.dumps({
                "target": "target.json",
                "target_sha256": "A" * 64,
                "scope": {"game_process_started_or_attached": False},
                "call_sites": [{
                    "asset_path": "StateOfDecay2/Content/TestAsset.uasset",
                    "blueprint_function": "AwardTestExperience",
                    "target": "Function'CharacterBlueprintHelpers:AuthAwardExperience'",
                    "parameters": [
                        {"inst": "EX_LocalVariable", "variable": "Attacker"},
                        {"inst": "EX_NameConst", "value": "Wits_StealthKills"},
                    ],
                    "related_local_assignments": [],
                }],
            }), encoding="utf-8")

            report = build_report(root, call_context_path)

        self.assertEqual(report["scope"]["reward_table_row_count"], 1)
        self.assertEqual(report["scope"]["matched_call_tag_count"], 1)
        self.assertEqual(report["scope"]["unmatched_call_tag_candidates"], [])
        row = report["referenced_call_tags"]["Wits_StealthKills"]
        self.assertEqual(row["table_skill_rewards"], [{
            "skill_definition": "CharacterSkillDefinition'StealthDefinition'",
            "experience": 50.0,
        }])


if __name__ == "__main__":
    unittest.main()
