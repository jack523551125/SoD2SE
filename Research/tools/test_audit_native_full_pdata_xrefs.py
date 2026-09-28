import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from audit_native_full_pdata_xrefs import audit_report, scan_raw_relative_sites


class FakeSection:
    name = ".text"
    virtual_address = 0x1000
    raw_offset = 0
    raw_size = 11
    is_executable = True


class FakeImage:
    image_base = 0
    sections = (FakeSection(),)
    function_ranges = ((0x1000, 0x100B),)
    data = bytes.fromhex("E8 FB 00 00 00 E9 F6 00 00 00 90")

    def __init__(self, path):
        self.path = path

    def section_for_rva(self, rva):
        return FakeSection() if 0x1000 <= rva < 0x100B else None

    def function_containing(self, rva):
        return (0x1000, 0x100B) if 0x1000 <= rva < 0x100B else None


class AuditNativeFullPdataXrefsTests(unittest.TestCase):
    def test_scans_raw_call_and_jump_candidates_by_opcode(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "fake.exe"
            path.write_bytes(FakeImage.data)
            found = scan_raw_relative_sites(FakeImage(path), {0x1100})

        self.assertEqual(found[0xE8][0x1100], {0x1000})
        self.assertEqual(found[0xE9][0x1100], {0x1005})

    def test_crosschecks_decoded_sites_and_marks_unmatched_jump_in_partial_body(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "fake.exe"
            path.write_bytes(FakeImage.data)
            image = FakeImage(path)
            decoded = {
                "targets": [{
                    "target_rva": "0x1100",
                    "direct_call_count": 1,
                    "direct_callers": [{"site_rva": "0x1000"}],
                    "tail_jump_count": 0,
                    "tail_jump_callers": [],
                }],
                "partially_decoded_function_bodies": [{
                    "start_rva": "0x1000", "end_exclusive": "0x100B"
                }],
            }
            report = audit_report(image, decoded)

        self.assertTrue(report["scope"]["all_e8_candidates_match_decoded_calls"])
        self.assertEqual(report["scope"]["unmatched_raw_e9_site_count"], 1)
        self.assertEqual(report["scope"]["unmatched_raw_e9_inside_partial_body_count"], 1)


if __name__ == "__main__":
    unittest.main()
