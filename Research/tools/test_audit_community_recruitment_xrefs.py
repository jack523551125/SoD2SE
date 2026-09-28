"""Tests for bounded direct recruitment call/jump confirmation."""

import struct
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from audit_community_recruitment_xrefs import audit
from pe_static import PeImage
from test_pe_static import make_test_pe

try:
    import capstone
except ImportError:
    capstone = None


@unittest.skipIf(capstone is None, "Capstone is required for instruction boundary tests")
class RecruitmentXrefAuditTests(unittest.TestCase):
    def test_confirms_call_and_tail_jump_only_from_pdata_bodies(self):
        data = bytearray(make_test_pe())
        # Add a second function [0x1010, 0x1030) with one call and one tail jump
        # to 0x1000, then fill the rest with single-byte INT3 instructions.
        struct.pack_into("<I", data, 0x124, 24)
        struct.pack_into("<III", data, 0x40C, 0x1010, 0x1030, 0x2020)
        data[0x210] = 0xE8
        struct.pack_into("<i", data, 0x211, 0x1000 - (0x1010 + 5))
        data[0x215] = 0xE9
        struct.pack_into("<i", data, 0x216, 0x1000 - (0x1015 + 5))
        data[0x21A:0x230] = b"\xCC" * 0x16

        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "fixture.exe"
            path.write_bytes(data)
            report = audit(PeImage(path), capstone, [{"id": "fixture", "name": "target", "rva": 0x1000}])

        edge = report["targets"][0]
        self.assertEqual(edge["raw_e8_candidate_count"], 1)
        self.assertEqual(edge["verified_direct_call_count"], 1)
        self.assertEqual(edge["verified_direct_callers"][0]["caller_range_rva"],
                         {"start": "0x1010", "end_exclusive": "0x1030"})
        self.assertEqual(edge["raw_e9_candidate_count"], 1)
        self.assertEqual(edge["verified_tail_jump_count"], 1)


if __name__ == "__main__":
    unittest.main()
