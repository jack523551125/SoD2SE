from __future__ import annotations

import struct
import unittest
import zlib

from inspect_iggy_movie import (
    IGGY_MAGIC,
    IggyFormatError,
    _classify_kind4_payload,
    _classify_relative_field_target,
    _summarize_index_stream_relationship,
    _summarize_index_subfile,
    inspect_iggy,
)


def make_iggy(
    *,
    object_kinds: tuple[int, ...] = (6,),
    additional_object_kinds: tuple[int, ...] = (),
    imported_guid: int = 0,
    text: str = "Settings",
    include_type3_candidate_index: bool = False,
    include_type1_candidate_index: bool = False,
    kind1_tail: bytes = b"tail",
    kind3_span: bytes = b"",
) -> bytes:
    if additional_object_kinds and imported_guid == 0:
        raise ValueError("additional objects require a nonzero imported GUID field")
    if include_type3_candidate_index and (
        not object_kinds or any(kind != 3 for kind in object_kinds + additional_object_kinds)
    ):
        raise ValueError("the type-3 candidate index fixture requires only kind-3 objects")
    if include_type3_candidate_index and additional_object_kinds:
        raise ValueError("the type-3 candidate index fixture does not use an additional table")
    if include_type1_candidate_index and (object_kinds + additional_object_kinds) != (1,):
        raise ValueError("the type-1 candidate index fixture requires exactly one kind-1 object")
    if include_type1_candidate_index and additional_object_kinds:
        raise ValueError("the type-1 candidate index fixture does not use an additional table")
    subfile_count = 2 if include_type3_candidate_index or include_type1_candidate_index else 1
    subfile_table_end = 32 + subfile_count * 16
    movie_header_offset = subfile_table_end
    movie_header_size = 0xB8
    pointer_table_offset = movie_header_offset + movie_header_size
    primary_slots_start = pointer_table_offset + 8
    primary_sentinel_slot = primary_slots_start + len(object_kinds) * 8
    additional_pointer_slot = primary_sentinel_slot + 8
    additional_table_offset = additional_pointer_slot + 8
    if imported_guid == 0:
        objects_start = primary_sentinel_slot + 8
    elif additional_object_kinds:
        objects_start = additional_table_offset + (len(additional_object_kinds) + 1) * 8
    else:
        objects_start = additional_table_offset
    body = bytearray(objects_start - movie_header_offset)
    all_kinds = object_kinds + additional_object_kinds

    struct.pack_into("<Q", body, 0, pointer_table_offset - movie_header_offset)
    struct.pack_into("<I", body, 0x40, len(all_kinds))
    struct.pack_into("<Q", body, 0x60, imported_guid)
    struct.pack_into("<I", body, 0xB0, 0)
    struct.pack_into("<Q", body, pointer_table_offset - movie_header_offset, 0)

    object_blobs: list[bytes] = []
    object_targets: list[int] = []
    current_object = objects_start
    for index, kind in enumerate(all_kinds):
        if kind == 6:
            name = text.encode("utf-16le") + b"\0\0"
            object_data = bytearray(104)
            struct.pack_into("<HH", object_data, 0, 0xFF06, index + 10)
            struct.pack_into("<4f", object_data, 32, 1.0, 2.0, 31.0, 42.0)
            string_target = current_object + 104
            struct.pack_into("<Q", object_data, 96, string_target - (current_object + 96))
            object_data.extend(name)
            object_blob = bytes(object_data)
        elif kind == 1 and include_type1_candidate_index:
            object_data = bytearray(80)
            object_data[0] = kind
            struct.pack_into("<Q", object_data, 0x48, 8)
            object_data.extend(kind1_tail)
            object_blob = bytes(object_data)
        elif kind == 3 and include_type3_candidate_index:
            object_data = bytearray(72)
            object_data[0] = kind
            struct.pack_into("<Q", object_data, 0x38, 16)
            struct.pack_into("<Q", object_data, 0x40, 8 + len(kind3_span))
            object_blob = bytes(object_data) + kind3_span + struct.pack("<QQ", 1, 1)
        else:
            object_blob = bytes([kind])
        object_targets.append(current_object)
        object_blobs.append(object_blob)
        current_object += len(object_blob)

    for index, target in enumerate(object_targets[: len(object_kinds)]):
        pointer_slot = primary_slots_start + index * 8
        struct.pack_into(
            "<Q", body, pointer_slot - movie_header_offset, target - pointer_slot
        )
    struct.pack_into("<Q", body, primary_sentinel_slot - movie_header_offset, 1)
    if imported_guid != 0:
        if additional_object_kinds:
            struct.pack_into(
                "<Q",
                body,
                additional_pointer_slot - movie_header_offset,
                additional_table_offset - additional_pointer_slot,
            )
            for index, target in enumerate(object_targets[len(object_kinds) :]):
                pointer_slot = additional_table_offset + index * 8
                struct.pack_into(
                    "<Q", body, pointer_slot - movie_header_offset, target - pointer_slot
                )
            additional_sentinel_slot = additional_table_offset + len(additional_object_kinds) * 8
            struct.pack_into("<Q", body, additional_sentinel_slot - movie_header_offset, 1)
        else:
            struct.pack_into("<Q", body, additional_pointer_slot - movie_header_offset, 1)
    for target, blob in zip(object_targets, object_blobs):
        body.extend(b"\0" * (target - (movie_header_offset + len(body))))
        body.extend(blob)

    movie_size = len(body)
    index_stream = b""
    if include_type3_candidate_index:
        object_start = object_targets[0] - movie_header_offset
        index_stream = bytearray(bytes((1, 72, 2, 0x38, 2, 0x40, 2, 0xFF)) + struct.pack("<I", object_start))
        for _ in object_targets:
            index_stream.append(0)
            index_stream.append(0xFF)
            index_stream.extend(struct.pack("<I", len(kind3_span) + 16))
        index_stream = bytes(index_stream)
    elif include_type1_candidate_index:
        object_start = object_targets[0] - movie_header_offset
        index_stream = bytes((1, 80, 1, 0x48, 2, 0xFF)) + struct.pack("<I", object_start) + b"\0"
    iggy = bytearray(subfile_table_end + movie_size + len(index_stream))
    struct.pack_into("<I", iggy, 0, IGGY_MAGIC)
    struct.pack_into("<I", iggy, 4, 0x900)
    iggy[8:12] = bytes((1, 64, 1, 3))
    struct.pack_into("<I", iggy, 12, 0x0C)
    struct.pack_into("<I", iggy, 28, subfile_count)
    struct.pack_into("<IIII", iggy, 32, 1, movie_size, movie_size, subfile_table_end)
    iggy[subfile_table_end : subfile_table_end + movie_size] = body
    if include_type3_candidate_index or include_type1_candidate_index:
        struct.pack_into(
            "<IIII",
            iggy,
            48,
            0,
            len(index_stream),
            len(index_stream),
            subfile_table_end + movie_size,
        )
        iggy[subfile_table_end + movie_size :] = index_stream
    return bytes(iggy)


