import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
from analyze_community_mission_condition_native_name_xrefs import find_utf16le_string_rvas


class Utf16NameReferenceTests(unittest.TestCase):
    def test_finds_utf16le_occurrences_without_confusing_ascii_or_offsets(self):
        first = "UCommunityMissionCondition".encode("utf-16le") + bytes((0, 0))
        second = "CommunityMissionCondition".encode("utf-16le") + bytes((0, 0))
        data = b"prefix!" + first + b"gap!" + second
        image = SimpleNamespace(
            data=data,
            sections=(SimpleNamespace(name=".rdata", raw_offset=0, virtual_address=0x1000, raw_size=len(data)),),
        )

        result = find_utf16le_string_rvas(image, ["UCommunityMissionCondition", "CommunityMissionCondition"])

        self.assertEqual(result["UCommunityMissionCondition"], [0x1000 + len(b"prefix!")])
        self.assertEqual(result["CommunityMissionCondition"], [
            0x1000 + len(b"prefix!") + 2,
            0x1000 + len(b"prefix!") + len(first) + len(b"gap!"),
        ])


if __name__ == "__main__":
    unittest.main()
