"""Self-contained tests for the dependency-free offline PE reader."""

import struct
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pe_static import PeImage


def make_test_pe() -> bytes:
    data = bytearray(0x600)
    data[:2] = b"MZ"
    struct.pack_into("<I", data, 0x3C, 0x80)
    data[0x80:0x84] = b"PE\0\0"
    coff = 0x84
    struct.pack_into("<HHIIIHH", data, coff, 0x8664, 2, 0, 0, 0, 0xF0, 0x0022)
    optional = coff + 20
    struct.pack_into("<H", data, optional, 0x20B)
    struct.pack_into("<Q", data, optional + 24, 0x140000000)
    struct.pack_into("<I", data, optional + 56, 0x3000)
    struct.pack_into("<I", data, optional + 108, 16)
    struct.pack_into("<II", data, optional + 112 + 3 * 8, 0x2000, 12)

    section_table = optional + 0xF0
    data[section_table : section_table + 8] = b".text\0\0\0"
    struct.pack_into("<IIII", data, section_table + 8, 0x100, 0x1000, 0x200, 0x200)
    struct.pack_into("<I", data, section_table + 36, 0x60000020)
    rdata = section_table + 40
    data[rdata : rdata + 8] = b".rdata\0\0"
    struct.pack_into("<IIII", data, rdata + 8, 0x200, 0x2000, 0x200, 0x400)
    struct.pack_into("<I", data, rdata + 36, 0x40000040)

    # One pdata record: [RVA 0x1000, RVA 0x1010).
    struct.pack_into("<III", data, 0x400, 0x1000, 0x1010, 0x2020)
    data[0x440 : 0x440 + 14] = b"ExampleNative\0"
    struct.pack_into("<QQ", data, 0x460, 0x140002040, 0x140001000)
    # A raw E8 rel32 reference at RVA 0x1020 to RVA 0x1000.
    data[0x220] = 0xE8
    struct.pack_into("<i", data, 0x221, 0x1000 - (0x1020 + 5))
    return bytes(data)


class PeImageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "fixture.exe"
        self.path.write_bytes(make_test_pe())
        self.image = PeImage(self.path)

    def tearDown(self):
        self.temp.cleanup()

    def test_rva_translation_and_pdata_range(self):
        self.assertEqual(self.image.rva_to_offset(0x1020), 0x220)
        self.assertEqual(self.image.va_to_offset(0x140002040), 0x440)
        self.assertEqual(self.image.function_containing(0x1005), (0x1000, 0x1010))
        self.assertIsNone(self.image.function_containing(0x1010))

    def test_native_pair_scan_and_relative_reference_triage(self):
        pairs = list(self.image.iter_native_pairs())
        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0]["name"], "ExampleNative")
        self.assertEqual(pairs[0]["func_rva"], "0x1000")
        self.assertEqual(self.image.direct_relative_refs({0x1000})[0x1000], [0x1020])

    def test_rejects_non_pe_input(self):
        self.path.write_bytes(b"not an executable")
        with self.assertRaises(ValueError):
            PeImage(self.path)


if __name__ == "__main__":
    unittest.main()