class IggyMovieInspectorTests(unittest.TestCase):
    def test_recognizes_bounded_kind4_payload_envelopes(self) -> None:
        compressed = zlib.compress(b"bounded raster-like data")
        self.assertEqual(
            _classify_kind4_payload(compressed + b"tail", 0, len(compressed) + 4),
            "zlib_complete",
        )
        self.assertEqual(
            _classify_kind4_payload(compressed[:4], 0, 4),
            "zlib_incomplete",
        )
        jpeg = b"\xFF\xD8\xFF\xD9"
        length_prefixed_jpeg = struct.pack("<I", len(jpeg)) + jpeg + b"tail"
        self.assertEqual(
            _classify_kind4_payload(length_prefixed_jpeg, 0, len(length_prefixed_jpeg)),
            "length_prefixed_jpeg",
        )
        with self.assertRaisesRegex(IggyFormatError, "bounds"):
            _classify_kind4_payload(b"data", 3, 2)

    def test_classifies_candidate_relative_field_targets(self) -> None:
        shared = {
            "record_start": 100,
            "record_size": 80,
            "next_record_start": 300,
            "movie_start": 0,
            "movie_end": 500,
        }
        self.assertEqual(
            _classify_relative_field_target(
                field_offset=172,
                relative_value=8,
                object_starts=set(),
                **shared,
            ),
            "record_end",
        )
        self.assertEqual(
            _classify_relative_field_target(
                field_offset=172,
                relative_value=120,
                object_starts=set(),
                **shared,
            ),
            "interrecord_tail",
        )
        self.assertEqual(
            _classify_relative_field_target(
                field_offset=172,
                relative_value=1,
                object_starts=set(),
                **shared,
            ),
            "sentinel_one",
        )
        self.assertEqual(
            _classify_relative_field_target(
                field_offset=172,
                relative_value=18,
                object_starts={190},
                **shared,
            ),
            "object_start",
        )
        self.assertEqual(
            _classify_relative_field_target(
                field_offset=280,
                relative_value=221,
                object_starts=set(),
                **shared,
            ),
            "outside_movie",
        )

    def test_decodes_index_command_sizes_and_metadata(self) -> None:
        index = bytes(
            [
                2, 2, 0, 4, 1, 0, 5,
                0x00,
                0x81, 1,
                0xC0,
                0xD2, 0,
                0xFC, 0xAA,
                0xFD, 3, 1, 0x10, 5,
                0xFE, 1,
                0xFF, 5, 0, 0, 0,
            ]
        )
        result = _summarize_index_subfile(
            index,
            is_64_bit=True,
            object_start_kinds={2: 3, 23: 6, 30: 1},
        )
        self.assertEqual(result["index_table_entry_count"], 2)
        self.assertEqual(result["index_metadata_descriptor_count"], 1)
        self.assertEqual(result["first_command_delta"], 2)
        self.assertEqual(result["first_command_end_offset"], 2)
        self.assertEqual(result["command_count"], 8)
        self.assertEqual(result["final_cumulative_offset"], 30)
        self.assertEqual(result["object_start_match_count"], 3)
        self.assertEqual(result["distinct_object_start_match_count"], 3)
        self.assertEqual(result["object_start_matches_by_kind"], {"1": 1, "3": 1, "6": 1})
        self.assertEqual(result["object_start_match_offsets"], [2, 23, 30])

    def test_reports_repeated_object_start_boundaries(self) -> None:
        # A zero-length command can repeat the same cumulative boundary. Preserve
        # both observations so the aggregate can flag ambiguous matches.
        result = _summarize_index_subfile(
            bytes([1, 0, 0, 0xFC, 0, 0xFC, 0]),
            is_64_bit=True,
            object_start_kinds={0: 4},
        )
        self.assertEqual(result["object_start_match_count"], 2)
        self.assertEqual(result["distinct_object_start_match_count"], 1)
        self.assertEqual(result["object_start_match_offsets"], [0, 0])

    def test_maps_object_start_to_the_following_index_table_layout(self) -> None:
        result = _summarize_index_subfile(
            bytes([1, 5, 0, 0]),
            is_64_bit=True,
            object_start_kinds={0: 3},
        )
        self.assertEqual(
            result["object_start_layout_usage_by_kind"],
            {"3": {"0": {"count": 1, "declared_size": 5}}},
        )
        self.assertEqual(
            result["object_start_layout_table_entries"],
            {"0": {"index": 0, "declared_size": 5, "metadata_descriptors": []}},
        )
        self.assertEqual(result["object_start_layout_match_offsets"], [0])
        self.assertEqual(
            result["object_start_layout_matches"],
            [
                {
                    "movie_offset": 0,
                    "kind": 3,
                    "index_table_entry": 0,
                    "record_size": 5,
                    "command_code": 0,
                }
            ],
        )

    def test_builds_per_object_layout_and_relative_field_catalog(self) -> None:
        result = inspect_iggy(
            make_iggy(
                object_kinds=(3, 3),
                include_type3_candidate_index=True,
                kind3_span=b"opaque-span-1234",
            )
        )
        catalog = result["object_record_catalog"]
        self.assertEqual(len(catalog["records"]), 2)
        self.assertEqual(len(catalog["layout_definitions"]), 1)
        self.assertEqual(
            catalog["layout_definitions"][0]["metadata_descriptors"],
            [
                {"local_offset": 56, "type_code": 2},
                {"local_offset": 64, "type_code": 2},
            ],
        )
        for row in catalog["records"]:
            self.assertEqual(row["kind"], 3)
            self.assertEqual(row["candidate_record_size"], 72)
            self.assertEqual(len(row["relative_fields"]), 2)
            self.assertEqual(
                [field["local_offset"] for field in row["relative_fields"]],
                [56, 64],
            )
            self.assertTrue(all(field["target_relation"] in {"record_end", "interrecord_tail"} for field in row["relative_fields"]))
        self.assertNotIn("opaque-span-1234", str(catalog))

    def test_summarizes_ordered_index_stream_segments(self) -> None:
        result = _summarize_index_stream_relationship(
            [
                {
                    "subfile_index": 2,
                    "index_table_sha256": "same-table",
                    "first_command_end_offset": 204,
                    "object_start_match_offsets": [220, 300],
                    "final_cumulative_offset": 400,
                },
                {
                    "subfile_index": 1,
                    "index_table_sha256": "same-table",
                    "first_command_end_offset": 184,
                    "object_start_match_offsets": [200, 210],
                    "final_cumulative_offset": 200,
                },
            ]
        )
        self.assertTrue(result["object_start_matches_disjoint"])
        self.assertTrue(result["object_start_match_ranges_sequential"])
        self.assertTrue(result["index_table_definitions_identical"])
        self.assertEqual(result["segments"][1]["first_command_end_delta_from_previous_final"], 4)
        self.assertEqual(result["object_start_match_count"], 4)

    def test_rejects_index_command_with_missing_table_entry(self) -> None:
        with self.assertRaisesRegex(IggyFormatError, "missing table entry"):
            _summarize_index_subfile(bytes([1, 4, 0, 5]), is_64_bit=True)

    def test_rejects_truncated_index_command(self) -> None:
        with self.assertRaisesRegex(IggyFormatError, "32-bit length command"):
            _summarize_index_subfile(bytes([1, 4, 0, 0xFF, 1, 2]), is_64_bit=True)

    def test_reads_text_geometry_without_retaining_text(self) -> None:
        result = inspect_iggy(make_iggy(text="Native menu"), source_name="sample.iggy")
        self.assertEqual(result["object_kind_counts"], {"6": 1})
        self.assertEqual(result["object_pointer_count"], 1)
        self.assertEqual(result["text_objects"][0]["text_index"], 10)
        self.assertEqual(result["text_objects"][0]["bounds"], [1.0, 2.0, 31.0, 42.0])
        self.assertEqual(result["text_objects"][0]["utf16_code_units"], 11)
        self.assertEqual(result["text_objects"][0]["string_offset_from_object"], 104)
        self.assertEqual(
            result["kind_6_string_pointer_summary"],
            {
                "objects_checked": 1,
                "object_relative_target_offset_counts": {"104": 1},
                "all_targets_at_104_byte_text_record_end": True,
            },
        )
        self.assertNotIn("Native menu", str(result))

    def test_summarizes_kind3_field_target_bytes_and_object_distance(self) -> None:
        result = inspect_iggy(
            make_iggy(
                object_kinds=(3,),
                include_type3_candidate_index=True,
            )
        )
        self.assertEqual(
            result["candidate_field_target_payload_observations"],
            {
                "3": {
                    "0x40": {
                        "metadata_type_code": 2,
                        "objects_checked": 1,
                        "target_location_counts": {"record_end": 1},
                        "target_to_next_object_start_distance_counts": {"16": 1},
                        "target_prefix_u64_pair_counts": {"1,1": 1},
                    }
                }
            },
        )
        self.assertEqual(
            result["candidate_dual_pointer_observations"],
            {
                "3": {
                    "0x38_to_0x40": {
                        "objects_checked": 1,
                        "first_pointer_target_location_counts": {"record_end": 1},
                        "second_pointer_target_location_counts": {"record_end": 1},
                        "joint_target_location_counts": {"record_end->record_end": 1},
                        "first_to_second_span_byte_length_counts": {"0": 1},
                        "first_to_second_span_byte_length_mod_8_counts": {"0": 1},
                        "first_target_mod_8_counts": {"0": 1},
                        "first_target_delta_from_record_end_counts": {"0": 1},
                        "first_target_to_next_object_start_distance_counts": {"16": 1},
                        "second_target_delta_from_record_end_counts": {"0": 1},
                        "second_target_to_next_object_start_distance_counts": {"16": 1},
                        "second_target_prefix_u64_pair_counts": {"1,1": 1},
                        "span_envelope_counts": {"empty": 1},
                        "distinct_nonempty_span_sha256_count": 0,
                        "all_valid_spans_8_byte_aligned": True,
                    }
                }
            },
        )

    def test_summarizes_kind3_candidate_span_between_dual_pointers(self) -> None:
        opaque_span = b"0123456789ABCDEF"
        result = inspect_iggy(
            make_iggy(
                object_kinds=(3, 3),
                include_type3_candidate_index=True,
                kind3_span=opaque_span,
            )
        )
        self.assertEqual(result["object_pointer_count"], 2)
        self.assertEqual(
            result["candidate_dual_pointer_observations"],
            {
                "3": {
                    "0x38_to_0x40": {
                        "objects_checked": 2,
                        "first_pointer_target_location_counts": {"record_end": 2},
                        "second_pointer_target_location_counts": {"interrecord_tail": 2},
                        "joint_target_location_counts": {"record_end->interrecord_tail": 2},
                        "first_to_second_span_byte_length_counts": {"16": 2},
                        "first_to_second_span_byte_length_mod_8_counts": {"0": 2},
                        "first_target_mod_8_counts": {"0": 2},
                        "first_target_delta_from_record_end_counts": {"0": 2},
                        "first_target_to_next_object_start_distance_counts": {"32": 2},
                        "second_target_delta_from_record_end_counts": {"16": 2},
                        "second_target_to_next_object_start_distance_counts": {"16": 2},
                        "second_target_prefix_u64_pair_counts": {"1,1": 2},
                        "span_envelope_counts": {"opaque_nonzero": 2},
                        "distinct_nonempty_span_sha256_count": 1,
                        "all_valid_spans_8_byte_aligned": True,
                    }
                }
            },
        )
        self.assertNotIn(opaque_span.decode("ascii"), str(result))

    def test_summarizes_kind1_record_end_region_without_retaining_bytes(self) -> None:
        result = inspect_iggy(
            make_iggy(
                object_kinds=(1,),
                include_type1_candidate_index=True,
                kind1_tail=b"opaque-tail",
            )
        )
        self.assertEqual(
            result["candidate_record_end_region_observations"],
            {
                "1": {
                    "0x48": {
                        "metadata_type_code": 2,
                        "objects_checked": 1,
                        "target_location_counts": {"record_end": 1},
                        "region_byte_length_counts": {"11": 1},
                        "region_byte_length_mod_8_counts": {"3": 1},
                        "region_start_mod_8_counts": {"0": 1},
                        "region_envelope_counts": {"opaque_nonzero": 1},
                        "distinct_non_sentinel_region_sha256_count": 1,
                        "all_non_sentinel_regions_8_byte_aligned": False,
                    }
                }
            },
        )
        self.assertNotIn("opaque-tail", str(result))

    def test_counts_unknown_object_kinds_but_does_not_decode_them(self) -> None:
        result = inspect_iggy(make_iggy(object_kinds=(3, 4, 1, 6)))
        self.assertEqual(result["object_kind_counts"], {"1": 1, "3": 1, "4": 1, "6": 1})
        self.assertEqual(len(result["text_objects"]), 1)

    def test_reports_absent_additional_object_table(self) -> None:
        result = inspect_iggy(make_iggy(imported_guid=1))
        self.assertEqual(result["object_pointer_tables"]["primary_count"], 1)
        self.assertEqual(result["object_pointer_tables"]["additional_count"], 0)
        self.assertEqual(result["object_pointer_tables"]["additional_pointer_value"], 1)
        self.assertIsNone(result["object_pointer_tables"]["additional_table_movie_offset"])

    def test_reads_and_counts_additional_object_table(self) -> None:
        result = inspect_iggy(
            make_iggy(
                object_kinds=(3,),
                additional_object_kinds=(6,),
                imported_guid=1,
                text="Additional object",
            )
        )
        self.assertEqual(result["object_pointer_tables"]["primary_count"], 1)
        self.assertEqual(result["object_pointer_tables"]["additional_count"], 1)
        self.assertEqual(result["object_pointer_count"], 2)
        self.assertEqual(result["object_kind_counts"], {"3": 1, "6": 1})
        self.assertEqual(result["text_objects"][0]["utf16_code_units"], len("Additional object"))

    def test_rejects_out_of_range_additional_object_table(self) -> None:
        malformed = bytearray(make_iggy(imported_guid=1))
        # One leading slot, one primary entry, one sentinel, then the optional-table pointer.
        additional_pointer_field = 48 + 0xB8 + 8 + 8 + 8
        struct.pack_into("<Q", malformed, additional_pointer_field, 0x7FFF_FFFF)
        with self.assertRaisesRegex(IggyFormatError, "additional object table pointer points outside"):
            inspect_iggy(bytes(malformed))

    def test_rejects_wrong_magic(self) -> None:
        with self.assertRaisesRegex(IggyFormatError, "signature"):
            inspect_iggy(b"not an iggy file" + bytes(32))

    def test_rejects_out_of_range_object_pointer(self) -> None:
        malformed = bytearray(make_iggy())
        pointer_slot = 48 + 0xB8 + 8
        struct.pack_into("<Q", malformed, pointer_slot, 0x7FFF_FFFF)
        with self.assertRaisesRegex(IggyFormatError, "outside the movie subfile"):
            inspect_iggy(bytes(malformed))

    def test_rejects_non_64_bit_platform_marker(self) -> None:
        malformed = bytearray(make_iggy())
        malformed[9] = 32
        with self.assertRaisesRegex(IggyFormatError, "64-bit"):
            inspect_iggy(bytes(malformed))

    def test_rejects_subfile_outside_input(self) -> None:
        malformed = bytearray(make_iggy())
        struct.pack_into("<I", malformed, 36, len(malformed) + 1)
        with self.assertRaisesRegex(IggyFormatError, "outside its containing stream"):
            inspect_iggy(bytes(malformed))

    def test_reports_relative_header_targets_and_sentinels(self) -> None:
        iggy = bytearray(make_iggy())
        movie_header_offset = 48
        struct.pack_into("<Q", iggy, movie_header_offset + 0x20, 1)
        result = inspect_iggy(bytes(iggy))
        pointers = {item["name"]: item for item in result["movie_header_relative_pointers"]}
        self.assertEqual(pointers["base"]["target_movie_offset"], 0xB8)
        self.assertEqual(pointers["sequence_start_2"]["target_movie_offset"], None)

    def test_rejects_out_of_range_header_target(self) -> None:
        malformed = bytearray(make_iggy())
        movie_header_offset = 48
        struct.pack_into("<Q", malformed, movie_header_offset + 0x08, 0x7FFF_FFFF)
        with self.assertRaisesRegex(IggyFormatError, "header sequence_end pointer points outside"):
            inspect_iggy(bytes(malformed))


if __name__ == "__main__":
    unittest.main()
