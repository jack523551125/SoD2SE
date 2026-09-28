#!/usr/bin/env python3
"""Offline, fixed-build probe of the cooked vanilla settings page.

The modified uasset lives only in a temporary directory. This does not produce
an installable asset or claim that the game will load or display it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path

from scan_gameplay_pak_assets import extract_record, load_u4pak


ASSET = "Art/UI/settings.uasset"
EXPECTED_SHA256 = "d8d320363be69ea9dfb39b5c20c8de5237c642841fe3ac86b00f8115050fe06e"
OLD = b"Aim Assist\0"
NEW = b"Mod Config\0"
EXPECTED_TEXT_PATHS = {
    "/0/Properties/TextTable/0/Text/SourceString",
    "/0/Properties/TextTable/0/Text/LocalizedString",
}


def patch_equal_length(data: bytes, old: bytes = OLD, new: bytes = NEW) -> tuple[bytes, list[int]]:
    if len(old) != len(new) or not old.endswith(b"\0") or not new.endswith(b"\0"):
        raise ValueError("Only equal-length, NUL-terminated text probes are supported")
    if data.count(old) != 1:
        raise ValueError("Expected exactly one source-text occurrence")
    result = data.replace(old, new, 1)
    changed = [index for index, (a, b) in enumerate(zip(data, result)) if a != b]
    if len(data) != len(result) or not changed:
        raise AssertionError("Unexpected patch length or empty patch")
    return result, changed


def structural_differences(left, right, path=""):
    if type(left) is not type(right):
        return [path]
    if isinstance(left, dict):
        if left.keys() != right.keys():
            return [path + "/keys"]
        result = []
        for key in left:
            result.extend(structural_differences(left[key], right[key], path + "/" + key))
        return result
    if isinstance(left, list):
        if len(left) != len(right):
            return [path + "/length"]
        result = []
        for index, (a, b) in enumerate(zip(left, right)):
            result.extend(structural_differences(a, b, path + "/" + str(index)))
        return result
    return [path] if left != right else []


def read_asset(pak_root: Path, parser_path: Path, asset_name: str = ASSET) -> tuple[bytes, str]:
    parser = load_u4pak(parser_path)
    matches = []
    for pak_path in sorted(pak_root.glob("*.pak")):
        with pak_path.open("rb") as stream:
            for record in parser.read_index(stream, force_version=3).records:
                if record.filename.replace("\\", "/").casefold() == asset_name.casefold():
                    matches.append((pak_path, record))
    if len(matches) != 1:
        raise ValueError("Expected one %s in PAK set; found %d" % (asset_name, len(matches)))
    pak_path, record = matches[0]
    with pak_path.open("rb") as stream:
        return extract_record(stream, record), pak_path.name


def export_asset(exporter: Path, asset_root: Path, output: Path, asset_list: Path) -> dict:
    command = [str(exporter), str(asset_root), "UE4_13", str(asset_list), str(output), "--quiet"]
    completed = subprocess.run(command, capture_output=True, text=True, timeout=120)
    if completed.returncode:
        raise RuntimeError("Independent UAsset parser failed: " + (completed.stderr + completed.stdout)[-1000:])
    result = output / "Art" / "UI" / "settings.json"
    if not result.is_file():
        raise RuntimeError("Independent parser emitted no settings.json")
    return json.loads(result.read_text(encoding="utf-8-sig"))


def normalize_export(data: dict) -> dict:
    # The parser derives this path from its temporary input root, not the asset bytes.
    copy = json.loads(json.dumps(data))
    copy[0]["Package"] = "Art/UI/settings"
    return copy


def probe(pak_root: Path, parser_path: Path, exporter: Path, reference_export: Path) -> dict:
    original, pak_name = read_asset(pak_root, parser_path)
    if hashlib.sha256(original).hexdigest() != EXPECTED_SHA256:
        raise ValueError("settings.uasset does not match fixed build 16535856")
    patched, changed = patch_equal_length(original)
    with tempfile.TemporaryDirectory(prefix="sod2-settings-asset-probe-") as directory:
        root = Path(directory)
        asset = root / "StateOfDecay2" / "Content" / ASSET
        asset.parent.mkdir(parents=True)
        asset_list = root / "assets.txt"
        asset_list.write_text(ASSET + "\n", encoding="ascii")
        asset.write_bytes(original)
        baseline = normalize_export(export_asset(exporter, root / "StateOfDecay2" / "Content", root / "baseline", asset_list))
        asset.write_bytes(patched)
        modified = normalize_export(export_asset(exporter, root / "StateOfDecay2" / "Content", root / "modified", asset_list))
    reference = normalize_export(json.loads(reference_export.read_text(encoding="utf-8-sig")))
    baseline_diff = structural_differences(reference, baseline)
    patch_diff = structural_differences(baseline, modified)
    if baseline_diff:
        raise AssertionError("No-op reparse differs from reference: " + repr(baseline_diff[:8]))
    if set(patch_diff) != EXPECTED_TEXT_PATHS:
        raise AssertionError("Patch changed unexpected export fields: " + repr(patch_diff[:8]))
    row = modified[0]["Properties"]["TextTable"][0]
    if row["Id"] != "ID_ACCESSIBILITY_AIM_ASSIST" or row["Text"]["SourceString"] != "Mod Config":
        raise AssertionError("Patched text row identity/value mismatch")
    return {
        "schema": 1,
        "scope": "offline text-only proof; no in-game load or navigation claim",
        "source_pak": pak_name,
        "asset": ASSET,
        "source_sha256": hashlib.sha256(original).hexdigest(),
        "source_size": len(original),
        "no_op_reparse_matches_reference": True,
        "changed_byte_count": len(changed),
        "changed_byte_span": [min(changed), max(changed)],
        "patched_reparse_succeeded": True,
        "changed_export_paths": sorted(patch_diff),
        "text_table_rows": len(baseline[0]["Properties"]["TextTable"]),
        "api_function_count": len(baseline[0]["Properties"]["ApiFunctions"]),
        "limits": [
            "Equal-length FText source substitution only; it does not add an Iggy control.",
            "A cooked asset parsed by CUE4Parse is not proof of game load, localization precedence, focus or input behavior.",
            "No edited game asset is retained or distributed by this tool.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pak-root", type=Path, required=True)
    parser.add_argument("--u4pak-module", type=Path, required=True)
    parser.add_argument("--exporter", type=Path, required=True)
    parser.add_argument("--reference-export", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    report = probe(args.pak_root, args.u4pak_module, args.exporter, args.reference_export)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("PASS: no-op and targeted text asset reparses; no game asset retained")


if __name__ == "__main__":
    main()
