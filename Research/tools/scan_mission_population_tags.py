#!/usr/bin/env python3
"""Decode selected primitive population-related tags from fixed-build PAK assets.

This is a focused research parser for the cooked Update 38.2 assets. It reads
only local PAK records and stores primitive tag names/values plus byte offsets;
it is not a general Unreal package or Blueprint graph parser.
"""

from __future__ import annotations

import argparse
import json
import re
import struct
import sys
from pathlib import Path

from scan_gameplay_pak_assets import extract_record, load_u4pak, path_is_selected


DEFAULT_ASSETS = (
    "GameSystems/Character/PlayerDialogueSettings_BP.uasset",
    "GameSystems/Enclave/PopulationManagerBp.uasset",
    "GameSystems/Enclave/CommunityScreenManager.uasset",
    "GameSystems/Enclave/CommunityComponentBp.uasset",
    "GameSystems/Radio/CommandInstances/AccessLegacyPool/RecruitSurvivorFromLegacy.uasset",
    "GameSystems/Radio/RadioCommandDefinitions.uasset",
    "Community/Community_EndOfDay_MoraleRecruit.uasset",
    "Community/Threaten_To_Leave.uasset",
    "Community/Threaten_To_Leave_Trait.uasset",
    "LegacyArcs/Arc_Legacy_Builder.uasset",
    "LegacyArcs/Arc_Legacy_Builder_StandAlone.uasset",
    "LegacyArcs/Arc_Legacy_BuilderBP.uasset",
    "LegacyArcs/Arc_Legacy_Sheriff_Missions.uasset",
    "LegacyArcs/Arc_Legacy_Sheriff_StandAlone.uasset",
    "LegacyArcs/Arc_Legacy_SheriffBP.uasset",
    "LegacyArcs/Arc_Legacy_Trader.uasset",
    "LegacyArcs/Arc_Legacy_Trader_StandAlone.uasset",
    "LegacyArcs/Arc_Legacy_TraderBP.uasset",
    "LegacyArcs/Arc_Legacy_Warlord.uasset",
    "LegacyArcs/Arc_Legacy_Warlord_StandAlone.uasset",
    "RadioRoom/RadioRoom_Survivors.uasset",
    "MissionSettings.uasset",
)
MISSION_ASSET_PREFIXES = (
    "AmbientMissions", "Community", "DemoMissions", "EnclaveArcs", "EnclaveMissions",
    "ExtremeEnclaves", "FactionMissions", "HeartlandMissions", "LegacyArcs",
    "MissionEvents", "MissionObjectives", "Missions", "PersonalArcs", "RadioRoom",
    "StarterScenarioArcs", "Story", "TutorialMissions",
    "DLC2_DaybreakStorySettings", "DLC3_HardMode_StorySettings", "DemoStorySettings",
    "GreenZone_StorySettings", "HeartlandStorySettings", "MissionSettings",
    "SharedStorySettings", "EnclaveAssets", "MissionCastingCollectionInterface",
    "StoryDirectorAsset",
)
RELEVANT_PROPERTY = re.compile(
    r"(?i)(population|community.?members|character.?count|castcharactercount|recruit|cap)"
)


def read_fname_table(data: bytes):
    """Read the FName strings using the cooked UE4 header layout used here."""
    if len(data) < 32:
        raise ValueError("asset is too small for a UE4 package header")
    custom_version_count = struct.unpack_from("<i", data, 20)[0]
    if not 0 <= custom_version_count <= 1024:
        raise ValueError("invalid custom version count")
    position = 24 + custom_version_count * 20 + 4
    if position + 4 > len(data):
        raise ValueError("truncated package folder name")
    folder_length = struct.unpack_from("<i", data, position)[0]
    position += 4
    folder_bytes = folder_length if folder_length >= 0 else -folder_length * 2
    position += folder_bytes + 4
    if position + 8 > len(data):
        raise ValueError("truncated FName table header")
    count, offset = struct.unpack_from("<ii", data, position)
    if not 0 <= count <= 100_000 or not 0 <= offset < len(data):
        raise ValueError("invalid FName table bounds")

    names = []
    for _ in range(count):
        if offset + 4 > len(data):
            raise ValueError("truncated FName entry")
        size = struct.unpack_from("<i", data, offset)[0]
        offset += 4
        if size >= 0:
            end = offset + size
            if end > len(data):
                raise ValueError("truncated narrow FName")
            name = data[offset : max(offset, end - 1)].decode("utf-8", "replace")
            offset = end
        else:
            payload_size = (-size) * 2
            end = offset + payload_size
            name_end = end - 2
            if end > len(data):
                raise ValueError("truncated wide FName")
            name = data[offset:name_end].decode("utf-16le", "replace")
            offset = end
        if offset + 4 > len(data):
            raise ValueError("truncated FName hash")
        names.append(name)
        offset += 4
    return names, offset


