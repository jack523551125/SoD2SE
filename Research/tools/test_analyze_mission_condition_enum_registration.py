import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from analyze_mission_condition_enum_registration import ordered_pointer_group_candidate


class MissionConditionEnumPointerEvidenceTests(unittest.TestCase):
    def test_candidate_order_comes_from_contiguous_pointer_slots(self):
        result = ordered_pointer_group_candidate(
            "EMissionConditionComparison",
            ["Equal", "Greater", "Less"],
            {
                "EMissionConditionComparison::Equal": [{"section": ".rdata", "slot_rva": "0x1000"}],
                "EMissionConditionComparison::Greater": [{"section": ".rdata", "slot_rva": "0x1008"}],
                "EMissionConditionComparison::Less": [{"section": ".rdata", "slot_rva": "0x1010"}],
            },
        )

        self.assertTrue(result["complete"])
        self.assertEqual([row["name"].split("::")[1] for row in result["entries"]], ["Equal", "Greater", "Less"])

    def test_missing_or_noncontiguous_names_do_not_produce_order_evidence(self):
        missing = ordered_pointer_group_candidate(
            "EComparison", ["Equal", "Less"], {"EComparison::Equal": [{"section": ".rdata", "slot_rva": "0x1000"}]}
        )
        spaced = ordered_pointer_group_candidate(
            "EComparison", ["Equal", "Less"], {
                "EComparison::Equal": [{"section": ".rdata", "slot_rva": "0x1000"}],
                "EComparison::Less": [{"section": ".rdata", "slot_rva": "0x1010"}],
            }
        )

        self.assertFalse(missing["complete"])
        self.assertFalse(spaced["complete"])


if __name__ == "__main__":
    unittest.main()
