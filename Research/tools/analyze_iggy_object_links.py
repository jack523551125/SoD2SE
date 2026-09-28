#!/usr/bin/env python3
"""Find aligned relative-i32 values in bounded Iggy side blocks that land on object starts."""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
from collections import Counter
from pathlib import Path
from typing import Any

from inspect_iggy_movie import IggyFormatError, inspect_iggy


PINNED_SAMPLES = {
    "settings": {
        "asset": "Art/UI/settings.uasset",
        "payload_sha256": "e69875cd5421f8082cf4e0b66e8a2cd09ba81f8455b08243635695ea0b4bdb57",
    },
    "character": {
        "asset": "Art/UI/character.uasset",
        "payload_sha256": "d134758ed784ac6beb64cc8494acc315b1f30591541fecaacdf3532109fb188d",
    },
    "pause": {
        "asset": "Art/UI/pause.uasset",
        "payload_sha256": "0f8607960fceedee1aa594fa699dc7eb7557b574f1e290b18a72440fa5e6ba33",
    },
}


def scan_relative_object_targets(
    block: bytes,
    *,
    block_start_movie_offset: int,
    source_record: dict[str, Any],
    block_role: str,
    records_by_offset: dict[int, dict[str, Any]],
) -> tuple[list[dict[str, Any]], Counter[int]]:
    """Return only 8-byte-aligned signed-i32 candidates resolving to object starts."""
    edges: list[dict[str, Any]] = []
    unaligned_hits: Counter[int] = Counter()
    for local_offset in range(0, len(block) - 3, 4):
        relative_i32 = struct.unpack_from("<i", block, local_offset)[0]
        target_offset = block_start_movie_offset + local_offset + relative_i32
        target_record = records_by_offset.get(target_offset)
        if target_record is None:
            continue
        if (
            local_offset % 8 != 0
            or relative_i32 % 8 != 0
            or target_offset % 8 != 0
        ):
            unaligned_hits[local_offset % 8] += 1
            continue
        edges.append(
            {
                "block_role": block_role,
                "source_object_index": source_record["object_index"],
                "source_movie_offset": source_record["movie_offset"],
                "source_kind": source_record["kind"],
                "block_start_movie_offset": block_start_movie_offset,
                "field_offset_from_block": local_offset,
                "relative_i32": relative_i32,
                "target_object_index": target_record["object_index"],
                "target_movie_offset": target_offset,
                "target_kind": target_record["kind"],
                "target_index_delta": target_record["object_index"] - source_record["object_index"],
            }
        )
    return edges, unaligned_hits


def analyze_asset(sample: str, path: Path) -> dict[str, Any]:
    spec = PINNED_SAMPLES[sample]
    payload = path.read_bytes()
    payload_sha256 = hashlib.sha256(payload).hexdigest()
    if payload_sha256 != spec["payload_sha256"]:
        raise ValueError(
            f"{sample} Iggy payload hash mismatch: expected {spec['payload_sha256']}, got {payload_sha256}"
        )
    report = inspect_iggy(payload, source_name=spec["asset"])
    movie_subfile = next(row for row in report["subfiles"] if row["kind"] == 1)
    movie_start = movie_subfile["offset"]
    movie = payload[movie_start : movie_start + movie_subfile["size"]]
    records = report["object_record_catalog"]["records"]
    records_by_offset = {row["movie_offset"]: row for row in records}
    edges: list[dict[str, Any]] = []
    analyzed_blocks = Counter()
    linked_blocks = Counter()
    unaligned_hits = Counter()

    for row in records:
        fields = {field["local_offset"]: field for field in row["relative_fields"]}
        if row["kind"] == 1 and 72 in fields:
            start = fields[72]["target_movie_offset"]
            end = row["next_object_movie_offset"]
            role = "kind1_record_end_region"
        elif row["kind"] == 3 and 56 in fields and 64 in fields:
            start = fields[56]["target_movie_offset"]
            end = fields[64]["target_movie_offset"]
            role = "kind3_dual_pointer_span"
        else:
            continue
        if start is None or end is None or end < start or end > len(movie):
            continue
        analyzed_blocks[role] += 1
        block_edges, block_unaligned = scan_relative_object_targets(
            movie[start:end],
            block_start_movie_offset=start,
            source_record=row,
            block_role=role,
            records_by_offset=records_by_offset,
        )
        if block_edges:
            linked_blocks[role] += 1
        edges.extend(block_edges)
        unaligned_hits.update(block_unaligned)

    by_role = {}
    for role in sorted(analyzed_blocks):
        role_edges = [edge for edge in edges if edge["block_role"] == role]
        by_role[role] = {
            "blocks_analyzed": analyzed_blocks[role],
            "blocks_with_aligned_object_targets": linked_blocks[role],
            "aligned_candidate_target_count": len(role_edges),
            "target_kind_counts": dict(sorted(Counter(str(edge["target_kind"]) for edge in role_edges).items())),
            "field_offset_from_block_counts": dict(sorted(Counter(str(edge["field_offset_from_block"]) for edge in role_edges).items(), key=lambda pair: int(pair[0]))),
            "target_index_delta_counts": dict(sorted(Counter(str(edge["target_index_delta"]) for edge in role_edges).items(), key=lambda pair: int(pair[0]))),
            "direction_counts": {
                "backward": sum(edge["target_index_delta"] < 0 for edge in role_edges),
                "self": sum(edge["target_index_delta"] == 0 for edge in role_edges),
                "forward": sum(edge["target_index_delta"] > 0 for edge in role_edges),
            },
        }
    return {
        "asset": spec["asset"],
        "payload_sha256": payload_sha256,
        "object_count": len(records),
        "aligned_candidate_links": len(edges),
        "unaligned_exact_object_start_hits_by_field_residue": {
            str(key): value for key, value in sorted(unaligned_hits.items())
        },
        "by_block_role": by_role,
        "edges": edges,
    }


def build_report(sample_paths: dict[str, Path]) -> dict[str, Any]:
    if set(sample_paths) != set(PINNED_SAMPLES):
        raise ValueError("settings, character, and pause samples are all required")
    return {
        "schema": 1,
        "target_build": 16535856,
        "method": "Scan 4-byte words in bounded kind-1/kind-3 side blocks as signed-i32, resolve field-relative targets against the same movie's object starts, and retain only hits where field offset, displacement, and target are all 8-byte aligned.",
        "scope_limitations": [
            "These are candidate object-start links; static byte matches do not prove the runtime field's semantic role or a parent-child relation.",
            "Kind-1 regions end at the next object start and are not proven to be fully owned by the preceding record.",
            "Kind-3 spans are bounded by the paired 0x38/0x40 targets but their internal schema is unknown.",
            "No original object bytes, text, or image data are stored.",
        ],
        "assets": [analyze_asset(sample, sample_paths[sample]) for sample in PINNED_SAMPLES],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--settings", required=True, type=Path)
    parser.add_argument("--character", required=True, type=Path)
    parser.add_argument("--pause", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        report = build_report(
            {"settings": args.settings, "character": args.character, "pause": args.pause}
        )
    except (OSError, ValueError, IggyFormatError) as error:
        parser.error(str(error))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"PASS: indexed {sum(asset['aligned_candidate_links'] for asset in report['assets'])} aligned candidate links"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
