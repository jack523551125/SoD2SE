"""Unit tests for the read-only gameplay-asset PAK scanner."""

import io
import re
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scan_gameplay_pak_assets import (
    asset_path_selected,
    asset_strings,
    is_name_like,
    lz4_block_decompress,
    path_is_selected,
)


class GameplayPakScannerTests(unittest.TestCase):
    def test_lz4_literal_only_block(self):
        self.assertEqual(lz4_block_decompress(b"\x30abc"), b"abc")

    def test_lz4_overlapping_back_reference(self):
        self.assertEqual(lz4_block_decompress(b"\x32abc\x03\x00"), b"abcabcabc")

    def test_lz4_rejects_invalid_back_reference(self):
        with self.assertRaisesRegex(ValueError, "invalid LZ4 match offset"):
            lz4_block_decompress(b"\x00\x01\x00")

    def test_asset_strings_reads_ascii_and_ascii_range_utf16le(self):
        payload = b"CanAddCharacter\x00" + "CommunityScreenManager".encode("utf-16le")
        self.assertEqual(
            set(asset_strings(payload)),
            {"CanAddCharacter", "CommunityScreenManager"},
        )

    def test_name_filter_excludes_prose(self):
        self.assertTrue(is_name_like("DisabledCommunityAtCap"))
        self.assertTrue(is_name_like("Maximum Survivors"))
        self.assertFalse(is_name_like("The community is already too large"))
        self.assertFalse(is_name_like("name;malformed"))

    def test_path_filter_accepts_roots_and_exact_assets(self):
        self.assertTrue(path_is_selected("LegacyArcs\\Arc_Legacy_Builder.uasset", ("LegacyArcs",)))
        self.assertTrue(path_is_selected("MissionSettings.uasset", ("MissionSettings",)))
        self.assertTrue(path_is_selected("EnclaveMissions\\Recruit.uasset", ("EnclaveMissions",)))
        self.assertFalse(path_is_selected("Art\\LegacyArcsIcon.uasset", ("LegacyArcs",)))
        self.assertTrue(asset_path_selected("External\\RecruitMission.uasset", (), re.compile("recruit", re.I)))
        self.assertFalse(asset_path_selected("External\\Other.uasset", (), re.compile("recruit", re.I)))

    def test_uncompressed_record_extraction(self):
        from scan_gameplay_pak_assets import extract_record

        stream = io.BytesIO(b"headerpayload")
        record = SimpleNamespace(
            encrypted=False,
            compression_method=0,
            data_offset=6,
            uncompressed_size=7,
        )
        self.assertEqual(extract_record(stream, record), b"payload")


if __name__ == "__main__":
    unittest.main()
