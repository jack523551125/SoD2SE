from __future__ import annotations

import unittest

from analyze_iggy_runtime_api import trace_x64_cfg


class IggyRuntimeApiTests(unittest.TestCase):
    def test_cfg_walk_follows_both_conditional_paths_and_stops_at_returns(self) -> None:
        # jnz +2; nop; ret; xor eax,eax; ret
        code = bytes.fromhex("75 02 90 C3 31 C0 C3")
        base = 0x1000
        result = trace_x64_cfg(
            base,
            read_code=lambda address, length: code[address - base : address - base + length],
            is_executable=lambda address: base <= address < base + len(code),
        )

        self.assertEqual(result["instruction_count"], 5)
        self.assertEqual(result["basic_block_count"], 2)
        self.assertEqual(result["direct_calls"], [])
        self.assertEqual(
            result["branches"],
            [
                {
                    "site_rva": base,
                    "target_rva": base + 4,
                    "mnemonic": "jne",
                    "unconditional": False,
                }
            ],
        )


if __name__ == "__main__":
    unittest.main()
