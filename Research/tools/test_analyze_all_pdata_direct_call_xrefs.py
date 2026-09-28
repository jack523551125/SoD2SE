import sys
import unittest
from pathlib import Path

try:
    import capstone
except ImportError:  # pragma: no cover - optional dependency message is tested by CLI users
    capstone = None

sys.path.insert(0, str(Path(__file__).resolve().parent))
from analyze_all_pdata_direct_call_xrefs import analyze_all_pdata_direct_call_xrefs


class FakeSection:
    is_executable = True


class FakeImage:
    image_base = 0
    data = bytes.fromhex("E8 FB 00 00 00 C3")
    function_ranges = ((0x1000, 0x1006),)
    path = Path("synthetic.exe")

    def section_for_rva(self, rva, length=1):
        return FakeSection() if 0x1000 <= rva and rva + length <= 0x1006 or rva == 0x1100 else None

    def rva_to_offset(self, rva, length):
        return rva - 0x1000

    def iter_native_pairs(self):
        return iter([{"func_rva": "0x1000", "name": "SyntheticCaller"}])


@unittest.skipIf(capstone is None, "Capstone is an optional development dependency")
class AnalyzeAllPdataDirectCallXrefsTests(unittest.TestCase):
    def test_decodes_direct_calls_for_every_function_range(self):
        report = analyze_all_pdata_direct_call_xrefs(
            FakeImage(),
            {0x1100: {"target_kinds": ["internal-callee"], "source_native_functions": ["Target"]}},
            capstone,
        )

        target = report["targets"][0]
        self.assertEqual(report["scope"]["decoded_function_bodies"], 1)
        self.assertEqual(report["scope"]["direct_call_edges"], 1)
        self.assertEqual(target["direct_call_count"], 1)
        self.assertEqual(target["direct_callers"][0]["site_rva"], "0x1000")
        self.assertEqual(target["direct_callers"][0]["registered_names_at_caller"], ["SyntheticCaller"])

    def test_rejects_empty_target_set(self):
        if capstone is None:
            self.skipTest("Capstone is an optional development dependency")
        with self.assertRaisesRegex(ValueError, "at least one xref target"):
            analyze_all_pdata_direct_call_xrefs(FakeImage(), {}, capstone)


if __name__ == "__main__":
    unittest.main()
