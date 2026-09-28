import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from analyze_community_mission_condition_native_layout import parse_r9d_offset_assignment


class PropertyOffsetExpressionTests(unittest.TestCase):
    def test_mov_immediate_is_an_offset(self):
        self.assertEqual(parse_r9d_offset_assignment("mov", "r9d, 0x28"), 0x28)

    def test_lea_offset_requires_proven_zero_base(self):
        self.assertEqual(
            parse_r9d_offset_assignment("lea", "r9d, [rdi + 0x30]", {"rdi"}),
            0x30,
        )
        with self.assertRaises(ValueError):
            parse_r9d_offset_assignment("lea", "r9d, [rdi + 0x30]")

    def test_unknown_offset_expression_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_r9d_offset_assignment("lea", "r9d, [rbx + 0x30]", {"rdi"})


if __name__ == "__main__":
    unittest.main()
