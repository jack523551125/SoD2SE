#!/usr/bin/env python3
"""Summarize fixed-build Character/Community/HUD Iggy APIs without retaining source."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from analyze_iggy_script_api import extract_abc_block
from inspect_iggy_movie import inspect_iggy


PINNED_MOVIES = {
    "character": {
        "asset": "Art/UI/character.uasset",
        "uasset_sha256": "941e57905b698214e7e962a613e486ef512eaa0a48ba09f40abbf1522f58cd70",
        "iggy_sha256": "d134758ed784ac6beb64cc8494acc315b1f30591541fecaacdf3532109fb188d",
        "abc_sha256": "143f089353e5ed0504db2dd8d2c59eb318c037228275dd203ce5486b4c421800",
        "root_class": "character",
        "source_files": {
            "root": "character.as",
            "traits": "traits_behavior.as",
            "skills": "skills_tab.as",
        },
        "required_api": {
            "ApiSkillsAddTraitName",
            "ApiSkillsAddTrait",
            "ApiSkillsAddTraitEffect",
            "ApiSkillsBeginAddTrait",
            "ApiSkillsEndAddTrait",
        },
    },
    "community": {
        "asset": "Art/UI/community.uasset",
        "uasset_sha256": "9e4454e8ddfd417a83c1995e48eaaed4a114e5e95808039f2decbb0342bec001",
        "iggy_sha256": "44a7fdaa81928addcdb5d052ca77043db4966f6fe79b95aa3027ad5b1cea5584",
        "abc_sha256": "eb62171b84bc1deb5b45ce723e1668fd5d85023357d92e24ebb5915b732484aa",
        "root_class": "community",
        "source_files": {
            "root": "community.as",
            "characters": "character_info/CharacterInfo.as",
            "overhead": "character_info/container_overhead_info.as",
        },
        "required_api": {
            "ApiAddOrUpdateCharacterStatus",
            "ApiClearCharacterStatus",
            "ApiSetActionText",
            "ApiClearActionText",
            "ApiSetUnavailableText",
            "ApiClearUnavailableText",
            "ApiSetOveheadIcons",
            "ApiSetSelectedCharacter",
            "ApiShowCharacterOverlays",
            "ApiHideCharacterOverlays",
        },
    },
    "hud": {
        "asset": "Art/UI/hud.uasset",
        "uasset_sha256": "9875c79a3afd5c0cd5ef4c9c5df91e55e5f069cb0ab97d9ce161a59fbf80b5cc",
        "iggy_sha256": "00da0e3e3ccabb57508f42744ad8b333ebc81be6da9b0cfedc5966ce264d2eae",
        "abc_sha256": "d13f771fb546d8d9f3f3262cd19c06ba7b0d3ff234760276d4d8d8858edb2751",
        "root_class": "hud",
        "source_files": {
            "root": "hud.as",
            "notification": "notification.as",
            "effects": "effects/container_effects.as",
            "effect_bubble": "effects/container_effect_bubble.as",
        },
        "required_api": {
            "ApiNotification",
            "ApiAddMiscEffect",
            "ApiUpdateMiscEffectState",
            "ApiRemoveMiscEffect",
            "ApiSetStats",
            "ApiMissionNewMission",
            "ApiMissionNewObjective",
            "ApiSearchSetProgress",
        },
    },
    "map": {
        "asset": "Art/UI/map.uasset",
        "uasset_sha256": "f91806d92ea18b12440bb0117d012fb20d3f9ab472c2841ab95d858083319945",
        "iggy_sha256": "706d317873a3ac91a0b1f338f568b4d2e63134fdd751104ca05f56b5600f0951",
        "abc_sha256": "92c057dda613057de6c84aeb05fce28e4e6faaf6a05680f40151e10c3740c9ca",
        "root_class": "map",
        "source_files": {
            "root": "map.as",
            "mission_layer": "info_layer/MissionLayer.as",
        },
        "required_api": {
            "ApiAddOrUpdateMission",
            "ApiAddOrUpdateObjective",
            "ApiAddOrUpdateObjectiveLocation",
            "ApiRemoveObjectiveLocation",
            "ApiRemoveMission",
            "ApiRemoveObjective",
        },
    },
}
FFDEC_VERSION = "v.26.3.0"
PUBLIC_FUNCTION = re.compile(
    r"(?m)^\s*public\s+function\s+([A-Za-z_$][\w$]*)\s*\(([^)]*)\)\s*(?::\s*([^\s{]+))?"
)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def extract_chained_abc_blocks(
    payload: bytes,
    *,
    section_offset: int,
    section_end: int,
    expected_block_count: int | None = None,
    maximum_blocks: int = 4096,
) -> tuple[list[bytes], dict[str, Any]]:
    """Extract a bounded Iggy declaration section containing step-linked ABCs.

    In the pinned Map movie each record is ``<Q step><I abc_length><ABC>``.
    Non-terminal steps point to the next record. A step value of one marks the
    final ABC, after which this build has a four-byte zero pad. The parser does
    not trust the sentinel as a byte count and refuses truncated or cyclic data.
    """
    if section_offset < 0 or section_end > len(payload) or section_offset >= section_end:
        raise ValueError("Chained ABC section is outside the input bounds")
    if maximum_blocks <= 0:
        raise ValueError("maximum_blocks must be positive")

    cursor = section_offset
    blocks: list[bytes] = []
    records: list[dict[str, int]] = []
    terminal_end: int | None = None
    for _ in range(maximum_blocks):
        if cursor + 12 > section_end:
            raise ValueError("Chained ABC section ended before its terminal record")
        step = struct.unpack_from("<Q", payload, cursor)[0]
        abc_length = struct.unpack_from("<I", payload, cursor + 8)[0]
        abc_start = cursor + 12
        abc_end = abc_start + abc_length
        if abc_length < 4 or abc_end > section_end:
            raise ValueError("Chained ABC payload escapes its declared section bounds")
        abc = payload[abc_start:abc_end]
        minor, major = struct.unpack_from("<HH", abc)
        if (minor, major) != (16, 46):
            raise ValueError(f"Unexpected chained AVM2 ABC version: {major}.{minor}")

        blocks.append(abc)
        records.append({
            "record_offset": cursor,
            "step": step,
            "abc_offset": abc_start,
            "abc_length": abc_length,
            "abc_end": abc_end,
        })
        if step == 1:
            terminal_end = abc_end
            break
        minimum_step = 12 + abc_length
        next_cursor = cursor + step
        if step < minimum_step:
            raise ValueError("Chained ABC step overlaps its own ABC payload")
        if next_cursor <= cursor or next_cursor > section_end:
            raise ValueError("Chained ABC step points outside its containing section")
        cursor = next_cursor
    else:
        raise ValueError("Chained ABC section exceeds the block safety limit")

    if terminal_end is None:
        raise ValueError("Chained ABC section has no terminal record")
    if expected_block_count is not None and len(blocks) != expected_block_count:
        raise ValueError(
            f"Chained ABC block count mismatch: expected {expected_block_count}, got {len(blocks)}"
        )
    trailer = payload[terminal_end:section_end]
    return blocks, {
        "section_offset": section_offset,
        "section_end": section_end,
        "block_count": len(blocks),
        "abc_total_length": sum(map(len, blocks)),
        "concatenated_abc_sha256": _sha256(b"".join(blocks)),
        "terminal_record_offset": records[-1]["record_offset"],
        "trailing_padding_length": len(trailer),
        "trailing_padding_sha256": _sha256(trailer),
        "trailing_padding_all_zero": not any(trailer),
        "first_record_step": records[0]["step"],
        "last_record_step": records[-1]["step"],
    }


def make_swf_wrapper_for_abc_blocks(blocks: list[bytes]) -> bytes:
    """Wrap each ABC block in its own DoABC tag for a metadata-only FFDec pass."""
    if not blocks:
        raise ValueError("At least one ABC block is required")
    rect = bytes.fromhex("08 00")
    file_attributes_body = struct.pack("<I", 0x08)
    file_attributes = struct.pack("<H", (69 << 6) | len(file_attributes_body)) + file_attributes_body
    tags = bytearray()
    for abc in blocks:
        if len(abc) < 4 or struct.unpack_from("<HH", abc) != (16, 46):
            raise ValueError("SWF wrapper received a malformed or unsupported ABC block")
        tag_body = struct.pack("<I", 0) + b"\0" + abc
        tags.extend(struct.pack("<H", (82 << 6) | 63))
        tags.extend(struct.pack("<I", len(tag_body)))
        tags.extend(tag_body)
    body = rect + struct.pack("<HH", 0x1800, 1) + file_attributes + bytes(tags) + struct.pack("<H", 0)
    return b"FWS" + bytes([10]) + struct.pack("<I", 8 + len(body)) + body


def _export_scripts(abc: bytes, ffdec_cli: Path, destination: Path) -> Path:
    return _export_script_blocks([abc], ffdec_cli, destination)


def _export_script_blocks(blocks: list[bytes], ffdec_cli: Path, destination: Path) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    version = subprocess.run(
        [str(ffdec_cli), "-help"], capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    if version.returncode != 0 or FFDEC_VERSION not in version.stdout + version.stderr:
        raise ValueError(f"Expected FFDec {FFDEC_VERSION}")
    wrapper = destination / "movie-abc.swf"
    export_dir = destination / "export"
    wrapper.write_bytes(make_swf_wrapper_for_abc_blocks(blocks))
    result = subprocess.run(
        [str(ffdec_cli), "-export", "script", str(export_dir), str(wrapper)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    output = result.stdout + result.stderr
    if result.returncode != 0 or "Export finished." not in output:
        raise ValueError("FFDec failed to export pinned Iggy ABC: " + output[-1000:])
    return export_dir / "scripts"


def _read_script(scripts: Path, relative: str) -> str:
    candidates = [path for path in scripts.rglob("*.as") if path.relative_to(scripts).as_posix().lower() == relative.lower()]
    if len(candidates) != 1:
        raise ValueError(f"Expected one decompiled script {relative}, found {len(candidates)}")
    return candidates[0].read_text(encoding="utf-8", errors="strict")


def _public_methods(source: str) -> dict[str, dict[str, Any]]:
    methods: dict[str, dict[str, Any]] = {}
    for match in PUBLIC_FUNCTION.finditer(source):
        name, parameters, return_type = match.groups()
        arity = len([parameter for parameter in parameters.split(",") if parameter.strip()])
        methods[name] = {"parameter_count": arity, "return_type": return_type or None}
    return methods


def _extract_function_body(source: str, name: str) -> str:
    match = re.search(
        rf"(?m)^\s*public\s+function\s+{re.escape(name)}\s*\([^)]*\)[^{{]*\{{",
        source,
    )
    if not match:
        raise ValueError(f"Could not locate public ActionScript method {name}")
    opening = source.find("{", match.start(), match.end())
    depth = 0
    quote: str | None = None
    escaped = False
    line_comment = False
    block_comment = False
    index = opening
    while index < len(source):
        char = source[index]
        next_char = source[index + 1] if index + 1 < len(source) else ""
        if line_comment:
            if char in "\r\n":
                line_comment = False
        elif block_comment:
            if char == "*" and next_char == "/":
                block_comment = False
                index += 1
        elif quote is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
        elif char == "/" and next_char == "/":
            line_comment = True
            index += 1
        elif char == "/" and next_char == "*":
            block_comment = True
            index += 1
        elif char in "\"'":
            quote = char
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[opening + 1:index]
        index += 1
    raise ValueError(f"ActionScript method {name} has an unterminated body")


def _analyze_hud_extension(
    root_source: str,
    notification_source: str,
    effects_source: str,
    effect_bubble_source: str,
    root_methods: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    required_arities = {
        "ApiNotification": 3,
        "ApiAddMiscEffect": 4,
        "ApiUpdateMiscEffectState": 2,
        "ApiRemoveMiscEffect": 2,
        "ApiSetStats": 6,
        "ApiMissionNewMission": 6,
        "ApiMissionNewObjective": 5,
        "ApiSearchSetProgress": 2,
    }
    if any(root_methods.get(name, {}).get("parameter_count") != arity for name, arity in required_arities.items()):
        raise ValueError("HUD root API signatures do not match the pinned adapter contract")

    compact_root = re.sub(r"\s+", "", root_source)
    compact_notification = re.sub(r"\s+", "", notification_source)
    compact_effects = re.sub(r"\s+", "", effects_source)
    compact_bubble = re.sub(r"\s+", "", effect_bubble_source)
    required_forwarders = (
        "this.menu_notification.Notify(icon,header,message);",
        "this.menu_effects.container_effects.AddMiscEffect(ID,iconName,iconState,doTransitions);",
        "this.menu_effects.container_effects.UpdateMiscEffectState(ID,iconState);",
        "this.menu_effects.container_effects.RemoveMiscEffect(ID,doTransitions);",
    )
    if not all(token in compact_root for token in required_forwarders):
        raise ValueError("HUD public notification/effect API no longer forwards to the expected native movie components")
    notification_tokens = (
        "newTimer(3000,1)",
        "this.txt_notification_header.txt_notification_header_text.text.text=header;",
        "this.txt_notification_body.txt_notification_body_text.text.text=message;",
        "this.m_timer.reset();",
        "this.m_timer.start();",
    )
    if not all(token in compact_notification for token in notification_tokens):
        raise ValueError("HUD notification lifetime or text assignment differs from the pinned screen")
    effect_tokens = (
        "this.bubbleCache.NewObject()",
        "this.activeEffects.push(effectBubble)",
        "addChild(effectBubble)",
        "effect.ID==ID",
        "this.activeEffects.splice(i,1)",
        "this.bubbleCache.StoreObject(effect)",
    )
    if not all(token in compact_effects for token in effect_tokens):
        raise ValueError("HUD effect-bubble allocation, identity, or cleanup behavior differs from the pinned screen")
    if compact_effects.count("thrownewError(") < 2:
        raise ValueError("HUD effect-bubble updates/removals no longer reject unknown IDs")
    if "icon_effect.icon_effect_art.SetTexture(iconName);" not in compact_bubble:
        raise ValueError("HUD effect bubble no longer binds the supplied icon to its native icon slot")

    return {
        "notification": {
            "method": "ApiNotification",
            "parameter_count": 3,
            "uses_native_icon_header_and_message": True,
            "auto_hide_after_ms": 3000,
            "persistent_progress_display": False,
        },
        "effect_bubbles": {
            "add_update_remove_api": True,
            "creates_movie_clip_and_adds_to_display_list": True,
            "reuses_removed_movie_clips": True,
            "caller_supplied_identity": "integer ID",
            "unknown_update_or_remove_id_throws": True,
            "custom_icon_asset_required": True,
            "interpretation": "A viable native HUD adapter for short notifications and persistent icon/status badges; it is not a general menu, text-panel, or interactive-control API.",
        },
    }


def _analyze_map_extension(
    root_source: str,
    mission_layer_source: str,
    root_methods: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    required_arities = {
        "ApiAddOrUpdateMission": 12,
        "ApiAddOrUpdateObjective": 7,
        "ApiAddOrUpdateObjectiveLocation": 4,
        "ApiRemoveObjectiveLocation": 2,
        "ApiRemoveMission": 1,
        "ApiRemoveObjective": 1,
    }
    if any(root_methods.get(name, {}).get("parameter_count") != arity for name, arity in required_arities.items()):
        raise ValueError("Map root API signatures do not match the pinned adapter contract")

    compact_root = re.sub(r"\s+", "", root_source)
    for method, call in {
        "ApiAddOrUpdateMission": "AddOrUpdateMission(param1,param2,param3,param4,param5,param6,param7,param8,param9,param10,param11,param12);",
        "ApiAddOrUpdateObjective": "AddOrUpdateObjective(param1,param2,param3,param4,param5,param6,param7);",
        "ApiAddOrUpdateObjectiveLocation": "AddOrUpdateObjectiveLocation(param1,param2,param3,param4);",
        "ApiRemoveObjectiveLocation": "RemoveObjectiveLocation(param1,param2);",
    }.items():
        if f"function{method}" not in compact_root or call not in compact_root:
            raise ValueError(f"Map root {method} no longer forwards through the native mission layer")
    if compact_root.count("this.m_minimap.UpdateOffscreenIndicatorPriorities();") < 4:
        raise ValueError("Map objective operations no longer refresh minimap indicator priority")

    mission_methods = _public_methods(mission_layer_source)
    required_layer_arities = {
        "AddOrUpdateObjective": 7,
        "AddOrUpdateObjectiveLocation": 4,
        "RemoveObjectiveLocation": 2,
    }
    if any(mission_methods.get(name, {}).get("parameter_count") != arity for name, arity in required_layer_arities.items()):
        raise ValueError("Map MissionLayer method signatures do not match the pinned adapter contract")

    add_body = re.sub(r"\s+", "", _extract_function_body(mission_layer_source, "AddOrUpdateObjectiveLocation"))
    add_tokens = (
        "this.m_objectives[objectiveHandle]asObjective",
        "if(Boolean(foundObjective))",
        "foundObjective.FindLocationByHandle(locationHandle)",
        "newObjectiveLocation(locationHandle,foundObjective,this)",
        "foundObjective.AddLocation(newLocation)",
        "newLocation.x=mapLocationX",
        "newLocation.y=mapLocationY+yAdjustment",
        "newLocation.Show()",
        "thrownewError(errorMsg)",
    )
    if not all(token in add_body for token in add_tokens):
        raise ValueError("Map objective-location allocation or ownership contract changed")

    remove_body = re.sub(r"\s+", "", _extract_function_body(mission_layer_source, "RemoveObjectiveLocation"))
    remove_tokens = (
        "this.m_objectives[param1]asObjective",
        "FindLocationByHandle(param2)",
        "RemoveLocationFromMap(_loc4_)",
        "_loc3_.RemoveLocation(_loc4_)",
        "thrownewError(_loc5_)",
    )
    if not all(token in remove_body for token in remove_tokens):
        raise ValueError("Map objective-location removal no longer uses objective/location handles")

    return {
        "mission_and_objective_api": {
            "mission_add_or_update_parameter_count": 12,
            "objective_add_or_update_parameter_count": 7,
            "objective_location_add_or_update_parameter_count": 4,
            "objective_location_remove_parameter_count": 2,
            "refreshes_minimap_offscreen_priorities": True,
        },
        "objective_locations": {
            "requires_preexisting_objective_handle": True,
            "requires_preexisting_location_handle_for_update": False,
            "new_location_is_attached_to_objective_collection": True,
            "new_location_is_shown_only_when_objective_has_owning_mission": True,
            "uses_map_movie_x_y_coordinates": True,
            "remove_uses_objective_and_location_handles": True,
            "unknown_objective_throws": True,
            "interpretation": "A structured map/objective adapter seam: add a location to a real Map Objective, then update/remove it by handles. The API receives map-space coordinates; it does not expose a standalone arbitrary-marker or world-to-map transform contract.",
        },
        "custom_interactive_controls": False,
    }


def _analyze_movie(name: str, payload_path: Path, ffdec_cli: Path, temp_root: Path) -> dict[str, Any]:
    config = PINNED_MOVIES[name]
    payload = payload_path.read_bytes()
    payload_hash = _sha256(payload)
    if payload_hash != config["iggy_sha256"]:
        raise ValueError(f"{name} Iggy SHA-256 mismatch: expected {config['iggy_sha256']}, got {payload_hash}")
    movie = inspect_iggy(payload, source_name=payload_path.name)
    movie_start = movie["subfiles"][movie["movie_subfile_index"]]["offset"]
    pointers = {row["name"]: row for row in movie["movie_header_relative_pointers"]}
    declaration = pointers.get("declaration_strings", {}).get("target_movie_offset")
    names_offset = pointers.get("names", {}).get("target_movie_offset")
    if declaration is None or names_offset is None:
        raise ValueError(f"{name} movie lacks bounded declaration/name offsets")
    if name == "map":
        abc_blocks, layout = extract_chained_abc_blocks(
            payload,
            section_offset=movie_start + declaration,
            section_end=movie_start + names_offset,
            expected_block_count=349,
        )
        abc_hash = _sha256(b"".join(abc_blocks))
        if (
            layout["abc_total_length"] != 585914
            or layout["trailing_padding_length"] != 4
            or not layout["trailing_padding_all_zero"]
        ):
            raise ValueError("Map chained ABC block lengths or terminal padding changed")
        script_root = _export_script_blocks(abc_blocks, ffdec_cli, temp_root / name)
    else:
        abc, layout = extract_abc_block(
            payload,
            section_offset=movie_start + declaration,
            section_end=movie_start + names_offset,
        )
        abc_hash = _sha256(abc)
        script_root = _export_scripts(abc, ffdec_cli, temp_root / name)
    if abc_hash != config["abc_sha256"]:
        raise ValueError(f"{name} ABC SHA-256 mismatch: expected {config['abc_sha256']}, got {abc_hash}")
    sources = {key: _read_script(script_root, relative) for key, relative in config["source_files"].items()}
    root_methods = _public_methods(sources["root"])
    missing = sorted(config["required_api"] - root_methods.keys())
    if missing:
        raise ValueError(f"{name} public Iggy movie API changed; missing: {', '.join(missing)}")

    record: dict[str, Any] = {
        "asset": config["asset"],
        "uasset_sha256": config["uasset_sha256"],
        "iggy_sha256": payload_hash,
        "abc_sha256": abc_hash,
        "abc_length": layout.get("abc_total_length", layout.get("abc_length")),
        "movie_subfile_size": movie["movie_subfile_size"],
        "abc_section": layout,
        "root_class": config["root_class"],
        "public_api": {name: root_methods[name] for name in sorted(config["required_api"])},
        "source_retained": False,
    }
    if name == "character":
        traits = sources["traits"]
        if "var _loc3_:uint = 4;" not in traits or "new Vector.<container_trait>(_loc3_)" not in traits or "new Vector.<container_trait_description>(_loc3_)" not in traits:
            raise ValueError("Could not verify the pinned Character trait widget pools")
        record["trait_extension"] = {
            "initial_widget_pool_capacity": 4,
            "creates_trait_name_widgets_from_pool": "this.m_containerTraits.pop()" in traits,
            "creates_trait_description_widgets_from_pool": "this.m_containerTraitDescriptions.pop()" in traits,
            "returns_without_adding_when_pool_empty": (
                "if(this.m_containerTraits.length == 0)" in traits
                and "if(this.m_containerTraitDescriptions.length == 0)" in traits
            ),
            "effect_rows_are_created_dynamically": "new container_trait_effect()" in traits,
            "interpretation": "Existing native trait display API is an adapter seam, but the stock movie preallocates four name/description widgets and silently refuses more; it is not an arbitrary widget API.",
        }
        record["other_character_movie_api_count"] = len(root_methods)
    elif name == "community":
        character_info = sources["characters"]
        overhead = sources["overhead"]
        record["community_extension"] = {
            "creates_character_overlay_for_new_ids": all(
                token in character_info
                for token in (
                    "new container_position_info_class()",
                    "new container_overhead_info_class()",
                    "this.m_positionInfos.push(_loc7_)",
                    "this.m_overheadInfos.push(_loc8_)",
                )
            ),
            "clear_all_characters_resets_collections": (
                "this.m_positionInfos = new Array()" in character_info
                and "this.m_overheadInfos = new Array()" in character_info
            ),
            "status_icons_created_as_needed": "new container_status_item()" in overhead,
            "per_character_text_adapters": sorted(
                name for name in ("ApiSetActionText", "ApiSetUnavailableText", "ApiClearActionText", "ApiClearUnavailableText")
                if name in root_methods
            ),
            "interpretation": "The stock community movie already creates anchored status overlays and icon rows dynamically for character IDs; API calls still require the game-owned screen lifecycle and cannot safely guess IDs or anchors.",
        }
        record["other_community_movie_api_count"] = len(root_methods)
    elif name == "hud":
        record["hud_extension"] = _analyze_hud_extension(
            sources["root"], sources["notification"], sources["effects"], sources["effect_bubble"], root_methods
        )
        record["other_hud_movie_api_count"] = len(root_methods)
    else:
        record["map_extension"] = _analyze_map_extension(
            sources["root"], sources["mission_layer"], root_methods
        )
        record["other_map_movie_api_count"] = len(root_methods)
    return record


def build_report(
    character: Path,
    community: Path,
    ffdec_cli: Path,
    hud: Path | None = None,
    map_movie: Path | None = None,
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="sod2-native-ui-movies-") as temp_name:
        temp_root = Path(temp_name)
        rows = {
            "character": _analyze_movie("character", character, ffdec_cli, temp_root),
            "community": _analyze_movie("community", community, ffdec_cli, temp_root),
        }
        if hud is not None:
            rows["hud"] = _analyze_movie("hud", hud, ffdec_cli, temp_root)
        if map_movie is not None:
            rows["map"] = _analyze_movie("map", map_movie, ffdec_cli, temp_root)
    return {
        "schema": 1,
        "target_build": 16535856,
        "target_executable_sha256": "ebf0a73e164baa701f74655585f262f8e38a32b1f6dc5057303489ba5b333ece",
        "scope": "Offline-only metadata summary of pinned Character, Community, and optional HUD/Map Iggy ActionScript APIs. No game process, executable, raw Iggy payload, or decompiled source is retained.",
        "decompiler": {"name": "JPEXS Free Flash Decompiler", "version": "26.3.0"},
        "movies": rows,
        "framework_assessment": {
            "settings_menu_entry": "A settings category/page adapter does not itself provide a general UI framework; it is a navigable host with one screen-specific rendering contract.",
            "character_ui": "A first read-only character adapter can reuse the original trait/effect display API, subject to selection/lifecycle and trait-slot layout limits. A guarded same-length bytecode probe raises the preallocated pool from four to six; it was wrapped into the pinned UAsset, changed only one package byte, and reparsed by CUE4Parse. Runtime loading and layout remain unverified.",
            "community_ui": "A community adapter can reuse per-character overlay and status-icon methods for progress/status annotations, but needs stable game-owned character IDs, screen lifecycle, anchors, cleanup, and input/focus ownership.",
            "hud_ui": "The HUD provides native transient notifications and keyed status-effect icon bubbles that are created, updated, removed, and recycled by the original movie. This is a concrete display adapter for level-up notices and active-buff badges, but it does not provide a general text panel or custom interactive controls.",
            "map_ui": "The Map movie exposes a mission/objective/location chain. A mod can target location updates on an existing objective and remove them by handles; new locations are only shown when their objective belongs to a mission. This is not a general arbitrary map marker API and does not define world-to-map coordinate conversion.",
            "generic_controls": "No static evidence here shows a supported API for arbitrary user-created controls, menu registration, or focus/navigation insertion across all native screens.",
            "overall_complexity": "High for a reusable cross-screen framework; moderate for narrowly scoped read-only adapters on one confirmed screen. Each screen requires a separate native UI adapter and lifecycle validation.",
        },
        "asset_editing_experiments": {
            "source_recompile": {
                "original_character_abc_bytes": 244745,
                "ffdec_imported_character_abc_bytes": 353302,
                "abc_growth_bytes": 108557,
                "naive_splice_new_movie_bytes": 2569024,
                "unchanged_index_final_offset_bytes": 2460464,
                "accepted_as_valid_asset": False,
                "finding": "FFDec script import rewrites several unrelated decompiled scripts, and a naive Iggy splice leaves the index stream ending at the old movie boundary. This rebuild route is rejected for now."
            },
            "same_length_character_trait_pool_probe": {
                "report": "native-character-trait-pool-probe.json",
                "capacity_change": [4, 6],
                "changed_byte_count": 1,
                "movie_size_unchanged": True,
                "index_stream_ends_at_movie_boundary": True,
                "uasset_wrap_test": {
                    "tool": "NativeSettingsAssetWriter replace-iggy",
                    "output_uasset_sha256": "5aef5e62a1ac2f3f00e5c17e9ee4269d6794f0306413d29eefc10c5cc1e51e64",
                    "uasset_size_bytes": 2554832,
                    "changed_byte_count": 1,
                    "changed_byte_offset": 2469842,
                    "cue4parse_reparsed": True,
                    "output_loaded_in_game": False,
                },
                "output_loaded_in_game": False,
                "finding": "A fixed-build AVM2 pushbyte immediate can be changed in place under an exact bytecode guard; this demonstrates a narrow asset-edit experiment only, not a general UI plugin API."
            }
        },
        "static_only_limitations": [
            "IggyPlayerCallMethodRS path/value argument ABI and its ActionScript namespace resolution remain unresolved; public method names in movie bytecode do not prove native invocation is safe or supported.",
            "Native character/community UFunction registration names and RVAs are static candidates only; selected-character ownership, ID stability, callback timing, and cleanup behavior are not verified.",
            "The one-byte probe now rebuilds and reparses the pinned Unreal package, but does not extend the community screen, create arbitrary controls, or prove the extra trait rows fit on screen.",
            "The Map Objective Location API is structurally understood, but IggyPlayerCallMethodRS runtime invocation, native mission/objective identity ownership, screen-open timing, and map coordinate conversion remain unverified.",
            "No runtime invocation or game validation was performed.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--character", type=Path, required=True, help="Pinned local character.iggy")
    parser.add_argument("--community", type=Path, required=True, help="Pinned local community.iggy")
    parser.add_argument("--hud", type=Path, help="Pinned local hud.iggy; when provided, adds the HUD adapter analysis")
    parser.add_argument("--map", dest="map_movie", type=Path, help="Pinned local map.iggy; when provided, adds the Map adapter analysis")
    parser.add_argument("--ffdec-cli", type=Path, required=True, help="JPEXS FFDec 26.3.0 CLI")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = build_report(args.character, args.community, args.ffdec_cli, args.hud, args.map_movie)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    analyzed_names = "Character and Community"
    if args.hud:
        analyzed_names += ", HUD"
    if args.map_movie:
        analyzed_names += ", and Map"
    print(f"PASS: verified pinned {analyzed_names} Iggy script API metadata")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
