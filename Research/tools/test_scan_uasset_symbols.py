"""Tests for offline, caller-supplied cooked-asset string scanning."""

import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scan_uasset_symbols import expand_assets, scan


class UassetScannerTests(unittest.TestCase):
    def test_recursively_expands_directories_and_reads_ascii_and_utf16(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            nested = root / "nested"
            nested.mkdir()
            asset = nested / "CharacterUI_BP.uasset"
            asset.write_bytes(b"/Script/IggyPlugin\0" + "CommonUIMoviePlayer".encode("utf-16le"))

            assets, missing = expand_assets([root])

            self.assertEqual(missing, [])
            self.assertEqual(assets, [asset])
            symbols = scan(asset, re.compile(r"(?i)(Iggy|CommonUIMoviePlayer)"), 4)
            self.assertEqual(symbols, ["/Script/IggyPlugin", "CommonUIMoviePlayer"])

    def test_reports_missing_inputs_without_hiding_valid_assets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            asset = root / "one.uasset"
            asset.write_bytes(b"Text\0")
            assets, missing = expand_assets([asset, root / "missing"])
            self.assertEqual(assets, [asset])
            self.assertEqual(missing, [root / "missing"])


if __name__ == "__main__":
    unittest.main()
