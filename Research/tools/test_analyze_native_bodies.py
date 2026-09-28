"""Tests for address joining and decoded-call evidence normalization."""

import struct
import importlib.util
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from analyze_native_bodies import (
    analyze_direct_call_xrefs,
    analyze_target,
    collect_targets,
    is_xref_focus_record,
)
from pe_static import PeImage
from test_pe_static import make_test_pe


class TargetCollectionTests(unittest.TestCase):
    def test_xref_focus_includes_reward_and_stable_identity_candidates(self):
        focus = {
            "function_ids": ["roguelite-progression.award-experience", "unlimited-community.can-add-character-native"],
            "function_id_prefixes": ["roguelite-kill."],
        }
        self.assertTrue(is_xref_focus_record({"function_ids": ["roguelite-progression.award-experience"]}, focus))
        self.assertTrue(is_xref_focus_record({"function_ids": ["roguelite-identity.get-survivor-by-id"]}, {**focus, "function_ids": ["roguelite-identity.get-survivor-by-id"]}))
        self.assertTrue(is_xref_focus_record({"function_ids": ["roguelite-kill.on-zombie-killed"]}, focus))
        self.assertTrue(is_xref_focus_record({"function_ids": ["unlimited-community.can-add-character-native"]}, focus))
        self.assertFalse(is_xref_focus_record({"function_ids": ["roguelite-progression.get-current-level"]}, focus))

    def test_curated_function_and_domain_candidate_join_same_registration(self):
        pairs = [
            {"name": "ExampleNative", "func_rva": "0x1000", "pair_rva": "0x2000"},
            {"name": "ExampleNative", "func_rva": "0x1010", "pair_rva": "0x2010"},
        ]
        functions = {
            "functions": [
                {
                    "id": "existing.example",
                    "kind": "native-ufunction",
                    "symbol": "ExampleNative",
                    "rva": "0x1000",
                    "registration_rva": "0x2000",
                }
            ]
        }
        domains = {"domains": [{"id": "candidate-domain", "native_candidates": ["ExampleNative"]}]}

        targets, _names, missing_functions, missing_candidates = collect_targets(functions, domains, pairs)

        self.assertEqual(len(targets), 2)
        first = next(row for row in targets if row["function_rva"] == 0x1000)
        self.assertEqual(first["function_ids"], ["existing.example"])
        self.assertEqual(first["domain_ids"], ["candidate-domain"])
        self.assertEqual(missing_functions, [])
        self.assertEqual(missing_candidates, [])

    def test_unresolved_candidate_is_reported_without_inventing_an_address(self):
        targets, _names, missing_functions, missing_candidates = collect_targets(
            {"functions": []},
            {"domains": [{"id": "absent-domain", "native_candidates": ["NoSuchSymbol"]}]},
            [],
        )
        self.assertEqual(targets, [])
        self.assertEqual(missing_functions, [])
        self.assertEqual(missing_candidates, [{"domain_id": "absent-domain", "native_name": "NoSuchSymbol"}])


