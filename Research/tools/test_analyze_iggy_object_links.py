from __future__ import annotations

import struct
import unittest

from analyze_iggy_object_links import scan_relative_object_targets


class IggyObjectLinkTests(unittest.TestCase):
    def test_keeps_aligned_relative_object_target_and_counts_misaligned_control(self) -> None:
        block_start = 96
        block = bytearray([0x7F] * 32)
        # At +8, field-relative -104 lands exactly on object start 0.
        struct.pack_into("<i", block, 8, -104)
        # At +12, field-relative +12 lands on object start 120, but the field
        # itself is not 8-byte aligned and therefore remains a control hit.
        struct.pack_into("<i", block, 12, 12)
        source = {"object_index": 7, "movie_offset": 800, "kind": 3}
        records = {
            0: {"object_index": 0, "movie_offset": 0, "kind": 6},
            120: {"object_index": 1, "movie_offset": 120, "kind": 4},
        }

        edges, unaligned = scan_relative_object_targets(
            bytes(block),
            block_start_movie_offset=block_start,
            source_record=source,
            block_role="kind3_dual_pointer_span",
            records_by_offset=records,
        )

        self.assertEqual(len(edges), 1)
        self.assertEqual(edges[0]["field_offset_from_block"], 8)
        self.assertEqual(edges[0]["relative_i32"], -104)
        self.assertEqual(edges[0]["target_movie_offset"], 0)
        self.assertEqual(edges[0]["target_kind"], 6)
        self.assertEqual(dict(unaligned), {4: 1})


if __name__ == "__main__":
    unittest.main()
