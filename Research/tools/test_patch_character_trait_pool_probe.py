from __future__ import annotations

import unittest

from patch_character_trait_pool_probe import find_unique


class CharacterTraitPoolProbeTests(unittest.TestCase):
    def test_finds_a_single_guarded_sequence(self) -> None:
        data = b"prefix" + bytes.fromhex("24 04 74 d7") + b"suffix"
        self.assertEqual(find_unique(data, bytes.fromhex("24 04 74 d7")), 6)

    def test_rejects_absent_or_ambiguous_sequence(self) -> None:
        pattern = bytes.fromhex("24 04 74 d7")
        with self.assertRaisesRegex(ValueError, "exactly one"):
            find_unique(b"no matching instructions", pattern)
        with self.assertRaisesRegex(ValueError, "exactly one"):
            find_unique(pattern + b"x" + pattern, pattern)

    def test_rejects_empty_sequence(self) -> None:
        with self.assertRaisesRegex(ValueError, "cannot be empty"):
            find_unique(b"anything", b"")


if __name__ == "__main__":
    unittest.main()
