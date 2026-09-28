import unittest

from probe_native_settings_asset import patch_equal_length, structural_differences


class NativeSettingsAssetProbeTests(unittest.TestCase):
    def test_fixed_length_patch_changes_only_source_bytes(self):
        original = b"prefix\0Aim Assist\0suffix"
        patched, offsets = patch_equal_length(original)
        self.assertEqual(len(patched), len(original))
        self.assertEqual(patched, b"prefix\0Mod Config\0suffix")
        self.assertEqual(offsets, [7, 8, 9, 11, 12, 13, 14, 15, 16])

    def test_ambiguous_or_size_changing_patch_fails_closed(self):
        with self.assertRaises(ValueError):
            patch_equal_length(b"Aim Assist\0Aim Assist\0")
        with self.assertRaises(ValueError):
            patch_equal_length(b"Aim Assist\0", b"Aim Assist\0", b"Longer Text\0")

    def test_structural_diff_catches_nontext_changes(self):
        before = [{"Properties": {"TextTable": [{"Text": "Aim Assist"}], "ApiFunctions": ["ApiInit"]}}]
        after = [{"Properties": {"TextTable": [{"Text": "Mod Config"}], "ApiFunctions": ["ApiInit"]}}]
        self.assertEqual(structural_differences(before, after), ["/0/Properties/TextTable/0/Text"])
        after[0]["Properties"]["ApiFunctions"].append("Other")
        self.assertIn("/0/Properties/ApiFunctions/length", structural_differences(before, after))


if __name__ == "__main__":
    unittest.main()
