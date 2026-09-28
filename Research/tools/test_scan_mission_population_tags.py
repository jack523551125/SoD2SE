"""Tests for the focused primitive mission-tag reader."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scan_mission_population_tags import associate_member_conditions


class MissionPopulationTagTests(unittest.TestCase):
    def test_pairs_nearby_community_member_stat_comparison_and_value(self):
        tags = [
            {"offset": "0x10", "name": "ComparisonStat", "type": "ByteProperty", "value": "ECommunityConditionStat::CommunityMembers"},
            {"offset": "0x20", "name": "Comparison", "type": "ByteProperty", "value": "EMissionConditionComparison::LessOrEqual"},
            {"offset": "0x30", "name": "Value", "type": "FloatProperty", "value": 11.0},
        ]
        self.assertEqual(
            associate_member_conditions(tags),
            [
                {
                    "offset": "0x10",
                    "stat": "ECommunityConditionStat::CommunityMembers",
                    "comparison": "EMissionConditionComparison::LessOrEqual",
                    "value": 11.0,
                    "complete_nearby_tag_sequence": True,
                }
            ],
        )

    def test_marks_unpaired_sequences_instead_of_guessing(self):
        tags = [
            {"offset": "0x10", "name": "ComparisonStat", "type": "ByteProperty", "value": "ECommunityConditionStat::CommunityMembers"},
            {"offset": "0x20", "name": "Comparison", "type": "ByteProperty", "value": "EMissionConditionComparison::Greater"},
            {"offset": "0x30", "name": "Other", "type": "BoolProperty", "value": True},
        ]
        result = associate_member_conditions(tags)
        self.assertEqual(len(result), 1)
        self.assertIsNone(result[0]["value"])
        self.assertFalse(result[0]["complete_nearby_tag_sequence"])


if __name__ == "__main__":
    unittest.main()
