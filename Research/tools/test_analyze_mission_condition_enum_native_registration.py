import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from analyze_mission_condition_enum_native_registration import chained_ranges_for_root


class ChainedUnwindRangeTests(unittest.TestCase):
    def test_follows_nested_and_sibling_chaininfo_ranges(self):
        root = {"begin_rva": 0x1000, "end_exclusive_rva": 0x1010, "unwind_info_rva": 0x5000,
                "unwind_flags": 0, "unwind_code_count": 1, "chained_parent": None}
        nested = {"begin_rva": 0x1020, "end_exclusive_rva": 0x1030, "unwind_info_rva": 0x5010,
                  "unwind_flags": 4, "unwind_code_count": 0,
                  "chained_parent": {"begin_rva": 0x1000, "end_exclusive_rva": 0x1010, "unwind_info_rva": 0x5000}}
        child = {"begin_rva": 0x1040, "end_exclusive_rva": 0x1050, "unwind_info_rva": 0x5020,
                 "unwind_flags": 4, "unwind_code_count": 0,
                 "chained_parent": {"begin_rva": 0x1020, "end_exclusive_rva": 0x1030, "unwind_info_rva": 0x5010}}
        sibling = {"begin_rva": 0x1060, "end_exclusive_rva": 0x1070, "unwind_info_rva": 0x5030,
                   "unwind_flags": 4, "unwind_code_count": 0,
                   "chained_parent": {"begin_rva": 0x1020, "end_exclusive_rva": 0x1030, "unwind_info_rva": 0x5010}}
        unrelated = {"begin_rva": 0x1080, "end_exclusive_rva": 0x1090, "unwind_info_rva": 0x5040,
                     "unwind_flags": 0, "unwind_code_count": 0, "chained_parent": None}

        result = chained_ranges_for_root([sibling, child, unrelated, nested, root], 0x1000)

        self.assertEqual([row["begin_rva"] for row in result], [0x1000, 0x1020, 0x1040, 0x1060])

    def test_missing_or_ambiguous_root_is_rejected(self):
        with self.assertRaises(ValueError):
            chained_ranges_for_root([], 0x1000)
        duplicate = {"begin_rva": 0x1000, "end_exclusive_rva": 0x1010, "unwind_info_rva": 0x5000,
                     "unwind_flags": 0, "unwind_code_count": 0, "chained_parent": None}
        with self.assertRaises(ValueError):
            chained_ranges_for_root([duplicate, duplicate], 0x1000)


if __name__ == "__main__":
    unittest.main()
