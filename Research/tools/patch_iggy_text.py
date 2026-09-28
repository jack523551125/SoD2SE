#!/usr/bin/env python3
"""Apply one same-size text edit to the pinned SoD2 settings Iggy payload."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from inspect_iggy_movie import IggyFormatError, inspect_iggy


PINNED_SETTINGS_IGGY_SHA256 = "e69875cd5421f8082cf4e0b66e8a2cd09ba81f8455b08243635695ea0b4bdb57"
SHA256_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")
UNCHANGED_REPORT_FIELDS = (
    "version",
    "platform",
    "subfiles",
    "index_subfiles",
    "index_stream_relationship",
    "movie_subfile_index",
    "movie_subfile_size",
    "object_pointer_count",
    "object_pointer_tables",
    "imported_guid_header_value",
    "object_kind_counts",
    "object_index_correspondence",
    "object_start_layout_correspondence",
    "object_start_layouts_by_kind",
    "object_directory_layout",
    "field_relative_target_observations",
    "candidate_field_target_payload_observations",
    "candidate_payload_format_observations",
    "kind_6_string_pointer_summary",
)


def patch_iggy_text(
    data: bytes,
    *,
    text_index: int,
    expected_source_sha256: str,
    expected_text_sha256: str,
    replacement: str,
) -> tuple[bytes, dict[str, Any]]:
    """Patch one UTF-16 string while preserving the entire Iggy payload layout."""
    if not 0 <= text_index <= 0xFFFF:
        raise ValueError("text_index must fit the Iggy 16-bit text index")
    if not SHA256_PATTERN.fullmatch(expected_source_sha256):
        raise ValueError("expected source SHA-256 must contain exactly 64 hex digits")
    if not SHA256_PATTERN.fullmatch(expected_text_sha256):
        raise ValueError("expected text SHA-256 must contain exactly 64 hex digits")
    actual_source_sha256 = hashlib.sha256(data).hexdigest()
    if actual_source_sha256.casefold() != expected_source_sha256.casefold():
        raise IggyFormatError("input payload SHA-256 does not match the caller-pinned source")
    if "\0" in replacement:
        raise ValueError("replacement text cannot contain a UTF-16 terminator")
    replacement_bytes = replacement.encode("utf-16le", errors="strict")

    before = inspect_iggy(data, source_name="pinned-settings.iggy")
    matches = [row for row in before["text_objects"] if row["text_index"] == text_index]
    if len(matches) != 1:
        raise IggyFormatError(
            f"expected exactly one text object with index {text_index}, found {len(matches)}"
        )
    target = matches[0]
    if target["text_sha256"].casefold() != expected_text_sha256.casefold():
        raise IggyFormatError("selected text SHA-256 does not match the expected original text")
    old_byte_length = target["utf16_code_units"] * 2
    if len(replacement_bytes) != old_byte_length:
        raise IggyFormatError(
            "replacement must have the same UTF-16 code-unit count as the original text"
        )
    movie_index = before["movie_subfile_index"]
    if not 0 <= movie_index < len(before["subfiles"]):
        raise IggyFormatError("parsed movie subfile index is outside the subfile table")
    movie_subfile = before["subfiles"][movie_index]
    movie_start = movie_subfile["offset"]
    movie_end = movie_start + before["movie_subfile_size"]
    string_offset = movie_start + target["stream_offset"] + target["string_offset_from_object"]
    terminator_offset = string_offset + old_byte_length
    if (
        string_offset < movie_start
        or terminator_offset + 2 > movie_end
        or data[terminator_offset : terminator_offset + 2] != b"\0\0"
    ):
        raise IggyFormatError("selected string or its UTF-16 terminator lies outside the payload")
    old_bytes = data[string_offset:terminator_offset]
    if replacement_bytes == old_bytes:
        raise IggyFormatError("replacement is identical to the selected original text")
    try:
        old_text = old_bytes.decode("utf-16le", errors="strict")
    except UnicodeDecodeError as error:
        raise IggyFormatError("selected text bytes are not valid UTF-16LE") from error
    if hashlib.sha256(old_text.encode("utf-8")).hexdigest() != target["text_sha256"]:
        raise IggyFormatError("selected text bytes do not match the parsed text digest")

    output = bytearray(data)
    output[string_offset:terminator_offset] = replacement_bytes
    patched = bytes(output)
    expected_bytes = bytearray(data)
    expected_bytes[string_offset:terminator_offset] = replacement_bytes
    if patched != bytes(expected_bytes):
        raise IggyFormatError("in-place text patch changed bytes outside the selected string")

    after = inspect_iggy(patched, source_name="patched-settings.iggy")
    for key in UNCHANGED_REPORT_FIELDS:
        if before.get(key) != after.get(key):
            raise IggyFormatError(f"text patch changed structural report field {key}")
    before_texts = {row["text_index"]: row for row in before["text_objects"]}
    after_texts = {row["text_index"]: row for row in after["text_objects"]}
    if before_texts.keys() != after_texts.keys():
        raise IggyFormatError("text patch changed the set of text objects")
    for index, old_row in before_texts.items():
        new_row = after_texts[index]
        if index == text_index:
            expected_row = dict(old_row)
            expected_row["text_sha256"] = hashlib.sha256(
                replacement.encode("utf-8")
            ).hexdigest()
            if new_row != expected_row:
                raise IggyFormatError("selected text object changed outside its text digest")
        elif new_row != old_row:
            raise IggyFormatError(f"unselected text object {index} changed")

    return patched, {
        "input_sha256": actual_source_sha256,
        "output_sha256": hashlib.sha256(patched).hexdigest(),
        "text_index": text_index,
        "expected_original_text_sha256": target["text_sha256"],
        "replacement_text_sha256": hashlib.sha256(replacement.encode("utf-8")).hexdigest(),
        "string_payload_offset": string_offset,
        "utf16_code_units": target["utf16_code_units"],
        "patched_span_byte_count": old_byte_length,
        "changed_byte_count": sum(old != new for old, new in zip(old_bytes, replacement_bytes)),
        "all_other_bytes_and_layouts_preserved": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_iggy", type=Path)
    parser.add_argument("output_iggy", type=Path)
    parser.add_argument("text_index", type=int)
    parser.add_argument("expected_text_sha256")
    parser.add_argument("replacement")
    args = parser.parse_args()
    input_path = args.input_iggy.resolve()
    output_path = args.output_iggy.resolve()
    if input_path == output_path:
        parser.error("input and output paths must be different")
    if output_path.exists():
        parser.error("output path already exists; choose a new path")
    if not input_path.is_file():
        parser.error("input file does not exist")
    try:
        result, summary = patch_iggy_text(
            input_path.read_bytes(),
            text_index=args.text_index,
            expected_source_sha256=PINNED_SETTINGS_IGGY_SHA256,
            expected_text_sha256=args.expected_text_sha256,
            replacement=args.replacement,
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(result)
    except (OSError, ValueError, IggyFormatError) as error:
        parser.error(str(error))
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    print("Output contains a local static-analysis edit; it is not an installable Mod.")
    print("Output: " + str(output_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