@unittest.skipUnless(importlib.util.find_spec("capstone"), "optional Capstone package is not installed")
class DecodedBodyTests(unittest.TestCase):
    def test_direct_call_xref_requires_a_capstone_confirmed_pdata_caller(self):
        import capstone

        data = bytearray(make_test_pe())
        # Add the call-site body to .pdata: [0x1020, 0x1026) contains E8 rel32; RET.
        optional = 0x98
        struct.pack_into("<II", data, optional + 112 + 3 * 8, 0x2000, 24)
        struct.pack_into("<III", data, 0x40C, 0x1020, 0x1026, 0x2020)
        data[0x225] = 0xC3
        path = Path(__file__).resolve().parent / "_native_body_fixture.exe"
        path.write_bytes(data)
        try:
            image = PeImage(path)
            md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
            md.detail = True
            result = analyze_direct_call_xrefs(
                image,
                md,
                [
                    {
                        "native_name": "ExampleNative",
                        "function_rva": "0x1000",
                        "function_ids": ["roguelite-kill.example"],
                        "direct_calls": [],
                    }
                ],
                {0x1000: {"ExampleNative"}},
                {"function_ids": [], "function_id_prefixes": ["roguelite-kill."]},
                capstone.CS_GRP_CALL,
                capstone.CS_OP_IMM,
            )
            target = next(row for row in result["targets"] if row["target_rva"] == "0x1000")
            self.assertEqual(target["raw_e8_candidate_count"], 1)
            self.assertEqual(len(target["verified_direct_callers"]), 1)
            self.assertEqual(target["verified_direct_callers"][0]["site_rva"], "0x1020")
            self.assertTrue(target["direct_e8_search_complete"])
            self.assertEqual(result["statistics"]["verified_direct_call_edges_observed"], 1)
        finally:
            path.unlink(missing_ok=True)

    def test_call_xref_without_pdata_is_not_promoted_from_raw_e8_bytes(self):
        import capstone

        path = Path(__file__).resolve().parent / "_native_body_fixture.exe"
        path.write_bytes(make_test_pe())
        try:
            image = PeImage(path)
            md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
            md.detail = True
            result = analyze_direct_call_xrefs(
                image,
                md,
                [
                    {
                        "native_name": "ExampleNative",
                        "function_rva": "0x1000",
                        "function_ids": ["roguelite-kill.example"],
                        "direct_calls": [],
                    }
                ],
                {0x1000: {"ExampleNative"}},
                {"function_ids": [], "function_id_prefixes": ["roguelite-kill."]},
                capstone.CS_GRP_CALL,
                capstone.CS_OP_IMM,
            )
            target = next(row for row in result["targets"] if row["target_rva"] == "0x1000")
            self.assertEqual(target["raw_e8_candidate_count"], 1)
            self.assertEqual(target["verified_direct_callers"], [])
            self.assertEqual(target["candidates_without_unwind_range"], 1)
            self.assertFalse(target["direct_e8_search_complete"])
            self.assertEqual(result["statistics"]["verified_direct_call_edges_observed"], 0)
        finally:
            path.unlink(missing_ok=True)

    def test_executable_entry_without_pdata_is_distinguished_and_skipped(self):
        path = Path(__file__).resolve().parent / "_native_body_fixture.exe"
        path.write_bytes(make_test_pe())
        try:
            image = PeImage(path)
            row = analyze_target(
                image,
                None,
                {
                    "native_name": "LeafNative",
                    "function_rva": 0x1020,
                    "registration_rva": 0x2040,
                    "function_ids": [],
                    "domain_ids": [],
                },
                {},
                0,
                0,
            )
            self.assertEqual(row["status"], "executable-rva-without-unwind-range")
            self.assertEqual(row["executable_section"], ".text")
            self.assertEqual(row["direct_calls"], [])
        finally:
            path.unlink(missing_ok=True)

    def test_decodes_a_direct_call_only_at_a_real_instruction_boundary(self):
        import capstone

        data = bytearray(make_test_pe())
        # .text starts at file offset 0x200 and the .pdata range begins at RVA 0x1000.
        data[0x200] = 0xE8
        struct.pack_into("<i", data, 0x201, 0x1020 - (0x1000 + 5))
        data[0x205] = 0xC3
        path = Path(__file__).resolve().parent / "_native_body_fixture.exe"
        path.write_bytes(data)
        try:
            image = PeImage(path)
            md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
            md.detail = True
            row = analyze_target(
                image,
                md,
                {
                    "native_name": "ExampleNative",
                    "function_rva": 0x1000,
                    "registration_rva": 0x2040,
                    "function_ids": [],
                    "domain_ids": [],
                },
                {},
                capstone.CS_GRP_CALL,
                capstone.CS_OP_IMM,
            )
            self.assertEqual(row["status"], "decoded")
            self.assertTrue(row["is_function_entry"])
            self.assertEqual(row["direct_calls"][0]["target_rva"], "0x1020")
            self.assertEqual(row["direct_calls"][0]["target_in_image"], True)
        finally:
            path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
