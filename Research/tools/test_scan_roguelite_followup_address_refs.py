import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scan_roguelite_followup_address_refs import scan_data_pointer_patterns


class Section:
    name = ".rdata"
    virtual_address = 0x4000
    raw_offset = 0
    is_executable = False

    def __init__(self, raw_size):
        self.raw_size = raw_size


class FakeImage:
    image_base = 0x140000000

    def __init__(self, data):
        self.data = data
        self.sections = (Section(len(data)),)

    @staticmethod
    def is_executable_va(_va):
        return True


class ScanRogueliteFollowupAddressRefsTests(unittest.TestCase):
    def test_finds_unaligned_va_qword_and_rva_dword_candidates(self):
        target = 0x1234
        data = b"\x91" + struct.pack("<Q", 0x140000000 + target) + b"\x92" + struct.pack("<I", target)
        result = scan_data_pointer_patterns(FakeImage(data), {target})[target]

        self.assertEqual(result["absolute_va_qword_candidates"][0]["site_rva"], "0x4001")
        self.assertEqual(result["rva_dword_candidates"][0]["site_rva"], "0x400a")


if __name__ == "__main__":
    unittest.main()
