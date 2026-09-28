#!/usr/bin/env python3
"""Read-only inspector for the 64-bit Iggy movie stream embedded in SoD2 assets.

Input is the `.iggy` payload extracted from an Unreal IggyPlayer export's
NormalExport.Extras field (skip the 20-byte Unreal/Iggy envelope). The report
contains bounded metadata, candidate record layouts, relative-field summaries,
and text-field geometry; it never copies original asset bytes or stores strings.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import zlib
from collections import Counter
from pathlib import Path
from typing import Any


IGGY_MAGIC = 0xED0A6749
IGGY_VERSION_9 = 0x900
IGGY_HEADER_SIZE = 32
IGGY_SUBFILE_ENTRY_SIZE = 16
FLASH_HEADER_SIZE = 0xB8
TEXT_OBJECT_KIND = 6
TEXT_TAG_TYPE = 0xFF06
FLASH_HEADER_RELATIVE_POINTERS = {
    "base": 0x00,
    "sequence_end": 0x08,
    "font_end": 0x10,
    "sequence_start_1": 0x18,
    "sequence_start_2": 0x20,
    "sequence_start_3": 0x28,
    "names": 0x70,
    "unknown_0x78": 0x78,
    "last_section": 0x88,
    "flash_filename": 0x90,
    "declaration_strings": 0x98,
    "font_types": 0xA0,
}
MAX_SUBFILES = 256
MAX_OBJECTS = 100_000
MAX_TEXT_UNITS = 1_000_000
MAX_INDEX_COMMANDS = 1_000_000
MAX_INLINE_DECODED_BYTES = 64 * 1024 * 1024


class IggyFormatError(ValueError):
    """Raised when offsets or structure fields do not fit the input stream."""


def _need(data: bytes, offset: int, size: int, end: int, description: str) -> None:
    if offset < 0 or size < 0 or offset + size > end or offset + size > len(data):
        raise IggyFormatError(f"{description} lies outside its containing stream")


def _u16(data: bytes, offset: int, end: int, description: str) -> int:
    _need(data, offset, 2, end, description)
    return struct.unpack_from("<H", data, offset)[0]


def _u32(data: bytes, offset: int, end: int, description: str) -> int:
    _need(data, offset, 4, end, description)
    return struct.unpack_from("<I", data, offset)[0]


def _u64(data: bytes, offset: int, end: int, description: str) -> int:
    _need(data, offset, 8, end, description)
    return struct.unpack_from("<Q", data, offset)[0]


def _relative_target(data: bytes, field_offset: int, end: int, description: str) -> int:
    relative = _u64(data, field_offset, end, description + " relative offset")
    if relative == 1:
        raise IggyFormatError(f"{description} has a null/sentinel offset")
    target = field_offset + relative
    if target < field_offset or target >= end:
        raise IggyFormatError(f"{description} points outside its containing stream")
    return target


def _read_utf16_string(data: bytes, offset: int, end: int) -> str:
    _need(data, offset, 2, end, "text string")
    cursor = offset
    units = 0
    while cursor + 2 <= end and units < MAX_TEXT_UNITS:
        if data[cursor : cursor + 2] == b"\0\0":
            try:
                return data[offset:cursor].decode("utf-16le", errors="strict")
            except UnicodeDecodeError as error:
                raise IggyFormatError("text string is not valid UTF-16LE") from error
        cursor += 2
        units += 1
    raise IggyFormatError("text string has no terminator within the bounded stream")


def _read_text_metadata(data: bytes, object_offset: int, stream_end: int) -> dict[str, Any]:
    _need(data, object_offset, 104, stream_end, "Iggy text object")
    tag_type = _u16(data, object_offset, stream_end, "Iggy text tag type")
    if tag_type != TEXT_TAG_TYPE:
        raise IggyFormatError(
            f"object kind {TEXT_OBJECT_KIND} has unexpected tag type 0x{tag_type:04X}"
        )
    text_index = _u16(data, object_offset + 2, stream_end, "Iggy text index")
    bounds = struct.unpack_from("<4f", data, object_offset + 32)
    if any(not (-1e7 < value < 1e7) for value in bounds):
        raise IggyFormatError("Iggy text object has implausible bounds")
    string_target = _relative_target(
        data, object_offset + 96, stream_end, "Iggy text initial string"
    )
    value = _read_utf16_string(data, string_target, stream_end)
    return {
        "text_index": text_index,
        "bounds": [round(value, 4) for value in bounds],
        "utf16_code_units": len(value.encode("utf-16le")) // 2,
        "string_offset_from_object": string_target - object_offset,
        "text_sha256": hashlib.sha256(value.encode("utf-8")).hexdigest(),
    }


def _read_movie_header_pointers(
    data: bytes, movie_start: int, movie_end: int
) -> list[dict[str, int | str | None]]:
    pointers: list[dict[str, int | str | None]] = []
    for name, header_offset in FLASH_HEADER_RELATIVE_POINTERS.items():
        field_offset = movie_start + header_offset
        relative = _u64(data, field_offset, movie_end, f"Iggy header {name} pointer")
        if relative == 1:
            target = None
        else:
            target = field_offset + relative
            if target < field_offset or target >= movie_end:
                raise IggyFormatError(f"Iggy header {name} pointer points outside the movie subfile")
            target -= movie_start
        pointers.append(
            {
                "name": name,
                "header_offset": header_offset,
                "relative_value": relative,
                "target_movie_offset": target,
            }
        )
    return pointers


def _read_object_pointer_table(
    data: bytes,
    table_start: int,
    movie_end: int,
    *,
    description: str,
    has_leading_sentinel: bool,
) -> tuple[list[int], int]:
    cursor = table_start + (8 if has_leading_sentinel else 0)
    targets: list[int] = []
    for _ in range(MAX_OBJECTS):
        relative = _u64(data, cursor, movie_end, f"{description} object pointer")
        if relative == 1:
            return targets, cursor + 8
        target = cursor + relative
        if target < cursor or target >= movie_end:
            raise IggyFormatError(f"{description} object pointer points outside the movie subfile")
        targets.append(target)
        cursor += 8
    raise IggyFormatError(f"{description} pointer table exceeds the safety limit")


def _classify_relative_field_target(
    *,
    field_offset: int,
    relative_value: int,
    record_start: int,
    record_size: int,
    next_record_start: int,
    movie_start: int,
    movie_end: int,
    object_starts: set[int],
) -> str:
    """Classify a candidate field-relative target without decoding its payload."""
    if relative_value == 1:
        return "sentinel_one"
    target = field_offset + relative_value
    if target < movie_start or target >= movie_end:
        return "outside_movie"
    record_end = record_start + record_size
    if target == record_end:
        return "record_end"
    if target in object_starts:
        return "object_start"
    if record_start <= target < record_end:
        return "inside_record"
    if record_end < target < next_record_start:
        return "interrecord_tail"
    return "other_in_movie"


def _classify_kind4_payload(data: bytes, target: int, end: int) -> str:
    """Recognize bounded kind-4 payload envelopes without retaining their contents."""
    if target < 0 or end < target or end > len(data):
        raise IggyFormatError("kind-4 candidate payload bounds are invalid")
    payload = data[target:end]
    if len(payload) >= 2 and payload[0] == 0x78:
        try:
            decoder = zlib.decompressobj()
            decoded = decoder.decompress(payload, MAX_INLINE_DECODED_BYTES + 1)
        except zlib.error:
            return "zlib_invalid"
        if len(decoded) > MAX_INLINE_DECODED_BYTES or decoder.unconsumed_tail:
            return "zlib_output_limit"
        return "zlib_complete" if decoder.eof else "zlib_incomplete"
    if len(payload) >= 8:
        image_size = _u32(data, target, end, "kind-4 JPEG length")
        image_start = target + 4
        image_end = image_start + image_size
        if (
            image_size >= 4
            and image_end <= end
            and data[image_start : image_start + 2] == b"\xFF\xD8"
            and data[image_end - 2 : image_end] == b"\xFF\xD9"
        ):
            return "length_prefixed_jpeg"
        if data[image_start : image_start + 2] == b"\xFF\xD8":
            return "length_prefixed_jpeg_invalid"
    return "unrecognized"


def _summarize_index_subfile(
    data: bytes,
    *,
    is_64_bit: bool,
    object_start_kinds: dict[int, int] | None = None,
) -> dict[str, Any]:
    if not data:
        raise IggyFormatError("Iggy index subfile is empty")
    table_size = data[0]
    if table_size == 0:
        raise IggyFormatError("Iggy index subfile has an empty index table")
    cursor = 1
    table_values: list[int] = []
    table_layouts: list[dict[str, Any]] = []
    metadata_descriptors = 0
    for index in range(table_size):
        _need(data, cursor, 2, len(data), f"Iggy index table entry {index}")
        value = data[cursor]
        metadata_count = data[cursor + 1]
        cursor += 2
        _need(data, cursor, metadata_count * 2, len(data), f"Iggy index metadata entry {index}")
        descriptors = [
            {"local_offset": data[cursor + item * 2], "type_code": data[cursor + item * 2 + 1]}
            for item in range(metadata_count)
        ]
        cursor += metadata_count * 2
        table_values.append(value)
        table_layouts.append(
            {"index": index, "declared_size": value, "metadata_descriptors": descriptors}
        )
        metadata_descriptors += metadata_count
    index_table_byte_length = cursor

    command_counts: Counter[int] = Counter()
    cumulative_offset = 0
    maximum_offset = 0
    command_count = 0
    object_start_matches: list[int] = []
    object_start_match_counts: Counter[int] = Counter()
    object_start_layout_counts: Counter[tuple[int, int | None, int, int]] = Counter()
    object_start_layout_match_offsets: list[int] = []
    object_start_layout_matches: list[dict[str, int | None]] = []
    first_command_delta: int | None = None
    first_command_end_offset: int | None = None
    while cursor < len(data):
        if command_count >= MAX_INDEX_COMMANDS:
            raise IggyFormatError("Iggy index stream exceeds the command safety limit")
        command_offset = cursor
        cumulative_start = cumulative_offset
        code = data[cursor]
        cursor += 1
        command_counts[code] += 1
        command_count += 1
        table_index: int | None = None

        if code < 0x80:
            if code >= table_size:
                raise IggyFormatError(f"Iggy index command references missing table entry {code}")
            table_index = code
            delta = table_values[code]
        elif code < 0xC0:
            _need(data, cursor, 1, len(data), "Iggy index repeated-table command")
            table_index = data[cursor]
            cursor += 1
            if table_index >= table_size:
                raise IggyFormatError(f"Iggy index command references missing table entry {table_index}")
            delta = table_values[table_index] * (code - 0x7F)
        elif code < 0xD0:
            delta = code * 2 - 0x17E
        elif code < 0xE0:
            _need(data, cursor, 1, len(data), "Iggy index platform-array command")
            count = data[cursor] + 1
            cursor += 1
            kind = code & 0x0F
            if is_64_bit:
                element_size = 8 if kind <= 2 or kind == 6 else 2 if kind <= 4 else 4 if kind == 5 else 0
            else:
                element_size = {2: 4, 4: 2, 5: 4, 6: 8}.get(kind, 0)
            if element_size == 0:
                raise IggyFormatError(f"Unsupported Iggy index platform element kind {kind} at {command_offset}")
            delta = element_size * count
        elif code == 0xFC:
            _need(data, cursor, 1, len(data), "Iggy index skip command")
            cursor += 1
            delta = 0
        elif code == 0xFD:
            _need(data, cursor, 2, len(data), "Iggy index custom-length command")
            delta = data[cursor]
            descriptor_count = data[cursor + 1]
            cursor += 2
            _need(data, cursor, descriptor_count * 2, len(data), "Iggy index custom-length descriptors")
            cursor += descriptor_count * 2
        elif code == 0xFE:
            _need(data, cursor, 1, len(data), "Iggy index one-byte length command")
            delta = data[cursor] + 1
            cursor += 1
        elif code == 0xFF:
            delta = _u32(data, cursor, len(data), "Iggy index 32-bit length command")
            cursor += 4
        else:
            raise IggyFormatError(f"Unsupported Iggy index command 0x{code:02X} at {command_offset}")

        if command_count == 1:
            first_command_delta = delta
            first_command_end_offset = cumulative_offset + delta
        cumulative_offset += delta
        if cumulative_offset > 0xFFFFFFFFFFFFFFFF:
            raise IggyFormatError("Iggy index cumulative offset overflows 64 bits")
        maximum_offset = max(maximum_offset, cumulative_offset)
        if object_start_kinds is not None and cumulative_offset in object_start_kinds:
            object_start_matches.append(cumulative_offset)
            object_start_match_counts[object_start_kinds[cumulative_offset]] += 1
        if object_start_kinds is not None and cumulative_start in object_start_kinds:
            object_start_layout_counts[
                (object_start_kinds[cumulative_start], table_index, delta, code)
            ] += 1
            object_start_layout_match_offsets.append(cumulative_start)
            object_start_layout_matches.append(
                {
                    "movie_offset": cumulative_start,
                    "kind": object_start_kinds[cumulative_start],
                    "index_table_entry": table_index,
                    "record_size": delta,
                    "command_code": code,
                }
            )

    result = {
        "index_table_entry_count": table_size,
        "index_metadata_descriptor_count": metadata_descriptors,
        "index_table_byte_length": index_table_byte_length,
        "index_table_sha256": hashlib.sha256(data[:index_table_byte_length]).hexdigest(),
        "command_count": command_count,
        "first_command_delta": first_command_delta,
        "first_command_end_offset": first_command_end_offset,
        "command_code_counts": {f"0x{code:02X}": count for code, count in sorted(command_counts.items())},
        "final_cumulative_offset": cumulative_offset,
        "maximum_cumulative_offset": maximum_offset,
        "bytes_consumed": cursor,
    }
    if object_start_kinds is not None:
        distinct_matches = set(object_start_matches)
        layout_usage: dict[str, dict[str, dict[str, int]]] = {}
        used_table_indexes: set[int] = set()
        for (kind, table_index, declared_size, code), count in sorted(
            object_start_layout_counts.items(),
            key=lambda item: (
                item[0][0],
                item[0][1] if item[0][1] is not None else -1,
                item[0][2],
                item[0][3],
            ),
        ):
            layout_key = str(table_index) if table_index is not None else f"command_0x{code:02X}"
            layout_usage.setdefault(str(kind), {})[layout_key] = {
                "count": count,
                "declared_size": declared_size,
            }
            if table_index is not None:
                used_table_indexes.add(table_index)
        used_layouts = {
            str(index): table_layouts[index]
            for index in sorted(used_table_indexes)
        }
        result.update(
            {
        "object_start_match_count": len(object_start_matches),
        "distinct_object_start_match_count": len(distinct_matches),
        "first_object_start_match_offset": min(object_start_matches) if object_start_matches else None,
        "last_object_start_match_offset": max(object_start_matches) if object_start_matches else None,
        "object_start_matches_by_kind": {
                    str(kind): object_start_match_counts[kind]
                    for kind in sorted(object_start_match_counts)
                },
                "object_start_match_offsets": object_start_matches,
                "object_start_layout_match_offsets": object_start_layout_match_offsets,
                "object_start_layout_matches": object_start_layout_matches,
                "object_start_layout_usage_by_kind": layout_usage,
                "object_start_layout_table_entries": used_layouts,
            }
        )
    return result


def _summarize_index_stream_relationship(index_subfiles: list[dict[str, Any]]) -> dict[str, Any]:
    ordered_streams = sorted(index_subfiles, key=lambda row: row["subfile_index"])
    all_matches = [
        offset
        for stream in ordered_streams
        for offset in stream.get("object_start_match_offsets", [])
    ]
    unique_matches = set(all_matches)
    ranges_sequential = True
    segments: list[dict[str, Any]] = []
    for index, stream in enumerate(ordered_streams):
        matches = stream.get("object_start_match_offsets", [])
        previous = ordered_streams[index - 1] if index > 0 else None
        previous_end = previous.get("final_cumulative_offset") if previous else None
        first_command_end = stream.get("first_command_end_offset")
        if previous is not None:
            previous_matches = previous.get("object_start_match_offsets", [])
            if matches and previous_matches and max(previous_matches) >= min(matches):
                ranges_sequential = False
        segments.append(
            {
                "subfile_index": stream["subfile_index"],
                "index_table_sha256": stream.get("index_table_sha256"),
                "first_command_end_offset": first_command_end,
                "first_object_start_offset": min(matches) if matches else None,
                "last_object_start_offset": max(matches) if matches else None,
                "final_cumulative_offset": stream.get("final_cumulative_offset"),
                "first_command_end_delta_from_previous_final": (
                    first_command_end - previous_end
                    if previous_end is not None and first_command_end is not None
                    else None
                ),
            }
        )
    table_hashes = {stream.get("index_table_sha256") for stream in ordered_streams}
    return {
        "stream_count": len(ordered_streams),
        "object_start_matches_disjoint": len(unique_matches) == len(all_matches),
        "object_start_match_ranges_sequential": ranges_sequential,
        "index_table_definitions_identical": len(table_hashes) <= 1,
        "object_start_match_count": len(all_matches),
        "distinct_object_start_match_count": len(unique_matches),
        "segments": segments,
    }


def inspect_iggy(data: bytes, *, source_name: str = "") -> dict[str, Any]:
    """Inspect one 64-bit Iggy movie without retaining any original text."""
    if len(data) < IGGY_HEADER_SIZE:
        raise IggyFormatError("input is shorter than the Iggy header")
    if _u32(data, 0, len(data), "Iggy signature") != IGGY_MAGIC:
        raise IggyFormatError("input does not start with the Iggy signature")

    version = _u32(data, 4, len(data), "Iggy version")
    platform = list(data[8:12])
    if platform[1] != 64:
        raise IggyFormatError("only 64-bit Iggy streams are supported by this inspector")
    subfile_count = _u32(data, 28, len(data), "Iggy subfile count")
    if subfile_count == 0 or subfile_count > MAX_SUBFILES:
        raise IggyFormatError(f"invalid Iggy subfile count: {subfile_count}")
    _need(
        data,
        IGGY_HEADER_SIZE,
        subfile_count * IGGY_SUBFILE_ENTRY_SIZE,
        len(data),
        "Iggy subfile table",
    )

    subfiles: list[dict[str, int]] = []
    flash_subfiles: list[tuple[int, int, int]] = []
    index_subfile_data: list[tuple[int, int, bytes]] = []
    for index in range(subfile_count):
        entry_offset = IGGY_HEADER_SIZE + index * IGGY_SUBFILE_ENTRY_SIZE
        kind, size, size2, offset = struct.unpack_from("<IIII", data, entry_offset)
        _need(data, offset, size, len(data), f"Iggy subfile {index}")
        subfiles.append({"kind": kind, "size": size, "size2": size2, "offset": offset})
        if kind == 1:
            flash_subfiles.append((offset, size, index))
        elif kind == 0:
            index_subfile_data.append((index, size, data[offset : offset + size]))

    if len(flash_subfiles) != 1:
        raise IggyFormatError(
            f"expected one type-1 movie subfile, found {len(flash_subfiles)}"
        )

    movie_start, movie_size, movie_index = flash_subfiles[0]
    movie_end = movie_start + movie_size
    _need(data, movie_start, FLASH_HEADER_SIZE, movie_end, "64-bit Flash/Iggy header")
    object_capacity = _u32(data, movie_start + 0x40, movie_end, "header field 0x40")
    font_count = _u32(data, movie_start + 0xB0, movie_end, "Iggy font count")
    if object_capacity > MAX_OBJECTS:
        raise IggyFormatError(f"object capacity field is implausibly large: {object_capacity}")

    pointer_table = _relative_target(data, movie_start, movie_end, "Iggy object pointer table")
    movie_header_pointers = _read_movie_header_pointers(data, movie_start, movie_end)
    imported_guid = _u64(data, movie_start + 0x60, movie_end, "Iggy imported GUID field")
    primary_targets, after_primary_table = _read_object_pointer_table(
        data,
        pointer_table,
        movie_end,
        description="Iggy primary",
        has_leading_sentinel=True,
    )

    additional_pointer_value: int | None = None
    additional_table_offset: int | None = None
    additional_targets: list[int] = []
    if imported_guid != 0:
        additional_pointer_field = after_primary_table
        additional_pointer_value = _u64(
            data, additional_pointer_field, movie_end, "Iggy additional object table pointer"
        )
        if additional_pointer_value != 1:
            additional_table_offset = additional_pointer_field + additional_pointer_value
            if additional_table_offset < additional_pointer_field or additional_table_offset >= movie_end:
                raise IggyFormatError("Iggy additional object table pointer points outside the movie subfile")
            additional_targets, _ = _read_object_pointer_table(
                data,
                additional_table_offset,
                movie_end,
                description="Iggy additional",
                has_leading_sentinel=False,
            )

    kinds: Counter[int] = Counter()
    text_objects: list[dict[str, Any]] = []
    object_offsets: set[int] = set()
    all_targets = primary_targets + additional_targets
    if len(all_targets) > MAX_OBJECTS:
        raise IggyFormatError("Iggy object pointer tables exceed the combined safety limit")
    object_start_kinds: dict[int, int] = {}
    for target in all_targets:
        if target in object_offsets:
            raise IggyFormatError("Iggy object pointer tables contain a duplicate target")
        object_offsets.add(target)
        kind = data[target]
        kinds[kind] += 1
        object_start_kinds[target - movie_start] = kind
        if kind == TEXT_OBJECT_KIND:
            text_metadata = _read_text_metadata(data, target, movie_end)
            text_metadata["stream_offset"] = target - movie_start
            text_objects.append(text_metadata)

    index_subfiles: list[dict[str, Any]] = []
    for index, size, index_data in index_subfile_data:
        index_report = _summarize_index_subfile(
            index_data,
            is_64_bit=True,
            object_start_kinds=object_start_kinds,
        )
        index_report["subfile_index"] = index
        index_report["size"] = size
        index_report["sha256"] = hashlib.sha256(index_data).hexdigest()
        index_subfiles.append(index_report)
    index_stream_relationship = _summarize_index_stream_relationship(index_subfiles)

    matched_object_offsets = [
        offset
        for index_report in index_subfiles
        for offset in index_report["object_start_match_offsets"]
    ]
    matched_object_offset_set = set(matched_object_offsets)
    object_index_correspondence = {
        "object_pointer_count": len(object_start_kinds),
        "distinct_object_starts_matched": len(matched_object_offset_set),
        "unmatched_object_start_count": len(object_start_kinds) - len(matched_object_offset_set),
        "duplicate_match_count": len(matched_object_offsets) - len(matched_object_offset_set),
        "every_object_start_matches_exactly_once": (
            len(matched_object_offset_set) == len(object_start_kinds)
            and len(matched_object_offsets) == len(object_start_kinds)
        ),
    }
    command_start_offsets = [
        offset
        for index_report in index_subfiles
        for offset in index_report.get("object_start_layout_match_offsets", [])
    ]
    kind_layout_counts: dict[str, dict[str, int]] = {}
    kind_layout_counts_by_kind: Counter[int] = Counter()
    object_layouts_by_kind: dict[str, dict[str, Any]] = {}
    layout_definition_conflicts: list[str] = []
    for index_report in index_subfiles:
        for kind, layouts in index_report.get("object_start_layout_usage_by_kind", {}).items():
            for table_entry, usage in layouts.items():
                kind_layout_counts.setdefault(kind, {})[table_entry] = (
                    kind_layout_counts.setdefault(kind, {}).get(table_entry, 0) + usage["count"]
                )
                kind_layout_counts_by_kind[int(kind)] += usage["count"]
                definition = index_report["object_start_layout_table_entries"][table_entry]
                per_kind = object_layouts_by_kind.setdefault(
                    kind,
                    {
                        "object_count": 0,
                        "record_size": definition["declared_size"],
                        "metadata_descriptors": definition["metadata_descriptors"],
                        "index_table_entries_by_subfile": {},
                    },
                )
                if (
                    per_kind["record_size"] != definition["declared_size"]
                    or per_kind["metadata_descriptors"] != definition["metadata_descriptors"]
                ):
                    layout_definition_conflicts.append(
                        f"kind {kind} has different table layout at subfile {index_report['subfile_index']} entry {table_entry}"
                    )
                per_kind["object_count"] += usage["count"]
                per_kind["index_table_entries_by_subfile"].setdefault(
                    str(index_report["subfile_index"]), []
                ).append(int(table_entry))
    for per_kind in object_layouts_by_kind.values():
        for subfile_entries in per_kind["index_table_entries_by_subfile"].values():
            subfile_entries.sort()
    object_layout_matches_by_offset: dict[int, list[dict[str, Any]]] = {}
    object_layout_definitions: dict[tuple[int, int, int], dict[str, Any]] = {}
    for index_report in index_subfiles:
        table_entries = index_report.get("object_start_layout_table_entries", {})
        for match in index_report.get("object_start_layout_matches", []):
            table_index = match["index_table_entry"]
            descriptor_rows: list[dict[str, int]] = []
            if table_index is not None:
                definition = table_entries.get(str(table_index))
                if definition is not None:
                    descriptor_rows = definition["metadata_descriptors"]
                    object_layout_definitions[
                        (match["kind"], index_report["subfile_index"], table_index)
                    ] = {
                        "kind": match["kind"],
                        "index_subfile": index_report["subfile_index"],
                        "index_table_entry": table_index,
                        "record_size": match["record_size"],
                        "metadata_descriptors": descriptor_rows,
                    }
            object_layout_matches_by_offset.setdefault(match["movie_offset"], []).append(
                {
                    "index_subfile": index_report["subfile_index"],
                    "index_table_entry": table_index,
                    "command_code": match["command_code"],
                    "record_size": match["record_size"],
                }
            )
    ordered_targets = sorted(all_targets)
    known_record_count = 0
    record_overlap_count = 0
    object_record_rows: list[dict[str, Any]] = []
    field_relative_target_observations: dict[str, dict[str, dict[str, int]]] = {}
    candidate_field_target_payload_observations: dict[str, dict[str, dict[str, Any]]] = {}
    candidate_payload_format_observations: dict[str, dict[str, dict[str, Any]]] = {}
    candidate_record_end_region_observations: dict[str, dict[str, dict[str, Any]]] = {}
    candidate_dual_pointer_observations: dict[str, dict[str, dict[str, Any]]] = {}
    for object_index, target in enumerate(ordered_targets):
        kind = data[target]
        kind_layout = object_layouts_by_kind.get(str(kind))
        if kind_layout is None:
            continue
        known_record_count += 1
        record_size = kind_layout["record_size"]
        next_record_start = (
            ordered_targets[object_index + 1]
            if object_index + 1 < len(ordered_targets)
            else movie_end
        )
        record_end = target + record_size
        if record_end > next_record_start or record_end > movie_end:
            record_overlap_count += 1
        movie_offset = target - movie_start
        next_movie_offset = next_record_start - movie_start
        record_fields: list[dict[str, int | str | None]] = []
        for match in object_layout_matches_by_offset.get(movie_offset, []):
            table_index = match["index_table_entry"]
            if table_index is None:
                continue
            definition = object_layout_definitions.get(
                (kind, match["index_subfile"], table_index)
            )
            if definition is None:
                continue
            for descriptor in definition["metadata_descriptors"]:
                if descriptor["type_code"] != 2:
                    continue
                local_offset = descriptor["local_offset"]
                if local_offset + 8 > match["record_size"]:
                    raise IggyFormatError(
                        f"kind {kind} type-code-2 field at {local_offset} exceeds its candidate record"
                    )
                field_offset = target + local_offset
                relative_value = _u64(
                    data, field_offset, movie_end, "Iggy catalog relative field"
                )
                target_relation = _classify_relative_field_target(
                    field_offset=field_offset,
                    relative_value=relative_value,
                    record_start=target,
                    record_size=match["record_size"],
                    next_record_start=next_record_start,
                    movie_start=movie_start,
                    movie_end=movie_end,
                    object_starts=object_offsets,
                )
                record_fields.append(
                    {
                        "local_offset": local_offset,
                        "type_code": descriptor["type_code"],
                        "relative_value": relative_value,
                        "target_movie_offset": (
                            field_offset + relative_value - movie_start
                            if relative_value != 1
                            else None
                        ),
                        "target_relation": target_relation,
                    }
                )
        object_record_rows.append(
            {
                "object_index": len(object_record_rows),
                "movie_offset": movie_offset,
                "kind": kind,
                "next_object_movie_offset": next_movie_offset,
                "candidate_record_size": record_size,
                "index_layout_matches": object_layout_matches_by_offset.get(movie_offset, []),
                "relative_fields": record_fields,
            }
        )
        for descriptor in kind_layout["metadata_descriptors"]:
            if descriptor["type_code"] != 2:
                continue
            local_offset = descriptor["local_offset"]
            if local_offset + 8 > record_size:
                raise IggyFormatError(
                    f"kind {kind} type-code-2 field at {local_offset} exceeds its candidate record"
                )
            field_offset = target + local_offset
            relative_value = _u64(
                data, field_offset, movie_end, "Iggy candidate relative field"
            )
            observation = _classify_relative_field_target(
                field_offset=field_offset,
                relative_value=relative_value,
                record_start=target,
                record_size=record_size,
                next_record_start=next_record_start,
                movie_start=movie_start,
                movie_end=movie_end,
                object_starts=object_offsets,
            )
            field_summary = field_relative_target_observations.setdefault(
                str(kind), {}
            ).setdefault(
                f"0x{local_offset:X}",
                {"metadata_type_code": 2, "objects_checked": 0},
            )
            field_summary["objects_checked"] += 1
            field_summary[observation] = field_summary.get(observation, 0) + 1
            if kind == 3 and local_offset == 0x40 and relative_value != 1:
                candidate_summary = candidate_field_target_payload_observations.setdefault(
                    str(kind), {}
                ).setdefault(
                    f"0x{local_offset:X}",
                    {
                        "metadata_type_code": 2,
                        "objects_checked": 0,
                        "target_location_counts": {},
                        "target_to_next_object_start_distance_counts": {},
                        "target_prefix_u64_pair_counts": {},
                    },
                )
                candidate_summary["objects_checked"] += 1
                for counter_name, key in (
                    ("target_location_counts", observation),
                    ("target_to_next_object_start_distance_counts", str(next_record_start - (field_offset + relative_value))),
                ):
                    counter = candidate_summary[counter_name]
                    counter[key] = counter.get(key, 0) + 1
                payload_target = field_offset + relative_value
                if payload_target + 16 <= min(next_record_start, movie_end):
                    pair = struct.unpack_from("<QQ", data, payload_target)
                    pair_key = f"{pair[0]},{pair[1]}"
                else:
                    pair_key = "outside_16_byte_window"
                pair_counts = candidate_summary["target_prefix_u64_pair_counts"]
                pair_counts[pair_key] = pair_counts.get(pair_key, 0) + 1
            if kind == 4 and local_offset == 0x48 and relative_value != 1:
                payload_target = field_offset + relative_value
                if payload_target > next_record_start:
                    format_name = "target_after_next_object"
                else:
                    format_name = _classify_kind4_payload(
                        data,
                        payload_target,
                        min(next_record_start, movie_end),
                    )
                payload_summary = candidate_payload_format_observations.setdefault(
                    str(kind), {}
                ).setdefault(
                    f"0x{local_offset:X}",
                    {
                        "metadata_type_code": 2,
                        "objects_checked": 0,
                        "target_format_counts": {},
                    },
                )
                payload_summary["objects_checked"] += 1
                format_counts = payload_summary["target_format_counts"]
                format_counts[format_name] = format_counts.get(format_name, 0) + 1
            if kind == 1 and local_offset == 0x48:
                region_summary = candidate_record_end_region_observations.setdefault(
                    str(kind), {}
                ).setdefault(
                    f"0x{local_offset:X}",
                    {
                        "metadata_type_code": 2,
                        "objects_checked": 0,
                        "target_location_counts": {},
                        "region_byte_length_counts": {},
                        "region_byte_length_mod_8_counts": {},
                        "region_start_mod_8_counts": {},
                        "region_envelope_counts": {},
                        "_region_sha256s": set(),
                    },
                )
                region_summary["objects_checked"] += 1
                location_counts = region_summary["target_location_counts"]
                location_counts[observation] = location_counts.get(observation, 0) + 1
                if relative_value == 1:
                    envelope = "sentinel_no_region"
                    region_size = 0
                else:
                    region_target = field_offset + relative_value
                    if region_target < record_end:
                        envelope = "target_inside_record"
                        region_size = 0
                    elif region_target > next_record_start:
                        envelope = "target_after_next_object"
                        region_size = 0
                    else:
                        region_size = next_record_start - region_target
                        start_alignment_counts = region_summary["region_start_mod_8_counts"]
                        alignment_key = str(region_target % 8)
                        start_alignment_counts[alignment_key] = start_alignment_counts.get(alignment_key, 0) + 1
                        if region_size == 0:
                            envelope = "empty"
                        elif not any(data[region_target:next_record_start]):
                            envelope = "zero_fill"
                        else:
                            envelope = _classify_kind4_payload(
                                data, region_target, next_record_start
                            )
                            if envelope == "unrecognized":
                                envelope = "opaque_nonzero"
                        region_summary["_region_sha256s"].add(
                            hashlib.sha256(data[region_target:next_record_start]).hexdigest()
                        )
                size_counts = region_summary["region_byte_length_counts"]
                size_key = str(region_size)
                size_counts[size_key] = size_counts.get(size_key, 0) + 1
                size_mod_counts = region_summary["region_byte_length_mod_8_counts"]
                size_mod_key = str(region_size % 8)
                size_mod_counts[size_mod_key] = size_mod_counts.get(size_mod_key, 0) + 1
                envelope_counts = region_summary["region_envelope_counts"]
                envelope_counts[envelope] = envelope_counts.get(envelope, 0) + 1
        if kind == 3:
            descriptor_offsets = {
                item["local_offset"]
                for item in kind_layout["metadata_descriptors"]
                if item["type_code"] == 2
            }
            if {0x38, 0x40} <= descriptor_offsets:
                first_field = target + 0x38
                second_field = target + 0x40
                first_relative = _u64(data, first_field, movie_end, "Iggy kind-3 first candidate pointer")
                second_relative = _u64(data, second_field, movie_end, "Iggy kind-3 second candidate pointer")
                first_location = _classify_relative_field_target(
                    field_offset=first_field,
                    relative_value=first_relative,
                    record_start=target,
                    record_size=record_size,
                    next_record_start=next_record_start,
                    movie_start=movie_start,
                    movie_end=movie_end,
                    object_starts=object_offsets,
                )
                second_location = _classify_relative_field_target(
                    field_offset=second_field,
                    relative_value=second_relative,
                    record_start=target,
                    record_size=record_size,
                    next_record_start=next_record_start,
                    movie_start=movie_start,
                    movie_end=movie_end,
                    object_starts=object_offsets,
                )
                dual_summary = candidate_dual_pointer_observations.setdefault(
                    str(kind), {}
                ).setdefault(
                    "0x38_to_0x40",
                    {
                        "objects_checked": 0,
                        "first_pointer_target_location_counts": {},
                        "second_pointer_target_location_counts": {},
                        "joint_target_location_counts": {},
                        "first_to_second_span_byte_length_counts": {},
                        "first_to_second_span_byte_length_mod_8_counts": {},
                        "first_target_mod_8_counts": {},
                        "first_target_delta_from_record_end_counts": {},
                        "first_target_to_next_object_start_distance_counts": {},
                        "second_target_delta_from_record_end_counts": {},
                        "second_target_to_next_object_start_distance_counts": {},
                        "second_target_prefix_u64_pair_counts": {},
                        "span_envelope_counts": {},
                        "_nonempty_span_sha256s": set(),
                    },
                )
                dual_summary["objects_checked"] += 1
                for name, value in (
                    ("first_pointer_target_location_counts", first_location),
                    ("second_pointer_target_location_counts", second_location),
                    ("joint_target_location_counts", f"{first_location}->{second_location}"),
                ):
                    counts = dual_summary[name]
                    counts[value] = counts.get(value, 0) + 1
                span_length_key = "unresolved_sentinel"
                envelope = "unresolved_sentinel"
                if first_relative != 1 and second_relative != 1:
                    first_target = first_field + first_relative
                    second_target = second_field + second_relative
                    first_delta = first_target - record_end
                    first_delta_counts = dual_summary["first_target_delta_from_record_end_counts"]
                    first_delta_key = str(first_delta)
                    first_delta_counts[first_delta_key] = first_delta_counts.get(first_delta_key, 0) + 1
                    first_gap = next_record_start - first_target
                    first_gap_counts = dual_summary["first_target_to_next_object_start_distance_counts"]
                    first_gap_key = str(first_gap)
                    first_gap_counts[first_gap_key] = first_gap_counts.get(first_gap_key, 0) + 1
                    second_delta = second_target - record_end
                    second_delta_counts = dual_summary["second_target_delta_from_record_end_counts"]
                    second_delta_key = str(second_delta)
                    second_delta_counts[second_delta_key] = second_delta_counts.get(second_delta_key, 0) + 1
                    gap = next_record_start - second_target
                    gap_counts = dual_summary["second_target_to_next_object_start_distance_counts"]
                    gap_key = str(gap)
                    gap_counts[gap_key] = gap_counts.get(gap_key, 0) + 1
                    if second_target + 16 <= min(next_record_start, movie_end):
                        pair = struct.unpack_from("<QQ", data, second_target)
                        pair_key = f"{pair[0]},{pair[1]}"
                    else:
                        pair_key = "outside_next_object_16_byte_window"
                    pair_counts = dual_summary["second_target_prefix_u64_pair_counts"]
                    pair_counts[pair_key] = pair_counts.get(pair_key, 0) + 1
                    if second_target < first_target:
                        span_length_key = "negative_target_order"
                        envelope = "negative_target_order"
                    elif (
                        first_target < movie_start
                        or second_target > min(next_record_start, movie_end)
                    ):
                        span_length_key = "outside_candidate_record_gap"
                        envelope = "outside_candidate_record_gap"
                    else:
                        span = data[first_target:second_target]
                        span_length_key = str(len(span))
                        span_mod_counts = dual_summary["first_to_second_span_byte_length_mod_8_counts"]
                        span_mod_key = str(len(span) % 8)
                        span_mod_counts[span_mod_key] = span_mod_counts.get(span_mod_key, 0) + 1
                        start_mod_counts = dual_summary["first_target_mod_8_counts"]
                        start_mod_key = str(first_target % 8)
                        start_mod_counts[start_mod_key] = start_mod_counts.get(start_mod_key, 0) + 1
                        if not span:
                            envelope = "empty"
                        elif not any(span):
                            envelope = "zero_fill"
                        else:
                            envelope = _classify_kind4_payload(data, first_target, second_target)
                            if envelope == "unrecognized":
                                envelope = "opaque_nonzero"
                            dual_summary["_nonempty_span_sha256s"].add(
                                hashlib.sha256(span).hexdigest()
                            )
                span_length_counts = dual_summary["first_to_second_span_byte_length_counts"]
                span_length_counts[span_length_key] = span_length_counts.get(span_length_key, 0) + 1
                envelope_counts = dual_summary["span_envelope_counts"]
                envelope_counts[envelope] = envelope_counts.get(envelope, 0) + 1

    for kind_summaries in candidate_record_end_region_observations.values():
        for region_summary in kind_summaries.values():
            hashes = region_summary.pop("_region_sha256s")
            region_summary["distinct_non_sentinel_region_sha256_count"] = len(hashes)
            region_summary["all_non_sentinel_regions_8_byte_aligned"] = (
                region_summary["region_byte_length_mod_8_counts"] == {"0": region_summary["objects_checked"]}
                and region_summary["region_start_mod_8_counts"] == {"0": region_summary["objects_checked"]}
            )
    for kind_summaries in candidate_dual_pointer_observations.values():
        for dual_summary in kind_summaries.values():
            hashes = dual_summary.pop("_nonempty_span_sha256s")
            dual_summary["distinct_nonempty_span_sha256_count"] = len(hashes)
            dual_summary["all_valid_spans_8_byte_aligned"] = (
                bool(dual_summary["first_to_second_span_byte_length_mod_8_counts"])
                and dual_summary["first_to_second_span_byte_length_mod_8_counts"]
                == {"0": sum(dual_summary["first_to_second_span_byte_length_mod_8_counts"].values())}
                and dual_summary["first_target_mod_8_counts"]
                == {"0": sum(dual_summary["first_target_mod_8_counts"].values())}
            )
    object_directory_layout = {
        "object_count": len(all_targets),
        "pointer_targets_in_file_order": all_targets == ordered_targets,
        "known_record_layout_count": known_record_count,
        "all_records_have_known_layout": known_record_count == len(all_targets),
        "candidate_records_non_overlapping": (
            record_overlap_count == 0 if known_record_count == len(all_targets) else None
        ),
        "candidate_record_overlap_count": record_overlap_count,
    }
    text_pointer_offsets = Counter(
        text_object["string_offset_from_object"] for text_object in text_objects
    )
    text_string_pointer_summary = {
        "objects_checked": len(text_objects),
        "object_relative_target_offset_counts": {
            str(offset): count for offset, count in sorted(text_pointer_offsets.items())
        },
        "all_targets_at_104_byte_text_record_end": (
            bool(text_objects) and set(text_pointer_offsets) == {104}
        ),
    }
    distinct_command_start_offsets = set(command_start_offsets)
    command_layout_correspondence = {
        "object_pointer_count": len(object_start_kinds),
        "command_start_match_count": len(command_start_offsets),
        "distinct_object_starts_matched": len(distinct_command_start_offsets),
        "unmatched_object_start_count": len(object_start_kinds) - len(distinct_command_start_offsets),
        "duplicate_match_count": len(command_start_offsets) - len(distinct_command_start_offsets),
        "object_start_count_by_kind": {
            str(kind): kinds[kind] for kind in sorted(kinds)
        },
        "layout_match_count_by_kind_and_table_entry": kind_layout_counts,
        "consistent_record_layout_per_kind": not layout_definition_conflicts,
        "every_object_start_has_exactly_one_layout_command": (
            len(distinct_command_start_offsets) == len(object_start_kinds)
            and len(command_start_offsets) == len(object_start_kinds)
            and set(command_start_offsets) == set(object_start_kinds)
            and all(kind_layout_counts_by_kind[kind] == kinds[kind] for kind in kinds)
        ),
    }

    object_count = sum(kinds.values())
    if object_capacity and object_count > object_capacity:
        raise IggyFormatError(
            f"object table has {object_count} entries; header field 0x40 says {object_capacity}"
        )

    return {
        "schema": 1,
        "scope": "read-only metadata; object record layouts and bounded candidate regions are summarized without semantic decoding",
        "source_name": source_name,
        "source_sha256": hashlib.sha256(data).hexdigest(),
        "source_size": len(data),
        "version": version,
        "platform": platform,
        "subfiles": subfiles,
        "index_subfiles": index_subfiles,
        "index_stream_relationship": index_stream_relationship,
        "movie_subfile_index": movie_index,
        "movie_subfile_size": movie_size,
        "movie_header_unknown_0x40": object_capacity,
        "movie_header_relative_pointers": movie_header_pointers,
        "font_count": font_count,
        "object_pointer_count": object_count,
        "object_pointer_tables": {
            "primary_count": len(primary_targets),
            "additional_count": len(additional_targets),
            "additional_pointer_field_movie_offset": (
                after_primary_table - movie_start if imported_guid != 0 else None
            ),
            "additional_pointer_value": additional_pointer_value,
            "additional_table_movie_offset": (
                additional_table_offset - movie_start if additional_table_offset is not None else None
            ),
        },
        "imported_guid_header_value": imported_guid,
        "object_kind_counts": {str(kind): kinds[kind] for kind in sorted(kinds)},
        "object_index_correspondence": object_index_correspondence,
        "object_start_layout_correspondence": command_layout_correspondence,
        "object_start_layouts_by_kind": object_layouts_by_kind,
        "object_record_catalog": {
            "scope": "per-object offsets, candidate index layouts, and type-code-2 relative-field summaries; no raw payloads or decoded object semantics",
            "layout_definitions": [
                object_layout_definitions[key]
                for key in sorted(object_layout_definitions)
            ],
            "records": object_record_rows,
        },
        "object_directory_layout": object_directory_layout,
        "field_relative_target_observations": field_relative_target_observations,
        "candidate_field_target_payload_observations": candidate_field_target_payload_observations,
        "candidate_payload_format_observations": candidate_payload_format_observations,
        "candidate_record_end_region_observations": candidate_record_end_region_observations,
        "candidate_dual_pointer_observations": candidate_dual_pointer_observations,
        "kind_6_string_pointer_summary": text_string_pointer_summary,
        "text_objects": text_objects,
        "limits": [
            "Only kind-6 text contents are decoded for bounded metadata; kinds 1, 3, and 4 remain semantically unnamed, and candidate relative-field targets are not treated as proven display relationships.",
            "This report does not prove a modified Iggy stream can be loaded by the game.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("iggy_file", type=Path, help="Extracted 64-bit .iggy movie payload")
    parser.add_argument("--report", type=Path, help="Write JSON report to a new or existing path")
    args = parser.parse_args()
    try:
        report = inspect_iggy(args.iggy_file.read_bytes(), source_name=args.iggy_file.name)
    except (OSError, IggyFormatError) as error:
        parser.error(str(error))
    serialized = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(serialized, encoding="utf-8")
    print(serialized, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
