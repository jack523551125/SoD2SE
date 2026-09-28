#!/usr/bin/env python3
"""Export a privacy-bounded per-object index for the pinned SoD2 Iggy samples."""
from __future__ import annotations

import argparse
import hashlib
import json
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


def project_asset(sample: str, path: Path) -> dict[str, Any]:
    spec = PINNED_SAMPLES[sample]
    payload = path.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    if digest != spec["payload_sha256"]:
        raise ValueError(
            f"{sample} Iggy payload hash mismatch: expected {spec['payload_sha256']}, got {digest}"
        )
    report = inspect_iggy(payload, source_name=spec["asset"])
    return {
        "asset": spec["asset"],
        "payload_sha256": digest,
        "payload_size": len(payload),
        "movie_subfile_size": report["movie_subfile_size"],
        "object_count": report["object_pointer_count"],
        "object_kind_counts": report["object_kind_counts"],
        "layout_definitions": report["object_record_catalog"]["layout_definitions"],
        "records": report["object_record_catalog"]["records"],
    }


def build_catalog(sample_paths: dict[str, Path]) -> dict[str, Any]:
    if set(sample_paths) != set(PINNED_SAMPLES):
        raise ValueError("settings, character, and pause samples are all required")
    assets = [project_asset(name, sample_paths[name]) for name in PINNED_SAMPLES]
    return {
        "schema": 1,
        "target_build": 16535856,
        "scope": "Per-object offsets, candidate index layouts, and type-code-2 relative-field summaries only.",
        "output_policy": "Does not retain original text, image payloads, or object bytes.",
        "limitations": [
            "Kinds 1, 3, and 4 are structurally indexed but are not semantically decoded.",
            "Relative targets are byte-offset observations, not proven display-tree or event references.",
            "Catalog completeness is limited to these three pinned movies and does not prove game loading behavior.",
        ],
        "assets": assets,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--settings", required=True, type=Path, help="Pinned settings .iggy payload")
    parser.add_argument("--character", required=True, type=Path, help="Pinned character .iggy payload")
    parser.add_argument("--pause", required=True, type=Path, help="Pinned pause .iggy payload")
    parser.add_argument("--output", required=True, type=Path, help="JSON output path")
    args = parser.parse_args()
    try:
        catalog = build_catalog(
            {"settings": args.settings, "character": args.character, "pause": args.pause}
        )
    except (OSError, ValueError, IggyFormatError) as error:
        parser.error(str(error))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"PASS: wrote {sum(asset['object_count'] for asset in catalog['assets'])} "+
        f"metadata-only object rows to {args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