def parse_primitive_tags(data: bytes, names: list[str], scan_start: int):
    def resolve_name(offset):
        if offset < 0 or offset + 8 > len(data):
            return None
        index, number = struct.unpack_from("<ii", data, offset)
        if 0 <= index < len(names) and 0 <= number < 100_000:
            return names[index]
        return None

    tags = []
    for offset in range(scan_start, len(data) - 40):
        name = resolve_name(offset)
        kind = resolve_name(offset + 8)
        if not name or kind not in ("IntProperty", "FloatProperty", "ByteProperty", "EnumProperty", "BoolProperty"):
            continue
        size, array_index = struct.unpack_from("<ii", data, offset + 16)
        if size < 0 or size > 16 or array_index < 0 or array_index > 500:
            continue
        value = None
        try:
            if kind == "FloatProperty" and size == 4:
                value = struct.unpack_from("<f", data, offset + 25)[0]
            elif kind == "IntProperty" and size == 4:
                value = struct.unpack_from("<i", data, offset + 25)[0]
            elif kind in ("ByteProperty", "EnumProperty") and size == 8:
                value = resolve_name(offset + 33)
            elif kind == "BoolProperty" and size == 0:
                value = bool(data[offset + 24])
        except struct.error:
            continue
        if value is not None:
            tags.append({"offset": hex(offset), "name": name, "type": kind, "value": value})
    return tags


def associate_member_conditions(tags):
    """Pair each CommunityMembers stat with nearby comparison/value tags."""
    result = []
    for index, tag in enumerate(tags):
        if tag["name"] != "ComparisonStat" or "CommunityMembers" not in str(tag["value"]):
            continue
        following = tags[index + 1 : index + 4]
        comparison = next((row["value"] for row in following if row["name"] == "Comparison"), None)
        value = next((row["value"] for row in following if row["name"] == "Value"), None)
        result.append(
            {
                "offset": tag["offset"],
                "stat": tag["value"],
                "comparison": comparison,
                "value": value,
                "complete_nearby_tag_sequence": comparison is not None and value is not None,
            }
        )
    return result


def scan(pak_root: Path, parser_path: Path, asset_paths=DEFAULT_ASSETS, include_all_mission_assets=False):
    u4pak = load_u4pak(parser_path)
    paks = sorted(pak_root.glob("*.pak"))
    if not paks:
        raise FileNotFoundError("no .pak files found in %s" % pak_root)
    wanted = {path.replace("/", "\\").casefold(): path for path in asset_paths}
    found = {}
    for pak_path in paks:
        with pak_path.open("rb") as stream:
            pak = u4pak.read_index(stream, force_version=3)
        for record in pak.records:
            normalized = record.filename.replace("/", "\\")
            key = normalized.casefold()
            if (
                include_all_mission_assets
                and normalized.lower().endswith(".uasset")
                and path_is_selected(normalized, MISSION_ASSET_PREFIXES)
            ):
                wanted.setdefault(key, normalized)
            if key in wanted:
                found[key] = (pak_path, record)

    output_assets = []
    errors = []
    for key, requested_path in wanted.items():
        pair = found.get(key)
        if pair is None:
            errors.append({"asset": requested_path, "error": "not found in installed PAK index"})
            continue
        pak_path, record = pair
        try:
            with pak_path.open("rb") as stream:
                data = extract_record(stream, record)
            names, start = read_fname_table(data)
            tags = parse_primitive_tags(data, names, start)
            relevant = [tag for tag in tags if RELEVANT_PROPERTY.search(tag["name"])]
            member_conditions = associate_member_conditions(tags)
            output_assets.append(
                {
                    "asset": requested_path.replace("\\", "/"),
                    "pak": pak_path.name,
                    "uncompressed_size": len(data),
                    "fname_count": len(names),
                    "primitive_tag_count": len(tags),
                    "community_member_conditions": member_conditions,
                    "relevant_tag_count": len(relevant),
                    "relevant_tags": relevant,
                }
            )
        except (OSError, ValueError, struct.error) as error:
            errors.append({"asset": requested_path, "error": str(error)})

    return {
        "schema": 1,
        "method": "offline partial FName/primitive-tag scan",
        "selection": {
            "mode": "all-campaign-and-mission-roots" if include_all_mission_assets else "curated-assets",
            "prefixes": list(MISSION_ASSET_PREFIXES) if include_all_mission_assets else [],
        },
        "limits": [
            "Not a full UE4 package parser; it does not decode UObject exports, Blueprint graph wiring, soft-object references or mission-node ownership.",
            "Each offset is relative to the uncompressed asset payload; a nearby stat/comparison/value sequence is not proof of which mission branch consumes it.",
            "Only primitive tags and CommunityMembers comparison sequences are retained; absent tags do not establish absent behavior.",
        ],
        "assets": sorted(output_assets, key=lambda row: row["asset"].casefold()),
        "errors": errors,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pak-root", required=True, type=Path)
    parser.add_argument("--u4pak-module", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--all-campaign-assets", action="store_true",
                        help="inspect primitive tags in every .uasset under mission/community/story roots")
    args = parser.parse_args(argv)
    parser_path = args.u4pak_module or Path(__file__).resolve().parents[3] / "u4pak" / "u4pak.py"
    try:
        report = scan(args.pak_root, parser_path, include_all_mission_assets=args.all_campaign_assets)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except (OSError, ImportError, ValueError, struct.error) as error:
        print("ERROR: %s" % error, file=sys.stderr)
        return 1
    found_conditions = sum(len(row["community_member_conditions"]) for row in report["assets"])
    print(
        "parsed %d/%d selected assets; %d CommunityMembers condition records; %d errors"
        % (len(report["assets"]), len(report["assets"]) + len(report["errors"]), found_conditions, len(report["errors"]))
    )
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
