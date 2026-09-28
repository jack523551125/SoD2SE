"""Validate the fixed-version reverse-engineering database and its exports."""
import json
import re
import sys
import hashlib
from collections import Counter
from pathlib import Path

# Keep an in-place validation run side-effect free for packaged research data.
sys.dont_write_bytecode = True

from sync_research import DATABASE, ROOT, render_exports, read_json


def fail(message):
    raise ValueError(message)


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def walk_json_nodes(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk_json_nodes(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_json_nodes(child)


def candidate_directory_matches(movie, expected_count):
    directory = movie.get("object_directory_layout", {})
    return directory == {
        "object_count": expected_count,
        "pointer_targets_in_file_order": True,
        "known_record_layout_count": expected_count,
        "all_records_have_known_layout": True,
        "candidate_records_non_overlapping": True,
        "candidate_record_overlap_count": 0,
    }


def relative_target_observations_match(movie, expected):
    observations = movie.get("field_relative_target_observations", {})
    for kind, fields in expected.items():
        for field_offset, expected_counts in fields.items():
            observation = observations.get(kind, {}).get(field_offset, {})
            actual_counts = {
                key: value
                for key, value in observation.items()
                if key not in {"metadata_type_code", "objects_checked"}
            }
            if (
                observation.get("metadata_type_code") != 2
                or observation.get("objects_checked") != sum(expected_counts.values())
                or actual_counts != expected_counts
            ):
                return False
    return True


def candidate_payload_observations_match(movie, expected):
    actual = movie.get("candidate_field_target_payload_observations", {}).get("3", {}).get("0x40")
    return actual == expected


def candidate_payload_formats_match(movie, expected):
    actual = movie.get("candidate_payload_format_observations", {}).get("4", {}).get("0x48")
    return actual == expected


def index_stream_relationship_matches(movie, expected):
    return movie.get("index_stream_relationship") == expected


def canonical_json_sha256(value):
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def main():
    target = read_json(DATABASE / "target.json")
    database = read_json(DATABASE / "patches.json")
    functions = read_json(DATABASE / "functions.json")
    structs = read_json(DATABASE / "structs.json")
    domains = read_json(DATABASE / "research-domains.json")
    body_analysis = read_json(DATABASE / "native-body-analysis.json")
    full_pdata_xrefs = read_json(DATABASE / "native-full-pdata-direct-xrefs.json")
    full_pdata_xref_audit = read_json(DATABASE / "native-full-pdata-direct-xrefs-audit.json")
    roguelite_followup_xrefs = read_json(DATABASE / "roguelite-native-followup-direct-xrefs.json")
    roguelite_followup_xref_audit = read_json(DATABASE / "roguelite-native-followup-direct-xrefs-audit.json")
    roguelite_followup_address_refs = read_json(DATABASE / "roguelite-native-followup-address-references.json")
    roguelite_kill_experience_disassembly = read_json(DATABASE / "roguelite-kill-experience-disassembly.json")
    roguelite_experience_blueprint_call_contexts = read_json(DATABASE / "roguelite-experience-blueprint-call-contexts.json")
    roguelite_experience_reward_table = read_json(DATABASE / "roguelite-experience-reward-table.json")
    roguelite = read_json(DATABASE / "roguelite-capabilities.json")
    xref_focus = read_json(DATABASE / "native-xref-focus.json")
    community_asset_scan = read_json(DATABASE / "community-assets-static-scan.json")
    community_named_asset_scan = read_json(DATABASE / "community-named-asset-candidates-scan.json")
    community_specific_symbol_scan = read_json(DATABASE / "community-specific-symbol-candidates-scan.json")
    community_global_asset_scan = read_json(DATABASE / "community-all-assets-global-scan.json")
    community_mission_tags = read_json(DATABASE / "community-mission-property-analysis.json")
    community_cooked_blueprint = read_json(DATABASE / "community-cooked-blueprint-analysis.json")
    community_all_string_hit_cooked = read_json(DATABASE / "community-all-string-hit-cooked-analysis.json")
    community_full_uasset_audit = read_json(DATABASE / "community-full-uasset-cooked-audit.json")
    community_full_uasset_calls = read_json(DATABASE / "community-full-uasset-blueprint-call-analysis.json")
    community_full_uasset_roguelite_calls = read_json(DATABASE / "community-full-uasset-roguelite-call-analysis.json")
    community_full_mission_event_calls = read_json(DATABASE / "community-full-uasset-mission-event-lifecycle-call-analysis.json")
    community_full_mission_condition_census = read_json(DATABASE / "community-full-uasset-mission-condition-census.json")
    mission_condition_enum_pointer_evidence = read_json(DATABASE / "mission-condition-enum-native-pointer-evidence.json")
    mission_condition_enum_native_registration = read_json(DATABASE / "mission-condition-enum-native-registration.json")
    community_mission_condition_native_name_xrefs = read_json(DATABASE / "community-mission-condition-native-name-xrefs.json")
    community_mission_condition_native_layout = read_json(DATABASE / "community-mission-condition-native-layout.json")
    roguelite_enemy_classification = read_json(DATABASE / "roguelite-enemy-classification-static.json")
    zombie_variant_enum_native_registration = read_json(DATABASE / "zombie-variant-enum-native-registration.json")
    zombie_plague_flag_native_name_references = read_json(DATABASE / "zombie-plague-flag-native-name-references.json")
    community_recruitment = read_json(DATABASE / "community-recruitment-static-findings.json")
    community_recruitment_xrefs = read_json(DATABASE / "community-recruitment-native-xrefs.json")
    native_settings_chain = read_json(DATABASE / "native-settings-resource-chain.json")
    native_settings_text = read_json(DATABASE / "native-settings-text-probe.json")
    native_settings_iggy = read_json(DATABASE / "native-settings-iggy-compatibility.json")
    native_settings_iggy_catalog = read_json(DATABASE / "native-settings-iggy-object-catalog.json")
    native_settings_iggy_links = read_json(DATABASE / "native-settings-iggy-object-links.json")
    native_settings_iggy_runtime_api = read_json(DATABASE / "native-settings-iggy-runtime-api.json")
    native_ui_screen_adapters = read_json(DATABASE / "native-ui-screen-adapters.json")
    native_character_trait_pool_probe = read_json(DATABASE / "native-character-trait-pool-probe.json")
    iggy_exports = read_json(DATABASE / "iggy-dll-exports.json")
    native_ui_runtime = read_json(DATABASE / "native-ui-runtime-candidates.json")
    if native_settings_chain.get("schema") != 2 or native_settings_chain.get("target_build") != 16535856:
        fail("原版设置资源链的目标版本不符")
    if native_settings_chain.get("cooked_settings_sha256") != native_settings_text.get("source_sha256"):
        fail("原版设置页两份静态报告的原始资产散列不一致")
    if native_settings_chain.get("settings_text_table_rows") != native_settings_text.get("text_table_rows") or native_settings_chain.get("settings_text_table_rows") != 159:
        fail("原版设置页文字表数量不一致")
    if len(native_settings_chain.get("settings_api_functions", [])) != native_settings_text.get("api_function_count") or native_settings_text.get("api_function_count") != 65:
        fail("原版设置页 API 数量不一致")
    movie_factory = native_settings_chain.get("movie_player_factory_callsite", [])
    if not movie_factory or any(
        row.get("function") != "UIManagerComponent:CreateMoviePlayer"
        or row.get("source_asset") != "GameModes/VanillaPlayerController_BP.json"
        or row.get("class_argument") != "/game/ui/characterui_bp"
        for row in movie_factory
    ):
        fail("原版播放器工厂的类参数证据不完整")
    export_hashes = native_settings_chain.get("export_sha256", {})
    navigation_source = native_settings_chain.get("settings_navigation_source", {})
    if len(export_hashes.get("GameModes/VanillaPlayerController_BP.json", "")) != 64:
        fail("原版播放器工厂调用点缺少导出资产散列")
    if navigation_source.get("asset") != "UI/PauseUI_BP.json" or navigation_source.get("asset_sha256") != export_hashes.get("UI/PauseUI_BP.json"):
        fail("原版设置页导航链没有关联到暂停菜单导出散列")
    settings_navigation = native_settings_chain.get("settings_navigation", {})
    display_settings = settings_navigation.get("display_settings", {})
    hide_settings = settings_navigation.get("hide_settings", {})
    if display_settings.get("entry_point") != 1075 or display_settings.get("graph_jump_target") != 713:
        fail("原版设置页打开事件的 Blueprint 跳转证据不完整")
    if "UIManagerComponent.PushMoviePlayer(/game/ui/settingsui_bp)" not in display_settings.get("operations", []):
        fail("原版设置页打开调用没有关联到设置播放器类")
    if settings_navigation.get("closed_delegate") != {
        "property": "MulticastDelegateProperty'CommonUIMoviePlayer:Closed'",
        "callback": "OnSettingsClosed",
    }:
        fail("原版设置页关闭回调证据不完整")
    if hide_settings.get("entry_point") != 906 or hide_settings.get("graph_jump_target") != 657:
        fail("原版设置页清理事件的 Blueprint 跳转证据不完整")
    if hide_settings.get("operation") != "PauseUI_BP.SettingsMovie = null":
        fail("原版设置页清理动作不完整")
    if native_settings_chain.get("settings_api_name_scan", {}).get("generic_page_or_plugin_candidates"):
        fail("原版设置页 API 名称扫描需要人工复核通用扩展候选")
    if not native_settings_text.get("no_op_reparse_matches_reference") or not native_settings_text.get("patched_reparse_succeeded"):
        fail("原版设置页离线文字实验状态不符")
    if native_settings_iggy.get("target_build") != 16535856:
        fail("原版设置页 Iggy 结构报告目标版本不符")
    iggy_settings_asset = native_settings_iggy.get("settings_asset", {})
    iggy_extract = native_settings_iggy.get("verified_settings_extraction", {})
    settings_movie = iggy_extract.get("movie", {})
    iggy_subfiles = iggy_extract.get("subfiles", [])
    if (
        iggy_settings_asset.get("sha256") != native_settings_chain.get("cooked_settings_sha256")
        or iggy_extract.get("exit_code") != 0
        or iggy_extract.get("payload_size") != iggy_settings_asset.get("normal_export_extras_size", 0) - 20
        or iggy_extract.get("platform_bytes", [None, None])[1] != 64
        or settings_movie.get("object_kind_counts") != {"1": 49, "3": 353, "4": 33, "6": 73}
        or [row.get("kind") for row in iggy_subfiles] != [1, 0, 0]
        or sum(row.get("size", 0) for row in iggy_subfiles) + 80 != iggy_extract.get("payload_size")
        or iggy_subfiles[0].get("offset") != 80
        or iggy_subfiles[1].get("offset") != iggy_subfiles[0].get("offset") + iggy_subfiles[0].get("size")
        or iggy_subfiles[2].get("offset") != iggy_subfiles[1].get("offset") + iggy_subfiles[1].get("size")
        or settings_movie.get("header_relative_pointer_targets", {}).get("base") != 184
        or settings_movie.get("header_relative_pointer_targets", {}).get("sequence_end", 0) >= settings_movie.get("movie_subfile_size", 0)
    ):
        fail("固定版本 Iggy 提取或设置页对象统计不一致")
    jpexs = native_settings_iggy.get("jpexs_26_3_0_source_check", {})
    if (
        set(jpexs.get("top_level_object_kinds_accepted_by_parser", {})) != {"6", "22"}
        or not {1, 3, 4} <= set(jpexs.get("target_game_object_kinds_not_supported_by_that_parser", []))
        or native_settings_iggy.get("inspector", {}).get("automated_tests") != 23
    ):
        fail("JPEXS 对照报告没有覆盖游戏设置电影里的未知对象类型")
    expected_iggy_catalog_assets = [
        {
            "asset": "Art/UI/settings.uasset",
            "payload_sha256": "e69875cd5421f8082cf4e0b66e8a2cd09ba81f8455b08243635695ea0b4bdb57",
            "object_count": 508,
            "object_kind_counts": {"1": 49, "3": 353, "4": 33, "6": 73},
        },
        {
            "asset": "Art/UI/character.uasset",
            "payload_sha256": "d134758ed784ac6beb64cc8494acc315b1f30591541fecaacdf3532109fb188d",
            "object_count": 541,
            "object_kind_counts": {"1": 37, "3": 386, "4": 29, "6": 89},
        },
        {
            "asset": "Art/UI/pause.uasset",
            "payload_sha256": "0f8607960fceedee1aa594fa699dc7eb7557b574f1e290b18a72440fa5e6ba33",
            "object_count": 156,
            "object_kind_counts": {"1": 11, "3": 110, "4": 8, "6": 27},
        },
    ]
    if (
        native_settings_iggy_catalog.get("schema") != 1
        or native_settings_iggy_catalog.get("target_build") != 16535856
        or [
            {key: asset.get(key) for key in ("asset", "payload_sha256", "object_count", "object_kind_counts")}
            for asset in native_settings_iggy_catalog.get("assets", [])
        ] != expected_iggy_catalog_assets
    ):
        fail("原版 Iggy 逐对象目录版本、散列或对象计数不符")
    expected_record_sizes = {"1": 80, "3": 72, "4": 88, "6": 104}
    for asset in native_settings_iggy_catalog["assets"]:
        records = asset.get("records", [])
        if len(records) != asset.get("object_count"):
            fail(f"原版 Iggy 逐对象目录行数不符：{asset.get('asset')}")
        offsets = [row.get("movie_offset") for row in records]
        if offsets != sorted(set(offsets)):
            fail(f"原版 Iggy 对象偏移未严格递增：{asset.get('asset')}")
        for expected_index, row in enumerate(records):
            kind = str(row.get("kind"))
            layouts = row.get("index_layout_matches", [])
            if (
                row.get("object_index") != expected_index
                or row.get("candidate_record_size") != expected_record_sizes.get(kind)
                or len(layouts) != 1
                or layouts[0].get("record_size") != row.get("candidate_record_size")
                or set(row) != {
                    "object_index", "movie_offset", "kind", "next_object_movie_offset",
                    "candidate_record_size", "index_layout_matches", "relative_fields",
                }
            ):
                fail(f"原版 Iggy 对象布局映射不完整：{asset.get('asset')} object {expected_index}")
            for field in row.get("relative_fields", []):
                if (
                    field.get("type_code") != 2
                    or set(field) != {
                        "local_offset", "type_code", "relative_value",
                        "target_movie_offset", "target_relation",
                    }
                    or (
                        field.get("relative_value") == 1
                        and field.get("target_movie_offset") is not None
                    )
                    or (
                        field.get("relative_value") != 1
                        and field.get("target_movie_offset")
                        != row.get("movie_offset") + field.get("local_offset") + field.get("relative_value")
                    )
                ):
                    fail(f"原版 Iggy 对象目录字段摘要无效：{asset.get('asset')} object {expected_index}")
    expected_iggy_link_assets = [
        {
            "asset": "Art/UI/settings.uasset",
            "payload_sha256": "e69875cd5421f8082cf4e0b66e8a2cd09ba81f8455b08243635695ea0b4bdb57",
            "object_count": 508,
            "aligned_candidate_links": 605,
            "roles": {
                "kind1_record_end_region": {"blocks_analyzed": 49, "blocks_with_aligned_object_targets": 33, "aligned_candidate_target_count": 33, "target_kind_counts": {"4": 33}},
                "kind3_dual_pointer_span": {"blocks_analyzed": 353, "blocks_with_aligned_object_targets": 322, "aligned_candidate_target_count": 572, "target_kind_counts": {"1": 53, "3": 445, "6": 74}},
            },
        },
        {
            "asset": "Art/UI/character.uasset",
            "payload_sha256": "d134758ed784ac6beb64cc8494acc315b1f30591541fecaacdf3532109fb188d",
            "object_count": 541,
            "aligned_candidate_links": 668,
            "roles": {
                "kind1_record_end_region": {"blocks_analyzed": 37, "blocks_with_aligned_object_targets": 29, "aligned_candidate_target_count": 45, "target_kind_counts": {"4": 45}},
                "kind3_dual_pointer_span": {"blocks_analyzed": 386, "blocks_with_aligned_object_targets": 355, "aligned_candidate_target_count": 623, "target_kind_counts": {"1": 42, "3": 492, "6": 89}},
            },
        },
        {
            "asset": "Art/UI/pause.uasset",
            "payload_sha256": "0f8607960fceedee1aa594fa699dc7eb7557b574f1e290b18a72440fa5e6ba33",
            "object_count": 156,
            "aligned_candidate_links": 182,
            "roles": {
                "kind1_record_end_region": {"blocks_analyzed": 11, "blocks_with_aligned_object_targets": 8, "aligned_candidate_target_count": 8, "target_kind_counts": {"4": 8}},
                "kind3_dual_pointer_span": {"blocks_analyzed": 110, "blocks_with_aligned_object_targets": 99, "aligned_candidate_target_count": 174, "target_kind_counts": {"1": 13, "3": 134, "6": 27}},
            },
        },
    ]
    if native_settings_iggy_links.get("schema") != 1 or native_settings_iggy_links.get("target_build") != 16535856:
        fail("原版 Iggy 候选对象链接报告的 schema 或目标版本不符")
    link_assets = native_settings_iggy_links.get("assets", [])
    if len(link_assets) != len(expected_iggy_link_assets):
        fail("原版 Iggy 候选对象链接报告的资源数量不符")
    for link_asset, expected, catalog_asset in zip(
        link_assets, expected_iggy_link_assets, native_settings_iggy_catalog["assets"]
    ):
        if (
            link_asset.get("asset") != expected["asset"]
            or link_asset.get("payload_sha256") != expected["payload_sha256"]
            or link_asset.get("object_count") != expected["object_count"]
            or link_asset.get("aligned_candidate_links") != expected["aligned_candidate_links"]
            or link_asset.get("unaligned_exact_object_start_hits_by_field_residue") != {}
        ):
            fail(f"原版 Iggy 候选链接样本或计数不符：{expected['asset']}")
        for role, expected_role in expected["roles"].items():
            actual_role = link_asset.get("by_block_role", {}).get(role, {})
            if any(actual_role.get(key) != value for key, value in expected_role.items()):
                fail(f"原版 Iggy 候选链接分类计数不符：{expected['asset']} {role}")
        records = catalog_asset["records"]
        for edge in link_asset.get("edges", []):
            source_index = edge.get("source_object_index", -1)
            target_index = edge.get("target_object_index", -1)
            role = edge.get("block_role")
            if role == "kind1_record_end_region" and 0 <= source_index < len(records):
                source_fields = {field.get("local_offset"): field for field in records[source_index].get("relative_fields", [])}
                expected_block_start = source_fields.get(72, {}).get("target_movie_offset")
                block_end = records[source_index].get("next_object_movie_offset")
            elif role == "kind3_dual_pointer_span" and 0 <= source_index < len(records):
                source_fields = {field.get("local_offset"): field for field in records[source_index].get("relative_fields", [])}
                expected_block_start = source_fields.get(56, {}).get("target_movie_offset")
                block_end = source_fields.get(64, {}).get("target_movie_offset")
            else:
                expected_block_start = None
                block_end = None
            if (
                source_index < 0 or source_index >= len(records)
                or target_index < 0 or target_index >= len(records)
                or edge.get("source_movie_offset") != records[source_index].get("movie_offset")
                or edge.get("target_movie_offset") != records[target_index].get("movie_offset")
                or edge.get("source_kind") != records[source_index].get("kind")
                or edge.get("target_kind") != records[target_index].get("kind")
                or edge.get("target_index_delta") != target_index - source_index
                or edge.get("block_start_movie_offset") + edge.get("field_offset_from_block") + edge.get("relative_i32") != edge.get("target_movie_offset")
                or edge.get("block_start_movie_offset") != expected_block_start
                or block_end is None
                or edge.get("field_offset_from_block") + 4 > block_end - expected_block_start
                or edge.get("field_offset_from_block") % 8 != 0
                or edge.get("relative_i32") % 8 != 0
                or edge.get("target_movie_offset") % 8 != 0
                or edge.get("source_kind") != (1 if edge.get("block_role") == "kind1_record_end_region" else 3)
                or set(edge) != {
                    "block_role", "source_object_index", "source_movie_offset", "source_kind",
                    "block_start_movie_offset", "field_offset_from_block", "relative_i32",
                    "target_object_index", "target_movie_offset", "target_kind", "target_index_delta",
                }
            ):
                fail(f"原版 Iggy 候选链接的逐边偏移无效：{expected['asset']}")
    expected_iggy_runtime_exports = {
        "IggyLibraryCreateFromMemory": 0x58360,
        "IggyPlayerCreateFromMemory": 0x582B0,
        "IggyPlayerCallFunctionRS": 0x573A0,
        "IggyPlayerCallMethodRS": 0x574A0,
        "IggyPlayerDispatchEventRS": 0x57EE0,
        "IggyPlayerGetFocusableObjects": 0x18140,
        "IggyPlayerSetFocusRS": 0x58030,
        "IggyValueRefCreateEmptyObject": 0x67FC0,
        "IggyValueRefCreateArray": 0x680B0,
        "IggyValueRefFromPath": 0x67E90,
        "IggyValuePathSetParent": 0x66A30,
    }
    runtime_export_rows = {
        row.get("name"): row
        for row in native_settings_iggy_runtime_api.get("analyzed_exports", [])
    }
    runtime_focus_patterns = native_settings_iggy_runtime_api.get(
        "focus_enumeration_observations", {}
    ).get("static_patterns_verified", {})
    if (
        native_settings_iggy_runtime_api.get("schema") != 1
        or native_settings_iggy_runtime_api.get("target_build") != 16535856
        or native_settings_iggy_runtime_api.get("dll_name") != "iggy_w64.dll"
        or native_settings_iggy_runtime_api.get("dll_sha256")
        != "09049ffc7b48639c72336bb809035fa1c1b827e898693fbc2968165bd23940a6"
        or native_settings_iggy_runtime_api.get("export_count") != 204
        or set(runtime_export_rows) != set(expected_iggy_runtime_exports)
        or any(
            runtime_export_rows[name].get("export_rva") != rva
            for name, rva in expected_iggy_runtime_exports.items()
        )
        or not all(runtime_focus_patterns.get(name) is True for name in (
            "count_initialized_to_zero",
            "optional_player_context_pointer_copied",
            "focus_record_stride_24_bytes",
            "output_copies_existing_object_fields",
            "walks_existing_object_links",
        ))
        or native_settings_iggy_runtime_api.get("export_surface", {}).get(
            "explicit_display_tree_mutation_name_candidates"
        ) != []
    ):
        fail("固定版 Iggy 运行时导出/控制流静态报告与锁定证据不符")
    for export_name, expected_target in (
        ("IggyPlayerCallFunctionRS", 0xB2520),
        ("IggyPlayerCallMethodRS", 0xB29C0),
    ):
        if expected_target not in {
            call.get("target_rva")
            for call in runtime_export_rows[export_name].get("direct_calls", [])
        }:
            fail(f"固定版 Iggy 脚本调用导出缺少已验证的分发调用边：{export_name}")
    text_edit_experiment = native_settings_iggy.get("iggy_text_edit_experiment", {})
    if (
        text_edit_experiment.get("tool") != "Research/tools/patch_iggy_text.py"
        or text_edit_experiment.get("source_asset") != "Art/UI/settings.uasset"
        or text_edit_experiment.get("input_payload_sha256") != iggy_extract.get("payload_sha256")
        or text_edit_experiment.get("output_payload_sha256") != "c8caf94d51ab6e11d44af159f5c6be3bace91201c3cc830ef8f50921ae7babc8"
        or text_edit_experiment.get("text_index") != 82
        or text_edit_experiment.get("expected_original_text_sha256") != "24c852fb8c99d4802cb5731f31e20d26ccb5a76d1e1ca92d7dfc75bf273caef1"
        or text_edit_experiment.get("replacement_text_sha256") != "f3c9bf8d81b3252158cb3833f89d798f6a101d05f48e4833576ef448b6e006ed"
        or text_edit_experiment.get("string_payload_offset") != 821840
        or text_edit_experiment.get("utf16_code_units") != 17
        or text_edit_experiment.get("patched_span_byte_count") != 34
        or text_edit_experiment.get("changed_byte_count") != 17
        or text_edit_experiment.get("payload_size_unchanged") is not True
        or text_edit_experiment.get("independent_reparse_succeeded") is not True
        or text_edit_experiment.get("all_other_bytes_and_layouts_preserved") is not True
        or {"original_text", "replacement_text"}.intersection(text_edit_experiment)
    ):
        fail("原版设置 Iggy 定长文字编辑实验记录不完整或边界声明不符")
    settings_indexes = iggy_extract.get("index_subfile_summaries", [])
    if (
        len(settings_indexes) != 2
        or [row.get("subfile_index") for row in settings_indexes] != [1, 2]
        or any(row.get("bytes_consumed") != row.get("size") for row in settings_indexes)
        or [row.get("final_cumulative_offset") for row in settings_indexes] != [4369624, settings_movie.get("movie_subfile_size")]
        or any(row.get("maximum_cumulative_offset") != row.get("final_cumulative_offset") for row in settings_indexes)
    ):
        fail("设置电影 Iggy 索引子流汇总不完整或累计偏移不一致")
    expected_settings_index_matches = [
        {"count": 389, "kinds": {"1": 35, "3": 271, "4": 24, "6": 59}},
        {"count": 119, "kinds": {"1": 14, "3": 82, "4": 9, "6": 14}},
    ]
    settings_correspondence = settings_movie.get("object_index_correspondence", {})
    settings_layout_correspondence = settings_movie.get("object_start_layout_correspondence", {})
    settings_layouts = settings_movie.get("object_start_layouts_by_kind", {})
    if (
        settings_movie.get("imported_guid_header_value") != 1
        or settings_movie.get("object_pointer_tables") != {
            "primary_count": 508,
            "additional_count": 0,
            "additional_pointer_field_movie_offset": 4264,
            "additional_pointer_value": 1,
            "additional_table_movie_offset": None,
        }
        or settings_correspondence != {
            "object_pointer_count": 508,
            "distinct_object_starts_matched": 508,
            "unmatched_object_start_count": 0,
            "duplicate_match_count": 0,
            "every_object_start_matches_exactly_once": True,
        }
        or [
            {
                "count": row.get("object_start_match_count"),
                "kinds": row.get("object_start_matches_by_kind"),
            }
            for row in settings_indexes
        ] != expected_settings_index_matches
        or any(row.get("distinct_object_start_match_count") != row.get("object_start_match_count") for row in settings_indexes)
    ):
        fail("设置电影对象目录与索引累计边界的一对一对应关系不一致")
    jpexs_conversion = jpexs.get("conversion_source_findings", {})
    jpexs_index = jpexs_conversion.get("index_read_write_findings", {})
    jpexs_metadata = jpexs.get("index_metadata_findings", {})
    text_layout = jpexs_metadata.get("builder_known_text_layout", {})
    expected_record_sizes = {"1": 80, "3": 72, "4": 88, "6": 104}
    expected_settings_relative_targets = {
        "1": {"0x48": {"record_end": 49}},
        "3": {
            "0x38": {"record_end": 353},
            "0x40": {"interrecord_tail": 346, "record_end": 7},
        },
        "4": {"0x48": {"record_end": 33}},
        "6": {"0x60": {"record_end": 73}},
    }
    expected_settings_text_pointer_summary = {
        "objects_checked": 73,
        "object_relative_target_offset_counts": {"104": 73},
        "all_targets_at_104_byte_text_record_end": True,
    }
    expected_settings_type3_payload = {
        "metadata_type_code": 2,
        "objects_checked": 353,
        "target_location_counts": {"interrecord_tail": 346, "record_end": 7},
        "target_to_next_object_start_distance_counts": {"16": 352, "196672": 1},
        "target_prefix_u64_pair_counts": {"1,1": 353},
    }
    expected_settings_type4_payload = {
        "metadata_type_code": 2,
        "objects_checked": 33,
        "target_format_counts": {"zlib_complete": 26, "length_prefixed_jpeg": 7},
    }
    expected_settings_type1_regions = {
        "1": {
            "0x48": {
                "metadata_type_code": 2,
                "objects_checked": 49,
                "target_location_counts": {"record_end": 49},
                "region_byte_length_counts": {
                    "216": 3,
                    "288": 6,
                    "336": 1,
                    "376": 32,
                    "384": 3,
                    "688": 1,
                    "696": 2,
                    "816": 1,
                },
                "region_byte_length_mod_8_counts": {"0": 49},
                "region_start_mod_8_counts": {"0": 49},
                "region_envelope_counts": {"opaque_nonzero": 49},
                "distinct_non_sentinel_region_sha256_count": 49,
                "all_non_sentinel_regions_8_byte_aligned": True,
            }
        }
    }
    expected_settings_index_relationship = {
        "stream_count": 2,
        "object_start_matches_disjoint": True,
        "object_start_match_ranges_sequential": True,
        "index_table_definitions_identical": True,
        "object_start_match_count": 508,
        "distinct_object_start_match_count": 508,
        "segments": [
            {
                "subfile_index": 1,
                "index_table_sha256": "0ec4af9dfc69cc0d7e4c1db9e34bb8e609358b986c93079d8c483d89852e046c",
                "first_command_end_offset": 184,
                "first_object_start_offset": 4280,
                "last_object_start_offset": 4367392,
                "final_cumulative_offset": 4369624,
                "first_command_end_delta_from_previous_final": None,
            },
            {
                "subfile_index": 2,
                "index_table_sha256": "0ec4af9dfc69cc0d7e4c1db9e34bb8e609358b986c93079d8c483d89852e046c",
                "first_command_end_offset": 4369624,
                "first_object_start_offset": 4377856,
                "last_object_start_offset": 7324632,
                "final_cumulative_offset": 7535744,
                "first_command_end_delta_from_previous_final": 0,
            },
        ],
    }
    expected_kind3_dual_pointer_sha256 = {
        "settings": "ddd7b4434295ebc29820dd47e29d2ca85fae30c17a44cdf9e955f4c9503ba6b8",
        "character": "2a1a1751473ae3ee8acb0d573c2acf7feea869ed7315d0263bb316ebb7047bc1",
        "pause": "ee0709423b9da1cdab7afb44986bc8bab01a5e1041b9670e1668904f0a468853",
    }
    if (
        settings_layout_correspondence.get("object_pointer_count") != settings_movie.get("object_pointer_count")
        or settings_layout_correspondence.get("command_start_match_count") != settings_movie.get("object_pointer_count")
        or settings_layout_correspondence.get("distinct_object_starts_matched") != settings_movie.get("object_pointer_count")
        or settings_layout_correspondence.get("unmatched_object_start_count") != 0
        or settings_layout_correspondence.get("duplicate_match_count") != 0
        or settings_layout_correspondence.get("consistent_record_layout_per_kind") is not True
        or settings_layout_correspondence.get("every_object_start_has_exactly_one_layout_command") is not True
        or set(settings_layouts) != set(expected_record_sizes)
        or any(
            settings_layouts[kind].get("object_count") != settings_movie.get("object_kind_counts", {}).get(kind)
            or settings_layouts[kind].get("record_size") != size
            or not settings_layouts[kind].get("metadata_descriptors")
            for kind, size in expected_record_sizes.items()
        )
        or settings_layouts["6"].get("record_size") != text_layout.get("size")
        or [field.get("local_offset") for field in settings_layouts["6"].get("metadata_descriptors", [])] != text_layout.get("local_offsets")
        or [field.get("type_code") for field in settings_layouts["6"].get("metadata_descriptors", [])] != text_layout.get("type_codes")
        or jpexs_metadata.get("parser_source") != "libsrc/ffdec_lib/src/com/jpexs/decompiler/flash/iggy/streams/IggyIndexParser.java"
        or jpexs_metadata.get("builder_source") != "libsrc/ffdec_lib/src/com/jpexs/decompiler/flash/iggy/streams/IggyIndexBuilder.java"
        or jpexs_metadata.get("text_source") != "libsrc/ffdec_lib/src/com/jpexs/decompiler/flash/iggy/IggyText.java"
        or jpexs_metadata.get("target_kinds_1_3_4_semantics_proven") is not False
        or not candidate_directory_matches(settings_movie, 508)
        or not relative_target_observations_match(settings_movie, expected_settings_relative_targets)
        or settings_movie.get("kind_6_string_pointer_summary") != expected_settings_text_pointer_summary
        or not candidate_payload_observations_match(settings_movie, expected_settings_type3_payload)
        or not candidate_payload_formats_match(settings_movie, expected_settings_type4_payload)
        or settings_movie.get("candidate_record_end_region_observations") != expected_settings_type1_regions
        or canonical_json_sha256(settings_movie.get("candidate_dual_pointer_observations")) != expected_kind3_dual_pointer_sha256["settings"]
        or not index_stream_relationship_matches(settings_movie, expected_settings_index_relationship)
    ):
        fail("设置电影对象起始命令、候选记录布局或相对字段目标汇总不完整")
    if (
        jpexs_conversion.get("exported_swf_object_families") != ["DefineFont2", "DefineEditText", "DoABC2"]
        or jpexs_conversion.get("importer_rejects_font_or_text_count_changes") is not True
        or jpexs_conversion.get("unknown_game_movie_objects_preserved_by_writer") is not False
        or jpexs_index.get("target_mapping_proven") is not False
        or "commented out" not in jpexs_index.get("reader_parse_entries", "")
        or "removes all original type-0 entries" not in jpexs_index.get("writer_update_flash_entry", "")
    ):
        fail("JPEXS 的 Iggy 编辑范围或写回限制报告不完整")
    global_asset_findings = {
        row.get("asset"): row for row in community_global_asset_scan.get("findings", [])
    }
    expected_iggy_ui_hashes = {
        "Art/UI/character.uasset": "941e57905b698214e7e962a613e486ef512eaa0a48ba09f40abbf1522f58cd70",
        "Art/UI/pause.uasset": "00b46a42a6fc83645ace9f7068b8fc3b34ed7c9abd0c185580abbfb5a7d53ab6",
    }
    expected_comparison_layouts = {
        "Art/UI/character.uasset": {
            "object_count": 541,
            "additional_pointer_field": 4528,
            "relative_targets": {
                "1": {"0x48": {"record_end": 37}},
                "3": {
                    "0x38": {"record_end": 384, "interrecord_tail": 2},
                    "0x40": {"interrecord_tail": 381, "record_end": 5},
                },
                "4": {"0x48": {"record_end": 29}},
                "6": {"0x60": {"record_end": 89}},
            },
            "string_pointer_summary": {
                "objects_checked": 89,
                "object_relative_target_offset_counts": {"104": 89},
                "all_targets_at_104_byte_text_record_end": True,
            },
            "type3_payload_observation": {
                "metadata_type_code": 2,
                "objects_checked": 386,
                "target_location_counts": {"interrecord_tail": 381, "record_end": 5},
                "target_to_next_object_start_distance_counts": {"16": 385, "260632": 1},
                "target_prefix_u64_pair_counts": {"1,1": 386},
            },
            "type4_payload_observation": {
                "metadata_type_code": 2,
                "objects_checked": 29,
                "target_format_counts": {"zlib_complete": 28, "length_prefixed_jpeg": 1},
            },
            "type1_record_end_regions": {
                "1": {
                    "0x48": {
                        "metadata_type_code": 2,
                        "objects_checked": 37,
                        "target_location_counts": {"record_end": 37},
                        "region_byte_length_counts": {"288": 7, "3360": 2, "376": 26, "696": 2},
                        "region_byte_length_mod_8_counts": {"0": 37},
                        "region_start_mod_8_counts": {"0": 37},
                        "region_envelope_counts": {"opaque_nonzero": 37},
                        "distinct_non_sentinel_region_sha256_count": 37,
                        "all_non_sentinel_regions_8_byte_aligned": True,
                    }
                }
            },
            "index_stream_relationship": {
                "stream_count": 2,
                "object_start_matches_disjoint": True,
                "object_start_match_ranges_sequential": True,
                "index_table_definitions_identical": True,
                "object_start_match_count": 541,
                "distinct_object_start_match_count": 541,
                "segments": [
                    {
                        "subfile_index": 1,
                        "index_table_sha256": "46b31b86bdd0156095e6ee176dc50876bf968a0d383a21eb49b22907042bee63",
                        "first_command_end_offset": 184,
                        "first_object_start_offset": 8376,
                        "last_object_start_offset": 1924456,
                        "final_cumulative_offset": 1925812,
                        "first_command_end_delta_from_previous_final": None,
                    },
                    {
                        "subfile_index": 2,
                        "index_table_sha256": "46b31b86bdd0156095e6ee176dc50876bf968a0d383a21eb49b22907042bee63",
                        "first_command_end_offset": 1925816,
                        "first_object_start_offset": 1934720,
                        "last_object_start_offset": 2189096,
                        "final_cumulative_offset": 2460464,
                        "first_command_end_delta_from_previous_final": 4,
                    },
                ],
            },
            "index_matches": [
                {"count": 527, "kinds": {"1": 34, "3": 378, "4": 26, "6": 89}},
                {"count": 14, "kinds": {"1": 3, "3": 8, "4": 3}},
            ],
        },
        "Art/UI/pause.uasset": {
            "object_count": 156,
            "additional_pointer_field": 1448,
            "relative_targets": {
                "1": {"0x48": {"record_end": 11}},
                "3": {
                    "0x38": {"record_end": 110},
                    "0x40": {"interrecord_tail": 107, "record_end": 3},
                },
                "4": {"0x48": {"record_end": 8}},
                "6": {"0x60": {"record_end": 27}},
            },
            "string_pointer_summary": {
                "objects_checked": 27,
                "object_relative_target_offset_counts": {"104": 27},
                "all_targets_at_104_byte_text_record_end": True,
            },
            "type3_payload_observation": {
                "metadata_type_code": 2,
                "objects_checked": 110,
                "target_location_counts": {"interrecord_tail": 107, "record_end": 3},
                "target_to_next_object_start_distance_counts": {"16": 109, "120512": 1},
                "target_prefix_u64_pair_counts": {"1,1": 110},
            },
            "type4_payload_observation": {
                "metadata_type_code": 2,
                "objects_checked": 8,
                "target_format_counts": {"zlib_complete": 7, "length_prefixed_jpeg": 1},
            },
            "type1_record_end_regions": {
                "1": {
                    "0x48": {
                        "metadata_type_code": 2,
                        "objects_checked": 11,
                        "target_location_counts": {"record_end": 11},
                        "region_byte_length_counts": {"288": 3, "376": 7, "696": 1},
                        "region_byte_length_mod_8_counts": {"0": 11},
                        "region_start_mod_8_counts": {"0": 11},
                        "region_envelope_counts": {"opaque_nonzero": 11},
                        "distinct_non_sentinel_region_sha256_count": 11,
                        "all_non_sentinel_regions_8_byte_aligned": True,
                    }
                }
            },
            "index_stream_relationship": {
                "stream_count": 1,
                "object_start_matches_disjoint": True,
                "object_start_match_ranges_sequential": True,
                "index_table_definitions_identical": True,
                "object_start_match_count": 156,
                "distinct_object_start_match_count": 156,
                "segments": [
                    {
                        "subfile_index": 1,
                        "index_table_sha256": "615a08dcddb15b17d6bf61a9ca17ddda8dabe9b9b267e7a348104702830cc7b6",
                        "first_command_end_offset": 184,
                        "first_object_start_offset": 2232,
                        "last_object_start_offset": 886304,
                        "final_cumulative_offset": 1012616,
                        "first_command_end_delta_from_previous_final": None,
                    },
                ],
            },
            "index_matches": [
                {"count": 156, "kinds": {"1": 11, "3": 110, "4": 8, "6": 27}},
            ],
        },
    }
    if {row.get("asset") for row in native_settings_iggy.get("comparison_assets", [])} != set(expected_iggy_ui_hashes):
        fail("Iggy 对照电影集合不完整或出现未预期资产")
    for comparison in native_settings_iggy.get("comparison_assets", []):
        finding = global_asset_findings.get(comparison.get("asset"), {})
        index_summaries = comparison.get("index_subfile_summaries", [])
        movie_size = comparison.get("movie_subfile_size", 0)
        expected_layout = expected_comparison_layouts.get(comparison.get("asset"), {})
        correspondence = comparison.get("object_index_correspondence", {})
        layout_correspondence = comparison.get("object_start_layout_correspondence", {})
        comparison_layouts = comparison.get("object_start_layouts_by_kind", {})
        if (
            finding.get("pak") != comparison.get("pak")
            or finding.get("uncompressed_size") != comparison.get("size")
            or comparison.get("sha256") != expected_iggy_ui_hashes.get(comparison.get("asset"))
            or comparison.get("extraction_verified") is not True
            or comparison.get("extraction_command") != "NativeSettingsAssetWriter extract-iggy"
            or comparison.get("version") != "0x900"
            or comparison.get("platform_bytes") != [1, 64, 1, 3]
            or not index_summaries
            or not movie_size
            or any(row.get("bytes_consumed") != row.get("size") for row in index_summaries)
            or any(row.get("maximum_cumulative_offset") != row.get("final_cumulative_offset") for row in index_summaries)
            or any(row.get("final_cumulative_offset", movie_size + 1) > movie_size for row in index_summaries)
            or not any(row.get("final_cumulative_offset") == movie_size for row in index_summaries)
            or comparison.get("object_pointer_count") != expected_layout.get("object_count")
            or comparison.get("imported_guid_header_value") != 1
            or comparison.get("object_pointer_tables", {}).get("additional_count") != 0
            or comparison.get("object_pointer_tables", {}).get("additional_pointer_field_movie_offset") != expected_layout.get("additional_pointer_field")
            or correspondence.get("distinct_object_starts_matched") != expected_layout.get("object_count")
            or correspondence.get("unmatched_object_start_count") != 0
            or correspondence.get("duplicate_match_count") != 0
            or correspondence.get("every_object_start_matches_exactly_once") is not True
            or [
                {
                    "count": row.get("object_start_match_count"),
                    "kinds": row.get("object_start_matches_by_kind"),
                }
                for row in index_summaries
            ] != expected_layout.get("index_matches")
            or any(row.get("distinct_object_start_match_count") != row.get("object_start_match_count") for row in index_summaries)
            or layout_correspondence.get("object_pointer_count") != expected_layout.get("object_count")
            or layout_correspondence.get("command_start_match_count") != expected_layout.get("object_count")
            or layout_correspondence.get("distinct_object_starts_matched") != expected_layout.get("object_count")
            or layout_correspondence.get("unmatched_object_start_count") != 0
            or layout_correspondence.get("duplicate_match_count") != 0
            or layout_correspondence.get("consistent_record_layout_per_kind") is not True
            or layout_correspondence.get("every_object_start_has_exactly_one_layout_command") is not True
            or set(comparison_layouts) != set(expected_record_sizes)
            or any(
                comparison_layouts[kind].get("object_count") != comparison.get("object_kind_counts", {}).get(kind)
                or comparison_layouts[kind].get("record_size") != size
                or comparison_layouts[kind].get("metadata_descriptors") != settings_layouts[kind].get("metadata_descriptors")
                for kind, size in expected_record_sizes.items()
            )
            or not candidate_directory_matches(comparison, expected_layout.get("object_count"))
            or not relative_target_observations_match(comparison, expected_layout.get("relative_targets", {}))
            or comparison.get("kind_6_string_pointer_summary") != expected_layout.get("string_pointer_summary")
            or not candidate_payload_observations_match(comparison, expected_layout.get("type3_payload_observation"))
            or not candidate_payload_formats_match(comparison, expected_layout.get("type4_payload_observation"))
            or comparison.get("candidate_record_end_region_observations") != expected_layout.get("type1_record_end_regions")
            or canonical_json_sha256(comparison.get("candidate_dual_pointer_observations")) != expected_kind3_dual_pointer_sha256["character" if comparison.get("asset", "").endswith("character.uasset") else "pause"]
            or not index_stream_relationship_matches(comparison, expected_layout.get("index_stream_relationship"))
        ):
            fail("Iggy 对照电影、对象索引对应关系和固定版本全局 PAK 扫描不一致：" + str(comparison.get("asset")))
    writer_source = (ROOT / "Research/tools/native_settings_asset_writer/Program.cs").read_text(encoding="utf-8")
    if (
        f'const string ExpectedBuild = "{native_settings_chain.get("cooked_settings_sha256")}";' not in writer_source
        or '[ExpectedBuild] = "settings"' not in writer_source
        or any(f'["{digest}"] = "{Path(asset).stem}"' not in writer_source for asset, digest in expected_iggy_ui_hashes.items())
    ):
        fail("Iggy 提取工具的固定 UI 资产白名单与研究散列不一致")
    if set(native_settings_text.get("changed_export_paths", [])) != {
        "/0/Properties/TextTable/0/Text/SourceString",
        "/0/Properties/TextTable/0/Text/LocalizedString",
    }:
        fail("原版设置页文字实验出现非目标字段变化")
    if iggy_exports.get("export_count") != 204 or "IggyPlayerCallFunctionRS" not in iggy_exports.get("selected_exports", []):
        fail("Iggy DLL 静态导出摘要不一致")
    if native_ui_runtime.get("target_build") != "16535856" or native_ui_runtime.get("target_executable_sha256") != target.get("sha256"):
        fail("原生 UI 调用点反汇编目标与固定 EXE 散列不符")
    ui_functions = native_ui_runtime.get("functions", {})
    required_ui_calls = {
        "create_movie_player": {"0x7cb060"},
        "create_movie_player_filter": {"0x7cc2e0", "0xa2f090"},
        "push_movie_player": {"0x7dfb80"},
        "push_movie_player_internal": {"0x7cc2e0", "0xa2f090"},
        "get_movie_source_path_info": {"0x74cb20", "0x1b540d0", "0x10ab810"},
        "pass_input_to_iggy": {"0x759c60"},
    }
    for name, callees in required_ui_calls.items():
        summary = ui_functions.get(name, {})
        if summary.get("decode_coverage") != 1.0 or not callees <= set(summary.get("direct_call_targets", [])):
            fail("原生 UI 调用点反汇编证据缺少预期边：" + name)
    native_settings_capability = roguelite.get("runtime_capabilities", {}).get("sod2.ui.native-settings", {})
    if native_settings_capability.get("status") != "static-asset-and-iggy-layout-probe" or native_settings_capability.get("runtime_enabled") is not False:
        fail("原版设置宿主在交互资源未验证前必须保持停用")
    if native_settings_capability.get("native_ui_runtime_candidate_report") != "native-ui-runtime-candidates.json":
        fail("原版设置宿主缺少固定 EXE 播放器调用边报告")
    if native_settings_capability.get("iggy_layout_report") != "native-settings-iggy-compatibility.json":
        fail("原版设置宿主缺少 Iggy 布局结构报告")
    native_ui_movies = native_ui_screen_adapters.get("movies", {})
    character_movie = native_ui_movies.get("character", {})
    community_movie = native_ui_movies.get("community", {})
    character_traits = character_movie.get("trait_extension", {})
    community_extension = community_movie.get("community_extension", {})
    if (
        native_ui_screen_adapters.get("schema") != 1
        or native_ui_screen_adapters.get("target_build") != 16535856
        or native_ui_screen_adapters.get("target_executable_sha256", "").upper() != str(target.get("sha256", "")).upper()
        or character_movie.get("asset") != "Art/UI/character.uasset"
        or character_movie.get("uasset_sha256") != "941e57905b698214e7e962a613e486ef512eaa0a48ba09f40abbf1522f58cd70"
        or character_movie.get("abc_sha256") != "143f089353e5ed0504db2dd8d2c59eb318c037228275dd203ce5486b4c421800"
        or character_movie.get("root_class") != "character"
        or character_traits.get("initial_widget_pool_capacity") != 4
        or character_traits.get("returns_without_adding_when_pool_empty") is not True
        or community_movie.get("asset") != "Art/UI/community.uasset"
        or community_movie.get("uasset_sha256") != "9e4454e8ddfd417a83c1995e48eaaed4a114e5e95808039f2decbb0342bec001"
        or community_movie.get("abc_sha256") != "eb62171b84bc1deb5b45ce723e1668fd5d85023357d92e24ebb5915b732484aa"
        or community_movie.get("root_class") != "community"
        or community_extension.get("creates_character_overlay_for_new_ids") is not True
        or community_extension.get("clear_all_characters_resets_collections") is not True
        or native_ui_screen_adapters.get("decompiler", {}).get("version") != "26.3.0"
        or len(native_ui_screen_adapters.get("static_only_limitations", [])) < 4
        or "High for a reusable cross-screen framework" not in native_ui_screen_adapters.get("framework_assessment", {}).get("overall_complexity", "")
    ):
        fail("角色/社区原版 UI 静态资源分析与证据边界不一致")
    hud_movie = native_ui_movies.get("hud", {})
    hud_extension = hud_movie.get("hud_extension", {})
    if (
        hud_movie.get("asset") != "Art/UI/hud.uasset"
        or hud_movie.get("uasset_sha256") != "9875c79a3afd5c0cd5ef4c9c5df91e55e5f069cb0ab97d9ce161a59fbf80b5cc"
        or hud_movie.get("iggy_sha256") != "00da0e3e3ccabb57508f42744ad8b333ebc81be6da9b0cfedc5966ce264d2eae"
        or hud_movie.get("abc_sha256") != "d13f771fb546d8d9f3f3262cd19c06ba7b0d3ff234760276d4d8d8858edb2751"
        or hud_movie.get("root_class") != "hud"
        or hud_movie.get("other_hud_movie_api_count") != 125
        or hud_extension.get("notification", {}).get("auto_hide_after_ms") != 3000
        or hud_extension.get("notification", {}).get("persistent_progress_display") is not False
        or hud_extension.get("effect_bubbles", {}).get("creates_movie_clip_and_adds_to_display_list") is not True
        or hud_extension.get("effect_bubbles", {}).get("reuses_removed_movie_clips") is not True
        or hud_extension.get("effect_bubbles", {}).get("unknown_update_or_remove_id_throws") is not True
        or "not a general menu" not in hud_extension.get("effect_bubbles", {}).get("interpretation", "")
    ):
        fail("HUD 原版 Iggy 适配证据或能力边界不一致")
    map_movie = native_ui_movies.get("map", {})
    map_extension = map_movie.get("map_extension", {})
    map_locations = map_extension.get("objective_locations", {})
    map_section = map_movie.get("abc_section", {})
    if (
        map_movie.get("asset") != "Art/UI/map.uasset"
        or map_movie.get("uasset_sha256") != "f91806d92ea18b12440bb0117d012fb20d3f9ab472c2841ab95d858083319945"
        or map_movie.get("iggy_sha256") != "706d317873a3ac91a0b1f338f568b4d2e63134fdd751104ca05f56b5600f0951"
        or map_movie.get("abc_sha256") != "92c057dda613057de6c84aeb05fce28e4e6faaf6a05680f40151e10c3740c9ca"
        or map_movie.get("root_class") != "map"
        or map_movie.get("other_map_movie_api_count") != 177
        or map_section.get("block_count") != 349
        or map_section.get("abc_total_length") != 585914
        or map_section.get("trailing_padding_length") != 4
        or map_section.get("trailing_padding_all_zero") is not True
        or map_locations.get("requires_preexisting_objective_handle") is not True
        or map_locations.get("new_location_is_shown_only_when_objective_has_owning_mission") is not True
        or map_locations.get("remove_uses_objective_and_location_handles") is not True
        or map_extension.get("custom_interactive_controls") is not False
        or "standalone arbitrary-marker" not in map_locations.get("interpretation", "")
    ):
        fail("Map 原版 Iggy 分块解析或 Objective Location 适配证据不一致")
    trait_probe = native_character_trait_pool_probe.get("patch", {})
    source_recompile = native_ui_screen_adapters.get("asset_editing_experiments", {}).get("source_recompile", {})
    same_length_probe = native_ui_screen_adapters.get("asset_editing_experiments", {}).get("same_length_character_trait_pool_probe", {})
    if (
        native_character_trait_pool_probe.get("schema") != 1
        or native_character_trait_pool_probe.get("target_build") != 16535856
        or native_character_trait_pool_probe.get("asset") != "Art/UI/character.uasset"
        or native_character_trait_pool_probe.get("source_uasset_sha256") != "941e57905b698214e7e962a613e486ef512eaa0a48ba09f40abbf1522f58cd70"
        or native_character_trait_pool_probe.get("source_iggy_sha256") != character_movie.get("iggy_sha256")
        or trait_probe.get("method") != "single guarded AVM2 pushbyte immediate rewrite; no source recompilation"
        or trait_probe.get("old_value") != 4
        or trait_probe.get("new_value") != 6
        or trait_probe.get("changed_byte_count") != 1
        or trait_probe.get("ffdec_decompile_confirms_new_capacity") is not True
        or native_character_trait_pool_probe.get("movie_size_unchanged") is not True
        or native_character_trait_pool_probe.get("index_stream_ends_at_movie_boundary") is not True
        or native_character_trait_pool_probe.get("output_loaded_in_game") is not False
        or source_recompile.get("original_character_abc_bytes") != 244745
        or source_recompile.get("ffdec_imported_character_abc_bytes") != 353302
        or source_recompile.get("accepted_as_valid_asset") is not False
        or same_length_probe.get("report") != "native-character-trait-pool-probe.json"
        or same_length_probe.get("changed_byte_count") != 1
        or same_length_probe.get("output_loaded_in_game") is not False
        or same_length_probe.get("uasset_wrap_test", {}).get("tool") != "NativeSettingsAssetWriter replace-iggy"
        or same_length_probe.get("uasset_wrap_test", {}).get("output_uasset_sha256") != "5aef5e62a1ac2f3f00e5c17e9ee4269d6794f0306413d29eefc10c5cc1e51e64"
        or same_length_probe.get("uasset_wrap_test", {}).get("uasset_size_bytes") != 2554832
        or same_length_probe.get("uasset_wrap_test", {}).get("changed_byte_count") != 1
        or same_length_probe.get("uasset_wrap_test", {}).get("changed_byte_offset") != 2469842
        or same_length_probe.get("uasset_wrap_test", {}).get("cue4parse_reparsed") is not True
        or same_length_probe.get("uasset_wrap_test", {}).get("output_loaded_in_game") is not False
        or len(native_character_trait_pool_probe.get("limitations", [])) < 4
    ):
        fail("Character Iggy 特质池单字节实验或 FFDec 重编写否决证据不一致")
    sha = str(target.get("sha256", ""))
    if not re.fullmatch(r"[0-9A-Fa-f]{64}", sha):
        fail("target.json 的 SHA256 无效")
    if database.get("target_sha256", sha).upper() != sha.upper():
        fail("patches.json 的 target_sha256 与 target.json 不一致")

    patches = database.get("patches", [])
    if len(patches) != 13:
        fail("统一补丁数量应为 13，实际为 %d" % len(patches))
    patch_ids = set()
    patch_names = set()
    patch_sources = set()
    for patch in patches:
        for key in ("id", "plugin", "manifest", "name", "original", "replacement", "guard_original"):
            if not patch.get(key):
                fail("补丁缺少字段：" + key)
        if patch["id"] in patch_ids:
            fail("重复补丁 ID：" + patch["id"])
        patch_ids.add(patch["id"])
        patch_sources.add(str(patch.get("source", "")))
        key = (patch["plugin"], patch["name"])
        if key in patch_names:
            fail("同一插件重复补丁名称：" + repr(key))
        patch_names.add(key)
        if int(patch["rva"]) < 0 or int(patch["guard_rva"]) < 0:
            fail("补丁 RVA 不能为负数：" + patch["id"])
        if len(bytes.fromhex(patch["original"])) != len(bytes.fromhex(patch["replacement"])):
            fail("补丁写入长度不一致：" + patch["id"])
        guard_start = int(patch["guard_rva"])
        guard_end = guard_start + len(bytes.fromhex(patch["guard_original"]))
        write_end = int(patch["rva"]) + len(bytes.fromhex(patch["original"]))
        if guard_start > int(patch["rva"]) or guard_end < write_end:
            fail("guard 没有覆盖写入区：" + patch["id"])
    if patch_sources != {"GameApi/StateOfDecay2GameApi.cs"}:
        fail("版本专用补丁必须由唯一 Game API 源文件提供：" + repr(sorted(patch_sources)))

    function_ids = set()
    for function in functions.get("functions", []):
        if "direct_callers" in function:
            fail("functions.json 不得保留来源不明的 direct_callers 计数；直接调用证据在 native-body-analysis.json")
        if function.get("id") in function_ids:
            fail("重复函数 ID：" + str(function.get("id")))
        function_ids.add(function.get("id"))
        for patch_id in function.get("patch_ids", []):
            if patch_id not in patch_ids:
                fail("函数引用了不存在的补丁：" + patch_id)
        if "rva" in function and not re.fullmatch(r"0x[0-9A-Fa-f]+", str(function["rva"])):
            fail("函数 RVA 不是十六进制：" + str(function.get("id")))
        if "prologue_guard" in function:
            try:
                bytes.fromhex(function["prologue_guard"])
            except (TypeError, ValueError):
                fail("函数前导 guard 不是有效十六进制：" + str(function.get("id")))

    struct_ids = set()
    for struct in structs.get("structures", []):
        if struct.get("id") in struct_ids:
            fail("重复结构体 ID：" + str(struct.get("id")))
        struct_ids.add(struct.get("id"))
        for field in struct.get("fields", []):
            offset = str(field.get("offset", ""))
            if not (re.fullmatch(r"0x[0-9A-Fa-f]+", offset) or
                    re.fullmatch(r"bits?\s+[0-9]+(\.\.[0-9]+)?", offset)):
                fail("结构体字段偏移无效：" + str(struct.get("id")))

    if domains.get("target") != "target.json":
        fail("research-domains.json 指向了错误的目标版本")
    domain_ids = set()
    domain_names = {}
    for domain in domains.get("domains", []):
        domain_id = str(domain.get("id", ""))
        if not domain_id or domain_id in domain_ids:
            fail("研究域 ID 为空或重复：" + domain_id)
        domain_ids.add(domain_id)
        if domain.get("status") != "candidate-only":
            fail("未验证的研究域必须保持 candidate-only：" + domain_id)
        candidates = domain.get("native_candidates", [])
        if not candidates or len(candidates) != len(set(candidates)):
            fail("研究域候选为空或有重复名称：" + domain_id)
        domain_names[domain_id] = set(candidates)

    if body_analysis.get("target_sha256", "").upper() != sha.upper():
        fail("native-body-analysis.json 的 SHA256 与目标 EXE 不一致")
    body_xref_stats = body_analysis.get("direct_call_xrefs", {}).get("statistics", {})
    expected_full_target_count = body_xref_stats.get("target_count")
    if (
        full_pdata_xrefs.get("schema") != 1
        or full_pdata_xrefs.get("target") != "target.json"
        or full_pdata_xrefs.get("target_sha256", "").upper() != sha.upper()
        or full_pdata_xrefs.get("scope", {}).get("game_process_started_or_attached") is not False
        or full_pdata_xrefs.get("scope", {}).get("selected_target_count") != expected_full_target_count
        or full_pdata_xrefs.get("scope", {}).get("executable_pdata_function_ranges") != 259728
        or full_pdata_xrefs.get("scope", {}).get("decoded_function_bodies") != 259728
        or full_pdata_xrefs.get("scope", {}).get("skipped_function_bodies") != 0
        or full_pdata_xrefs.get("scope", {}).get("partially_decoded_function_bodies") != 675
        or full_pdata_xrefs.get("scope", {}).get("direct_call_edges") != sum(row.get("direct_call_count", 0) for row in full_pdata_xrefs.get("targets", []))
        or full_pdata_xrefs.get("scope", {}).get("tail_jump_edges") != sum(row.get("tail_jump_count", 0) for row in full_pdata_xrefs.get("targets", []))
    ):
        fail("全量 .pdata 直接调用清点的版本、范围或覆盖统计不符")
    if (
        full_pdata_xref_audit.get("schema") != 1
        or full_pdata_xref_audit.get("target") != "target.json"
        or full_pdata_xref_audit.get("target_sha256", "").upper() != sha.upper()
        or full_pdata_xref_audit.get("source_report") != "native-full-pdata-direct-xrefs.json"
        or full_pdata_xref_audit.get("scope", {}).get("game_process_started_or_attached") is not False
        or full_pdata_xref_audit.get("scope", {}).get("target_count") != expected_full_target_count
        or full_pdata_xref_audit.get("scope", {}).get("raw_e8_candidate_count") != full_pdata_xrefs.get("scope", {}).get("direct_call_edges")
        or full_pdata_xref_audit.get("scope", {}).get("decoded_e8_call_count") != full_pdata_xrefs.get("scope", {}).get("direct_call_edges")
        or full_pdata_xref_audit.get("scope", {}).get("unmatched_raw_e8_site_count") != 0
        or full_pdata_xref_audit.get("scope", {}).get("decoded_calls_without_raw_e8_count") != 0
        or full_pdata_xref_audit.get("scope", {}).get("unmatched_raw_e9_site_count") != len(full_pdata_xref_audit.get("unmatched_raw_e9_sites", []))
        or full_pdata_xref_audit.get("scope", {}).get("unmatched_raw_e9_inside_partial_body_count") != 0
        or full_pdata_xref_audit.get("scope", {}).get("all_e8_candidates_match_decoded_calls") is not True
    ):
        fail("全量 .pdata E8/E9 独立字节扫描交叉核验结果不符")
    full_targets = full_pdata_xrefs.get("targets", [])
    full_audit_targets = full_pdata_xref_audit.get("targets", [])
    full_targets_by_rva = {row.get("target_rva"): row for row in full_targets}
    full_audit_by_rva = {row.get("target_rva"): row for row in full_audit_targets}
    if (
        len(full_targets) != expected_full_target_count
        or len(full_targets_by_rva) != expected_full_target_count
        or set(full_targets_by_rva) != {row.get("target_rva") for row in body_analysis.get("direct_call_xrefs", {}).get("targets", [])}
        or set(full_targets_by_rva) != set(full_audit_by_rva)
        or any(
            row.get("raw_e8_sites_all_match_decoded_calls") is not True
            or row.get("unmatched_raw_e8_sites")
            or row.get("decoded_calls_without_raw_e8")
            or row.get("raw_e8_candidate_count") != full_targets_by_rva[rva].get("direct_call_count")
            or row.get("decoded_direct_call_count") != full_targets_by_rva[rva].get("direct_call_count")
            for rva, row in full_audit_by_rva.items()
        )
    ):
        fail("全量 .pdata 直接调用逐目标 E8 交叉核验失败")

    expected_followup_call_counts = {
        "0x1cf9ca": 0,
        "0x1e53ab": 0,
        "0x276e80": 0,
        "0x29a690": 6,
        "0x2bbd8b": 0,
        "0x3292c7": 0,
        "0x3c92e4": 0,
        "0x461993": 0,
    }
    followup_targets = roguelite_followup_xrefs.get("targets", [])
    followup_by_rva = {row.get("target_rva"): row for row in followup_targets}
    followup_audit_targets = roguelite_followup_xref_audit.get("targets", [])
    followup_audit_by_rva = {row.get("target_rva"): row for row in followup_audit_targets}
    if (
        roguelite_followup_xrefs.get("schema") != 1
        or roguelite_followup_xrefs.get("report_name") != "roguelite-native-followup-direct-xrefs.json"
        or roguelite_followup_xrefs.get("target") != "target.json"
        or roguelite_followup_xrefs.get("target_sha256", "").upper() != sha.upper()
        or roguelite_followup_xrefs.get("scope", {}).get("game_process_started_or_attached") is not False
        or roguelite_followup_xrefs.get("scope", {}).get("selected_target_count") != 8
        or roguelite_followup_xrefs.get("scope", {}).get("executable_pdata_function_ranges") != 259728
        or roguelite_followup_xrefs.get("scope", {}).get("decoded_function_bodies") != 259728
        or roguelite_followup_xrefs.get("scope", {}).get("partially_decoded_function_bodies") != 675
        or roguelite_followup_xrefs.get("scope", {}).get("direct_call_edges") != 6
        or roguelite_followup_xrefs.get("scope", {}).get("tail_jump_edges") != 0
        or set(followup_by_rva) != set(expected_followup_call_counts)
        or len(followup_targets) != len(followup_by_rva)
        or any(followup_by_rva[rva].get("direct_call_count") != count
               for rva, count in expected_followup_call_counts.items())
        or any(followup_by_rva[rva].get("tail_jump_count") != 0
               for rva in expected_followup_call_counts)
        or followup_by_rva["0x1cf9ca"].get("target_kinds") != ["roguelite-followup-chaininfo-fragment-start"]
        or not any(
            row.get("target_rva") == "0x1cf9ca"
            and row.get("target_kind") == "roguelite-followup-chaininfo-fragment-start"
            and "CHAININFO-linked subrange" in row.get("candidate_reason", "")
            for row in roguelite_followup_xrefs.get("focus_sources", [])
        )
        or len(followup_by_rva["0x29a690"].get("direct_callers", [])) != 6
        or any(row.get("caller_function_range_rva", {}).get("start") != "0x2bbd8b"
               for row in followup_by_rva["0x29a690"].get("direct_callers", []))
    ):
        fail("幸存者成长匿名入口全量 .pdata 跟进结果不符")
    if (
        roguelite_followup_xref_audit.get("schema") != 1
        or roguelite_followup_xref_audit.get("target_sha256", "").upper() != sha.upper()
        or roguelite_followup_xref_audit.get("source_report") != "roguelite-native-followup-direct-xrefs.json"
        or roguelite_followup_xref_audit.get("scope", {}).get("target_count") != 8
        or roguelite_followup_xref_audit.get("scope", {}).get("raw_e8_candidate_count") != 6
        or roguelite_followup_xref_audit.get("scope", {}).get("decoded_e8_call_count") != 6
        or roguelite_followup_xref_audit.get("scope", {}).get("unmatched_raw_e8_site_count") != 0
        or roguelite_followup_xref_audit.get("scope", {}).get("raw_e9_candidate_count") != 0
        or roguelite_followup_xref_audit.get("scope", {}).get("unmatched_raw_e9_site_count") != 0
        or roguelite_followup_xref_audit.get("scope", {}).get("all_e8_candidates_match_decoded_calls") is not True
        or set(followup_audit_by_rva) != set(expected_followup_call_counts)
        or any(row.get("raw_e8_sites_all_match_decoded_calls") is not True
               for row in followup_audit_targets)
    ):
        fail("幸存者成长匿名入口的 E8/E9 独立字节核验失败")

    address_targets = roguelite_followup_address_refs.get("targets", [])
    address_by_rva = {row.get("target_rva"): row for row in address_targets}
    expected_rva32_counts = {
        "0x1cf9ca": 2,
        "0x1e53ab": 2,
        "0x276e80": 0,
        "0x29a690": 0,
        "0x2bbd8b": 2,
        "0x3292c7": 0,
        "0x3c92e4": 0,
        "0x461993": 2,
    }
    if (
        roguelite_followup_address_refs.get("schema") != 1
        or roguelite_followup_address_refs.get("target_sha256", "").upper() != sha.upper()
        or roguelite_followup_address_refs.get("scope", {}).get("game_process_started_or_attached") is not False
        or roguelite_followup_address_refs.get("scope", {}).get("executable_pdata_function_ranges") != 259728
        or roguelite_followup_address_refs.get("scope", {}).get("target_count") != 8
        or roguelite_followup_address_refs.get("scope", {}).get("excluded_exception_directory_section") != ".pdata"
        or set(address_by_rva) != set(expected_rva32_counts)
        or len(address_targets) != 8
        or any(row.get("non_branch_instruction_reference_count") != 0 for row in address_targets)
        or any(len(address_by_rva[rva].get("rva_dword_candidates", [])) != count
               for rva, count in expected_rva32_counts.items())
        or len(address_by_rva["0x276e80"].get("absolute_va_qword_candidates", [])) != 1
        or any(
            candidate.get("section") != ".rdata" or candidate.get("target_is_executable") is not True
            for row in address_targets
            for candidate in row.get("absolute_va_qword_candidates", []) + row.get("rva_dword_candidates", [])
        )
    ):
        fail("幸存者成长匿名入口的代码/数据地址引用候选报告不符")

    kill_disassembly_rows = roguelite_kill_experience_disassembly.get("functions", [])
    kill_disassembly_by_rva = {row.get("rva"): row for row in kill_disassembly_rows}
    expected_kill_disassembly_rvas = {
        "0xa8afd0", "0xa8c600", "0xa8c680", "0x19e900", "0x19ef80",
        "0x1cf910", "0xaefd50", "0xa8b590", "0xada660", "0x3c92e4",
        "0x3292c7", "0x461993", "0x1e53ab", "0x276e80",
    }
    on_zombie_calls = kill_disassembly_by_rva.get("0xaefd50", {}).get("direct_calls", [])
    auth_on_zombie_calls = kill_disassembly_by_rva.get("0xa8b590", {}).get("direct_calls", [])
    killed_zombie_indirect_calls = kill_disassembly_by_rva.get("0xada660", {}).get("indirect_calls", [])
    if (
        roguelite_kill_experience_disassembly.get("schema") != 1
        or roguelite_kill_experience_disassembly.get("target") != "target.json"
        or roguelite_kill_experience_disassembly.get("target_sha256", "").upper() != sha.upper()
        or roguelite_kill_experience_disassembly.get("scope", {}).get("game_process_started_or_attached") is not False
        or roguelite_kill_experience_disassembly.get("scope", {}).get("function_count") != 14
        or set(kill_disassembly_by_rva) != expected_kill_disassembly_rvas
        or sum(len(row.get("direct_calls", [])) for row in kill_disassembly_rows) != 128
        or sum(len(row.get("indirect_calls", [])) for row in kill_disassembly_rows) != 10
        or not any(row.get("site_rva") == "0xaefdc3" and row.get("target_rva") == "0x253ed0" for row in on_zombie_calls)
        or not any(row.get("site_rva") == "0xa8b63e" and row.get("target_rva") == "0x3dbfe0" for row in auth_on_zombie_calls)
        or killed_zombie_indirect_calls != [{"site_rva": "0xada796", "operand": "qword ptr [r10 + 0xb00]"}]
    ):
        fail("幸存者成长击杀/经验定向机器码调用摘要不符")

    experience_call_sites = roguelite_experience_blueprint_call_contexts.get("call_sites", [])
    experience_target_counts = Counter(row.get("target") for row in experience_call_sites)
    experience_melee_sites = [
        row for row in experience_call_sites
        if row.get("blueprint_function") == "AwardZombieMeleeExperience"
    ]
    experience_ranged_sites = [
        row for row in experience_call_sites
        if row.get("blueprint_function") == "AwardZombieRangedExperience"
    ]
    melee_tag_values = {
        assignment.get("expression", {}).get("value")
        for site in experience_melee_sites
        for local in site.get("related_local_assignments", [])
        for assignment in local.get("assignments", [])
        if assignment.get("expression", {}).get("inst") == "EX_NameConst"
    }
    ranged_nodes = [
        node
        for site in experience_ranged_sites
        for local in site.get("related_local_assignments", [])
        for assignment in local.get("assignments", [])
        for node in walk_json_nodes(assignment.get("expression", {}))
    ]
    ranged_literals = {
        (node.get("inst"), node.get("value"))
        for node in ranged_nodes
        if node.get("inst") in {"EX_StringConst", "EX_ByteConst"}
    }
    ranged_switch_cases = {
        (case.get("caseIndexValueTerm", {}).get("value"), case.get("caseTerm", {}).get("variable"))
        for node in ranged_nodes if node.get("inst") == "EX_SwitchValue"
        for case in node.get("cases", [])
    }
    delayed_death_site = next((
        row for row in experience_call_sites
        if row.get("asset_path") == "StateOfDecay2/Content/Characters/Zombie/ZombieFullBodyAction.uasset"
        and row.get("blueprint_function") == "OnDelayedDeath"
    ), {})
    delayed_death_parameters = delayed_death_site.get("parameters", [])
    experience_call_context_statistics = roguelite.get("extraction", {}).get(
        "roguelite_experience_blueprint_call_contexts_statistics", {}
    )
    if (
        roguelite_experience_blueprint_call_contexts.get("schema") != 1
        or roguelite_experience_blueprint_call_contexts.get("target") != "target.json"
        or roguelite_experience_blueprint_call_contexts.get("target_sha256", "").upper() != sha.upper()
        or roguelite_experience_blueprint_call_contexts.get("source_call_census") != "community-full-uasset-roguelite-call-analysis.json"
        or roguelite_experience_blueprint_call_contexts.get("scope", {}).get("game_process_started_or_attached") is not False
        or roguelite_experience_blueprint_call_contexts.get("scope", {}).get("selected_asset_count") != 7
        or roguelite_experience_blueprint_call_contexts.get("scope", {}).get("selected_function_count") != 13
        or roguelite_experience_blueprint_call_contexts.get("scope", {}).get("serialized_award_call_count") != 37
        or experience_target_counts != Counter({
            "Function'CharacterBlueprintHelpers:AuthAwardExperience'": 34,
            "Function'CharacterSkill:AwardExperience'": 1,
            "Function'DaytonCharacter:AwardExperience'": 2,
        })
        or experience_call_context_statistics.get("game_process_started_or_attached") is not False
        or experience_call_context_statistics.get("selected_asset_count") != 7
        or experience_call_context_statistics.get("selected_function_count") != 13
        or experience_call_context_statistics.get("serialized_award_call_count") != 37
        or experience_call_context_statistics.get("auth_award_experience_call_count") != 34
        or experience_call_context_statistics.get("character_skill_award_experience_call_count") != 1
        or experience_call_context_statistics.get("dayton_character_award_experience_call_count") != 2
        or "Research/tools/analyze_roguelite_experience_blueprint_call_contexts.py" not in roguelite.get("extraction", {}).get("tools", [])
        or roguelite.get("extraction", {}).get("roguelite_experience_blueprint_call_contexts_report") != "roguelite-experience-blueprint-call-contexts.json"
        or len(experience_melee_sites) != 4
        or any(
            len(site.get("parameters", [])) != 2
            or not isinstance(site["parameters"][1], dict)
            or site["parameters"][1].get("inst") != "EX_SwitchValue"
            for site in experience_melee_sites
        )
        or melee_tag_values != {
            "Fighting_Zombie_Close_Lethal", "Fighting_Zombie_Close_Nonlethal",
            "Fighting_Zombie_Blunt_Lethal", "Fighting_Zombie_Blunt_Nonlethal",
            "Fighting_Zombie_Bladed_Lethal", "Fighting_Zombie_Bladed_Nonlethal",
            "Fighting_Zombie_Heavy_Lethal", "Fighting_Zombie_Heavy_Nonlethal",
        }
        or len(experience_ranged_sites) != 1
        or not {("EX_StringConst", "Shooting_Zombie_"), ("EX_StringConst", "Lethal"), ("EX_StringConst", "Nonlethal")}.issubset(ranged_literals)
        or not {(0, "Temp_string_Variable2"), (1, "Temp_string_Variable")}.issubset(ranged_switch_cases)
        or len(delayed_death_parameters) != 2
        or delayed_death_parameters[0].get("variable") != "ReactAttacker"
        or delayed_death_parameters[1].get("value") != "Explosive_Zombie_Lethal"
        or not all(len(value) == 64 for value in roguelite_experience_blueprint_call_contexts.get("scope", {}).get("selected_assets_sha256", {}).values())
    ):
        fail("经验奖励 Blueprint 调用参数、局部赋值链或来源清单不符")

    reward_table_rows = roguelite_experience_reward_table.get("reward_rows", [])
    reward_rows_by_name = {row.get("row_name"): row for row in reward_table_rows}
    reward_call_tags = roguelite_experience_reward_table.get("referenced_call_tags", {})
    reward_table_statistics = roguelite_experience_reward_table.get("scope", {})
    capability_reward_statistics = roguelite.get("extraction", {}).get(
        "roguelite_experience_reward_table_statistics", {}
    )
    _shooting_lethal = reward_call_tags.get("Shooting_Zombie_Lethal", {}).get("table_skill_rewards", [])
    _shooting_nonlethal = reward_call_tags.get("Shooting_Zombie_Nonlethal", {}).get("table_skill_rewards", [])
    _stealth = reward_call_tags.get("Wits_StealthKills", {}).get("table_skill_rewards", [])
    _explosive_lethal = {
        row.get("skill_definition"): row.get("experience")
        for row in reward_call_tags.get("Explosive_Zombie_Lethal", {}).get("table_skill_rewards", [])
    }
    _explosive_nonlethal = {
        row.get("skill_definition"): row.get("experience")
        for row in reward_call_tags.get("Explosive_Zombie_Nonlethal", {}).get("table_skill_rewards", [])
    }
    _explosive_lethal_expected = {
        "CharacterSkillDefinition'ChemistryDefinition'": 2.0,
        "CharacterSkillDefinition'MunitionsDefinition'": 3.0,
        "CharacterSkillDefinition'HL_AnarchyDefinition'": 3.0,
        "CharacterSkillDefinition'HL_InventionDefinition'": 3.0,
    }
    if (
        roguelite_experience_reward_table.get("schema") != 1
        or roguelite_experience_reward_table.get("target") != "target.json"
        or roguelite_experience_reward_table.get("target_sha256", "").upper() != sha.upper()
        or roguelite_experience_reward_table.get("source_call_context_report") != "roguelite-experience-blueprint-call-contexts.json"
        or roguelite_experience_reward_table.get("source_call_context_sha256") != sha256_file(DATABASE / "roguelite-experience-blueprint-call-contexts.json")
        or reward_table_statistics.get("game_process_started_or_attached") is not False
        or reward_table_statistics.get("table_row_struct") != "ScriptStruct'ExperienceReward'"
        or reward_table_statistics.get("reward_table_row_count") != 28
        or len(reward_rows_by_name) != 28
        or reward_table_statistics.get("call_context_site_count") != 37
        or reward_table_statistics.get("call_site_tag_candidate_count") != 16
        or reward_table_statistics.get("matched_call_tag_count") != 16
        or reward_table_statistics.get("unmatched_call_tag_candidates") != []
        or not set(reward_call_tags).issubset(reward_rows_by_name)
        or any(not row.get("table_row_found") for row in reward_call_tags.values())
        or len(_shooting_lethal) != 6
        or {row.get("experience") for row in _shooting_lethal} != {50.0}
        or len(_shooting_nonlethal) != 6
        or {row.get("experience") for row in _shooting_nonlethal} != {5.0}
        or len(_stealth) != 10
        or {row.get("experience") for row in _stealth} != {50.0}
        or _explosive_lethal != _explosive_lethal_expected
        or _explosive_nonlethal != {name: 1.0 for name in _explosive_lethal_expected}
        or capability_reward_statistics.get("game_process_started_or_attached") is not False
        or capability_reward_statistics.get("reward_table_row_count") != 28
        or capability_reward_statistics.get("call_context_site_count") != 37
        or capability_reward_statistics.get("call_site_tag_candidate_count") != 16
        or capability_reward_statistics.get("matched_call_tag_count") != 16
        or capability_reward_statistics.get("unmatched_call_tag_candidate_count") != 0
        or roguelite.get("extraction", {}).get("roguelite_experience_reward_table_report") != "roguelite-experience-reward-table.json"
        or "Research/tools/analyze_roguelite_experience_reward_table.py" not in roguelite.get("extraction", {}).get("tools", [])
        or len(roguelite_experience_reward_table.get("source_table_sha256", "")) != 64
        or any(character not in "0123456789ABCDEF" for character in roguelite_experience_reward_table.get("source_table_sha256", "").upper())
    ):
        fail("ExperienceRewards 表行、标签连接或经验数值证据不符")

    extraction = roguelite.get("extraction", {})
    if extraction.get("body_analysis_report") != "native-body-analysis.json":
        fail("roguelite-capabilities.json 没有引用派生函数体分析报告")
    if "Research/tools/analyze_native_bodies.py" not in extraction.get("tools", []):
        fail("roguelite-capabilities.json 没有登记函数体分析工具")
    if (
        extraction.get("full_pdata_direct_xref_report") != "native-full-pdata-direct-xrefs.json"
        or extraction.get("full_pdata_direct_xref_audit_report") != "native-full-pdata-direct-xrefs-audit.json"
        or extraction.get("full_pdata_direct_xref_statistics", {}).get("direct_call_edges") != full_pdata_xrefs.get("scope", {}).get("direct_call_edges")
        or extraction.get("full_pdata_direct_xref_audit_statistics", {}).get("unmatched_raw_e8_site_count") != 0
    ):
        fail("roguelite-capabilities.json 未引用完整 .pdata 直接调用清点与交叉审计")
    if (
        extraction.get("roguelite_followup_direct_xref_report") != "roguelite-native-followup-direct-xrefs.json"
        or extraction.get("roguelite_followup_direct_xref_audit_report") != "roguelite-native-followup-direct-xrefs-audit.json"
        or extraction.get("roguelite_followup_address_reference_report") != "roguelite-native-followup-address-references.json"
        or extraction.get("roguelite_followup_direct_xref_statistics", {}).get("direct_call_edges") != 6
        or extraction.get("roguelite_followup_direct_xref_audit_statistics", {}).get("unmatched_raw_e8_site_count") != 0
    ):
        fail("roguelite-capabilities.json 未引用匿名入口跟进与地址引用报告")
    kill_disassembly_stats = extraction.get("roguelite_kill_experience_disassembly_statistics", {})
    if (
        extraction.get("roguelite_kill_experience_disassembly_report") != "roguelite-kill-experience-disassembly.json"
        or kill_disassembly_stats.get("game_process_started_or_attached") is not False
        or kill_disassembly_stats.get("function_count") != 14
        or kill_disassembly_stats.get("direct_call_count") != 128
        or kill_disassembly_stats.get("indirect_call_count") != 10
        or kill_disassembly_stats.get("pdata_range_count") != 26
        or "Research/tools/analyze_roguelite_kill_experience_disassembly.py" not in extraction.get("tools", [])
    ):
        fail("roguelite-capabilities.json 未引用击杀/经验定向机器码报告")
    enemy_finding = roguelite.get("static_findings", {}).get("enemy_classification", {})
    if (
        extraction.get("roguelite_enemy_classification_report") != "roguelite-enemy-classification-static.json"
        or extraction.get("roguelite_native_zombie_variant_enum_report") != "zombie-variant-enum-native-registration.json"
        or "Research/tools/analyze_zombie_variant_enum_native_registration.py" not in extraction.get("tools", [])
        or extraction.get("roguelite_native_plague_flag_name_reference_report") != "zombie-plague-flag-native-name-references.json"
        or "Research/tools/analyze_native_plague_flag_name_references.py" not in extraction.get("tools", [])
        or extraction.get("roguelite_enemy_classification_statistics", {}).get("enum_usage_json_files") != 105357
        or extraction.get("roguelite_enemy_classification_statistics", {}).get("enum_value_reference_count") != 6
        or extraction.get("roguelite_enemy_classification_statistics", {}).get("zombie_type_table_row_count") != 17
        or extraction.get("roguelite_enemy_classification_statistics", {}).get("boons_banes_density_category_count") != 9
        or extraction.get("roguelite_enemy_classification_statistics", {}).get("normal_plague_preset_is_plague_zombie") is not True
        or extraction.get("roguelite_enemy_classification_statistics", {}).get("blood_plague_special_construction_assignments") != 4
        or extraction.get("roguelite_enemy_classification_statistics", {}).get("plague_variant_appearance_row_count") != 3
        or extraction.get("roguelite_enemy_classification_statistics", {}).get("generic_appearance_plague_flag_writes") != 2
        or extraction.get("roguelite_enemy_classification_statistics", {}).get("serialized_plague_flag_candidate_asset_count") != 47
        or extraction.get("roguelite_enemy_classification_statistics", {}).get("serialized_plague_flag_bytecode_assignment_count") != 11
        or enemy_finding.get("serialized_export_report") != "roguelite-enemy-classification-static.json"
        or enemy_finding.get("native_enum_registration_report") != "zombie-variant-enum-native-registration.json"
        or enemy_finding.get("native_plague_flag_name_reference_report") != "zombie-plague-flag-native-name-references.json"
        or not any("17 个行名" in row for row in enemy_finding.get("observations", []))
    ):
        fail("roguelite-capabilities.json 缺少结构化僵尸分类导出及其证据限制")
    zombie_enum_mapping = zombie_variant_enum_native_registration.get("candidate_numeric_value_mapping", [])
    zombie_enum_builder_evidence = zombie_variant_enum_native_registration.get("enumerator_builder", {}).get("instruction_evidence", {})
    if (
        zombie_variant_enum_native_registration.get("schema") != 1
        or zombie_variant_enum_native_registration.get("target") != "target.json"
        or zombie_variant_enum_native_registration.get("target_sha256", "").upper() != sha.upper()
        or zombie_variant_enum_native_registration.get("enum") != "EZombieVariantType"
        or zombie_variant_enum_native_registration.get("scope", {}).get("game_process_started_or_attached") is not False
        or zombie_variant_enum_native_registration.get("scope", {}).get("executable_pdata_ranges_scanned") != 259728
        or zombie_variant_enum_native_registration.get("confidence") != "strong-static-inference"
        or [(row.get("name"), row.get("candidate_numeric_value")) for row in zombie_enum_mapping]
        != [("Slow", 0), ("Unique", 1), ("Fast", 2), ("Armored", 3), ("Plague", 4), ("EZombieVariantType_MAX", 5)]
        or zombie_variant_enum_native_registration.get("candidate_plague_ordinal") != 4
        or zombie_variant_enum_native_registration.get("enum_type_name_direct_code_reference", {}).get("site_rva") != "0xd6610f"
        or zombie_variant_enum_native_registration.get("enum_type_name_direct_code_reference", {}).get("target_rva") != "0x3739db0"
        or zombie_variant_enum_native_registration.get("initializer", {}).get("enumerator_name_table_rva") != "0x3761a40"
        or not zombie_enum_builder_evidence
        or not all(zombie_enum_builder_evidence.values())
        or roguelite_enemy_classification.get("native_enum_registration_report") != "zombie-variant-enum-native-registration.json"
        or "native enum registrar" not in roguelite_enemy_classification.get("generic_plague_variant_logic", {}).get("interpretation", "")
    ):
        fail("EZombieVariantType 原生注册映射或其血疫分类报告引用不符")
    plague_name_refs = zombie_plague_flag_native_name_references.get("executable_instruction_references", {})
    plague_contexts = zombie_plague_flag_native_name_references.get("reference_contexts", {})
    plague_xp_body_refs = zombie_plague_flag_native_name_references.get("selected_xp_function_direct_name_references", {})
    telemetry_context = next(
        (row for row in plague_contexts.get("IsPlagueZombie", []) if row.get("function_start_rva") == "0x251f510"),
        {},
    )
    corpse_state_context = next(
        (row for row in plague_contexts.get("bIsBloodPlagueZombie", []) if row.get("function_start_rva") == "0x9214c6"),
        {},
    )
    telemetry_names = {row.get("text") for row in telemetry_context.get("function_ascii_metadata_references", [])}
    corpse_state_names = {row.get("text") for row in corpse_state_context.get("function_ascii_metadata_references", [])}
    if (
        zombie_plague_flag_native_name_references.get("schema") != 1
        or zombie_plague_flag_native_name_references.get("target") != "target.json"
        or zombie_plague_flag_native_name_references.get("target_sha256", "").upper() != sha.upper()
        or zombie_plague_flag_native_name_references.get("scope", {}).get("game_process_started_or_attached") is not False
        or zombie_plague_flag_native_name_references.get("scope", {}).get("executable_pdata_ranges_scanned") != 259728
        or zombie_plague_flag_native_name_references.get("scope", {}).get("selected_xp_disassembly_function_count") != 14
        or zombie_plague_flag_native_name_references.get("scope", {}).get("selected_xp_disassembly_pdata_range_count") != 26
        or zombie_plague_flag_native_name_references.get("executable_instruction_reference_counts") != {
            "IsPlagueZombie": 5,
            "bIsBloodPlagueZombie": 3,
        }
        or {row.get("site_rva") for row in plague_name_refs.get("IsPlagueZombie", [])}
        != {"0x1cb06c", "0x2517667", "0x2517ac7", "0x2517d5c", "0x251f597"}
        or {row.get("site_rva") for row in plague_name_refs.get("bIsBloodPlagueZombie", [])}
        != {"0x9216e0", "0xd0586f", "0xd31514"}
        or "c:\\ul\\w\\r\\DaytonGame\\Source\\GameTelemetry\\Private\\EventTypes.cpp" not in telemetry_names
        or not {"IsPlagueZombie", "ZombieId", "ZombieTypeId", "Killed", "DealerId", "CauseOfDamageTypeId"}.issubset(telemetry_names)
        or not {"bIsBloodPlagueZombie", "DeadState", "ZombieMapInstanceId", "DeadBodyInventory"}.issubset(corpse_state_names)
        or any(plague_xp_body_refs.get(name) for name in ("IsPlagueZombie", "bIsBloodPlagueZombie"))
        or roguelite_enemy_classification.get("native_plague_flag_name_reference_report") != "zombie-plague-flag-native-name-references.json"
    ):
        fail("血疫标记原生名称引用报告或 XP 函数范围交叉核验不符")
    roguelite_xref_focus_ids = extraction.get("direct_call_xref_focus_ids", [])
    if len(roguelite_xref_focus_ids) != len(set(roguelite_xref_focus_ids)):
        fail("幸存者成长直接调用焦点函数 ID 重复")
    catalog_function_ids = {row.get("id") for row in functions.get("functions", [])}
    if xref_focus.get("schema") != 1 or xref_focus.get("target") != "target.json":
        fail("native-xref-focus.json 指向了错误的目标版本或 schema")
    xref_focus_ids = xref_focus.get("function_ids", [])
    xref_focus_prefixes = xref_focus.get("function_id_prefixes", [])
    if not xref_focus_ids or len(xref_focus_ids) != len(set(xref_focus_ids)):
        fail("native-xref-focus.json 函数 ID 为空或重复")
    if not xref_focus_prefixes or len(xref_focus_prefixes) != len(set(xref_focus_prefixes)):
        fail("native-xref-focus.json 函数前缀为空或重复")
    if not set(xref_focus_ids).issubset(catalog_function_ids):
        fail("直接调用交叉引用焦点函数未登记在 functions.json")
    if not set(roguelite_xref_focus_ids).issubset(set(xref_focus_ids)):
        fail("幸存者成长的交叉引用焦点未并入共享焦点清单")
    if body_analysis.get("decoder", {}).get("name") != "Capstone":
        fail("native-body-analysis.json 缺少 Capstone 解码器来源")
    if body_analysis.get("schema") != 2:
        fail("native-body-analysis.json 未包含直接调用交叉引用 schema")
    stats = body_analysis.get("statistics", {})
    if stats.get("missing_function_catalog_entries") or stats.get("missing_domain_candidates"):
        fail("静态解析结果未能解析全部研究目录候选")
    observed_status_counts = {}
    for body in body_analysis.get("functions", []):
        status = body.get("status")
        observed_status_counts[status] = observed_status_counts.get(status, 0) + 1
    if stats.get("status_counts") != dict(sorted(observed_status_counts.items())):
        fail("native-body-analysis.json 的状态汇总与函数记录不一致")
    resolved_domains = {row.get("id"): row for row in body_analysis.get("domains", [])}
    if set(resolved_domains) != domain_ids:
        fail("解码结果的研究域集合与研究目录不一致")
    for domain_id, names in domain_names.items():
        domain_row = resolved_domains[domain_id]
        if domain_row.get("status") != "candidate-only":
            fail("静态候选研究域不得被标记为已启用：" + domain_id)
        resolved_names = {row.get("native_name") for row in domain_row.get("resolved_entries", [])}
        if not names.issubset(resolved_names):
            fail("研究域候选没有完整解析到目标函数：" + domain_id)

    body_ids = set()
    for body in body_analysis.get("functions", []):
        key = (body.get("native_name"), body.get("function_rva"), body.get("registration_rva"))
        if not all(key) or key in body_ids:
            fail("native-body-analysis.json 函数记录为空或重复")
        body_ids.add(key)
        for call in body.get("direct_calls", []):
            if call.get("site_rva") and not re.fullmatch(r"0x[0-9A-Fa-f]+", call["site_rva"]):
                fail("静态调用点 RVA 无效：" + str(key))
            if call.get("target_rva") is not None and not re.fullmatch(r"0x[0-9A-Fa-f]+", call["target_rva"]):
                fail("静态调用目标 RVA 无效：" + str(key))

    xrefs = body_analysis.get("direct_call_xrefs", {})
    expected_xref_focus_count = sum(
        any(function_id.startswith(tuple(xref_focus_prefixes)) or function_id in set(xref_focus_ids)
            for function_id in body.get("function_ids", []))
        for body in body_analysis.get("functions", [])
    )
    if xrefs.get("statistics", {}).get("focus_registration_count") != expected_xref_focus_count:
        fail("直接调用交叉引用焦点数量与登记目录不一致")
    xref_targets = xrefs.get("targets", [])
    xref_target_ids = set()
    observed_edges = 0
    for target in xref_targets:
        target_rva = target.get("target_rva")
        if not target_rva or not re.fullmatch(r"0x[0-9A-Fa-f]+", target_rva) or target_rva in xref_target_ids:
            fail("直接调用交叉引用目标 RVA 无效或重复")
        xref_target_ids.add(target_rva)
        callers = target.get("verified_direct_callers", [])
        observed = target.get("verified_direct_callers_observed_count")
        if not isinstance(observed, int) or observed < len(callers):
            fail("直接调用交叉引用的观察数小于序列化调用点：" + target_rva)
        if target.get("verified_direct_callers_truncated") != (observed > len(callers)):
            fail("直接调用交叉引用的截断标记不一致：" + target_rva)
        if target.get("analysis_status") == "raw-candidate-fanout-limit" and target.get("direct_e8_search_complete"):
            fail("高扇出目标不得标记为搜索完整：" + target_rva)
        for caller in callers:
            site = caller.get("site_rva")
            call_range = caller.get("caller_unwind_range_rva", {})
            if not site or not re.fullmatch(r"0x[0-9A-Fa-f]+", site):
                fail("直接调用交叉引用的调用点 RVA 无效：" + target_rva)
            if not re.fullmatch(r"0x[0-9A-Fa-f]+", str(call_range.get("start", ""))) or not re.fullmatch(
                r"0x[0-9A-Fa-f]+", str(call_range.get("end_exclusive", ""))
            ):
                fail("直接调用交叉引用缺少调用者 unwind 边界：" + target_rva)
        observed_edges += observed
    if len(xref_targets) != xrefs.get("statistics", {}).get("target_count"):
        fail("直接调用交叉引用目标统计不一致")
    if observed_edges != xrefs.get("statistics", {}).get("verified_direct_call_edges_observed"):
        fail("直接调用交叉引用边数汇总不一致")
    followup = xrefs.get("one_hop_followup", {})
    followup_analysis = followup.get("analysis", {})
    followup_targets = followup_analysis.get("targets", [])
    followup_relation_count = sum(
        len(target.get("previously_observed_as_caller_of", [])) for target in followup_targets
    )
    if followup_relation_count != followup.get("relation_count"):
        fail("直接调用一跳跟进关系数汇总不一致")
    if len(followup_targets) != followup_analysis.get("statistics", {}).get("target_count"):
        fail("直接调用一跳跟进目标数汇总不一致")

    static_findings = roguelite.get("static_findings", {})
    if not static_findings.get("scope"):
        fail("roguelite-capabilities.json 缺少静态证据范围说明")
    for finding_id in ("kill_attribution", "experience_awards", "enemy_classification", "survivor_identity", "duplicate_reward_risk", "mission_event_lifecycle"):
        if finding_id not in static_findings or not static_findings[finding_id].get("status"):
            fail("roguelite-capabilities.json 缺少静态发现状态：" + finding_id)
    for finding_id in ("kill_attribution", "duplicate_reward_risk"):
        if static_findings[finding_id]["status"] != "unresolved-static-only":
            fail("未验证的击杀语义必须继续标为静态未解决：" + finding_id)

    for name, expected in render_exports(database).items():
        actual = read_json(ROOT / name)
        if actual != expected:
            fail("根目录导出清单与数据库不一致：" + name)
        if str(actual.get("sha256", "")).upper() != sha.upper():
            fail("导出清单 SHA256 不一致：" + name)

    if community_asset_scan.get("schema") != 1:
        fail("community-assets-static-scan.json schema 无效")
    if community_asset_scan.get("pak_count", 0) < 1 or community_asset_scan.get("selected_uasset_count", 0) < 1:
        fail("社区招募 PAK 资产扫描缺少覆盖统计")
    if community_asset_scan.get("scanned_uasset_count") != community_asset_scan.get("selected_uasset_count"):
        fail("社区招募 PAK 资产扫描并未完整覆盖选定目录")
    if community_asset_scan.get("errors"):
        fail("社区招募 PAK 资产扫描存在未解析资源")
    required_prefixes = {
        "GameSystems", "UI", "AI", "Missions", "Blueprints", "LegacyArcs",
        "RadioRoom", "Community", "MissionSettings", "AmbientMissions",
        "EnclaveArcs", "EnclaveMissions", "FactionMissions", "HeartlandMissions",
        "MissionEvents", "MissionObjectives", "PersonalArcs", "StarterScenarioArcs",
    }
    if not required_prefixes.issubset(set(community_asset_scan.get("prefixes", []))):
        fail("社区招募 PAK 扫描缺少关键资源根目录")

    if community_mission_tags.get("schema") != 1 or community_mission_tags.get("errors"):
        fail("社区任务原始属性扫描 schema 无效或存在错误")
    mission_assets = community_mission_tags.get("assets", [])
    if community_mission_tags.get("selection", {}).get("mode") != "all-campaign-and-mission-roots":
        fail("社区任务属性扫描没有覆盖完整的任务/社区资产根目录")
    if len(mission_assets) != 248:
        fail("社区任务/社区属性扫描应覆盖 248 个选定资产")
    if sum(len(row.get("community_member_conditions", [])) for row in mission_assets) != 163:
        fail("社区任务人口条件证据未覆盖预期的条件集合")
    for asset in mission_assets:
        for condition in asset.get("community_member_conditions", []):
            if "complete_nearby_tag_sequence" not in condition:
                fail("CommunityMembers 条件缺少完整性标记：" + str(asset.get("asset")))

    if community_recruitment.get("schema") != 1 or community_recruitment.get("target") != "target.json":
        fail("community-recruitment-static-findings.json schema 或目标版本无效")
    if community_recruitment.get("target_sha256", "").upper() != sha.upper():
        fail("社区招募静态结论与目标 EXE SHA256 不一致")
    scope = community_recruitment.get("scope", {})
    global_asset_scan_valid = (
        community_global_asset_scan.get("schema") == 1
        and community_global_asset_scan.get("pak_count") == 35
        and community_global_asset_scan.get("selected_uasset_count") == 105357
        and community_global_asset_scan.get("scanned_uasset_count") == 105357
        and community_global_asset_scan.get("scanned_uncompressed_bytes") == 8169066939
        and community_global_asset_scan.get("matched_asset_count") == 3798
        and not community_global_asset_scan.get("errors")
    )
    if not global_asset_scan_valid:
        fail("完整 .uasset 字符串扫描没有覆盖固定索引、存在错误或摘要数据漂移")
    if scope.get("full_asset_string_scan_report") != "community-all-assets-global-scan.json":
        fail("社区招募结论没有引用全量 .uasset 字符串扫描报告")
    for summary_key, scan_key in (
        ("full_asset_string_scan_selected", "selected_uasset_count"),
        ("full_asset_string_scan_scanned", "scanned_uasset_count"),
        ("full_asset_string_scan_uncompressed_bytes", "scanned_uncompressed_bytes"),
        ("full_asset_string_scan_matched_assets", "matched_asset_count"),
        ("full_asset_string_scan_errors", "errors"),
    ):
        expected_value = len(community_global_asset_scan[scan_key]) if scan_key == "errors" else community_global_asset_scan[scan_key]
        if scope.get(summary_key) != expected_value:
            fail("社区招募结论中的全量资产扫描统计与原始报告不一致：" + summary_key)
    def normalize_asset_path(value):
        path = str(value).replace("\\", "/").casefold()
        prefix = "stateofdecay2/content/"
        return path[len(prefix):] if path.startswith(prefix) else path

    def report_asset_paths(report, key="findings"):
        return {
            normalize_asset_path(row["asset"])
            for row in report.get(key, [])
            if row.get("asset")
        }

    index_path = (DATABASE / scope.get("full_pak_index_source", "")).resolve()
    if not index_path.is_file():
        fail("完整 PAK 索引缺失，无法复核结构化资源路径覆盖率：" + str(index_path))
    try:
        asset_index = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        fail("完整 PAK 索引无法解码：" + str(error))
    indexed_uassets = [
        row for row in asset_index
        if str(row.get("path", "")).lower().endswith(".uasset")
    ]
    indexed_uasset_paths = {
        normalize_asset_path(row["path"])
        for row in indexed_uassets
    }
    global_hit_paths = report_asset_paths(community_global_asset_scan)
    path_candidate_paths = report_asset_paths(community_named_asset_scan)
    symbol_candidate_paths = report_asset_paths(community_specific_symbol_scan)
    mission_paths = report_asset_paths(community_mission_tags, "assets")
    structured_export_paths = global_hit_paths | path_candidate_paths | symbol_candidate_paths | mission_paths
    path_coverage = scope.get("structured_asset_path_coverage", {})
    if (
        len(indexed_uassets) != 105357
        or len(indexed_uasset_paths) != 105304
        or len(global_hit_paths) != 3798
        or len(path_candidate_paths) != 1013
        or len(symbol_candidate_paths) != 487
        or len(mission_paths) != 248
        or not path_candidate_paths.issubset(global_hit_paths)
        or not symbol_candidate_paths.issubset(global_hit_paths)
        or len(mission_paths & global_hit_paths) != 153
        or len(mission_paths - global_hit_paths) != 95
        or not structured_export_paths.issubset(indexed_uasset_paths)
        or len(structured_export_paths) != 3893
        or len(indexed_uasset_paths - structured_export_paths) != 101411
        or path_coverage.get("full_index_uasset_entry_count") != 105357
        or path_coverage.get("full_index_unique_uasset_path_count") != 105304
        or path_coverage.get("duplicate_uasset_path_entries_across_paks") != 53
        or path_coverage.get("targeted_export_sets_unique_paths_before_full_export") != 3893
        or path_coverage.get("targeted_export_sets_paths_outside_those_exports") != 101411
        or path_coverage.get("targeted_export_sets_unique_path_coverage_percent") != 3.6969
    ):
        fail("结构化导出路径并集、PAK 重复项或全量覆盖率与索引不符")
    static_audit = community_recruitment.get("static_phase_audit", {})
    if static_audit.get("complete") is not False or not static_audit.get("unresolved_static") or not static_audit.get("requires_runtime"):
        fail("静态阶段审计不得把未完成的语义分析或实机验收标为完成")
    if scope.get("game_process_started_or_attached") is not False:
        fail("社区招募静态结论必须明确记录未启动/附加游戏进程")
    for summary_key, scan_key in (
        ("pak_files_indexed", "pak_count"),
        ("gameplay_assets_selected", "selected_uasset_count"),
        ("gameplay_assets_scanned", "scanned_uasset_count"),
        ("uncompressed_asset_bytes_scanned", "scanned_uncompressed_bytes"),
        ("assets_with_matching_name_like_strings", "matched_asset_count"),
    ):
        if scope.get(summary_key) != community_asset_scan.get(scan_key):
            fail("社区招募静态结论资产扫描统计与原始报告不一致：" + summary_key)
    if community_recruitment.get("native_analysis", {}).get("ue_native_pairs_scanned") != body_analysis.get("statistics", {}).get("native_pairs_scanned"):
        fail("社区招募静态结论中的原生登记表扫描数与主体分析不一致")
    if scope.get("asset_prefixes") != community_asset_scan.get("prefixes"):
        fail("社区招募结论中的资产根目录与 PAK 扫描报告不一致")
    if (
        community_named_asset_scan.get("schema") != 1
        or community_named_asset_scan.get("pak_count") != 35
        or community_named_asset_scan.get("path_regex") != scope.get("named_asset_candidates_path_regex")
        or community_named_asset_scan.get("selected_uasset_count") != scope.get("named_asset_candidates_selected")
        or community_named_asset_scan.get("scanned_uasset_count") != scope.get("named_asset_candidates_scanned")
        or community_named_asset_scan.get("scanned_uncompressed_bytes") != scope.get("named_asset_candidates_uncompressed_bytes")
        or community_named_asset_scan.get("matched_asset_count") != scope.get("named_asset_candidates_selected")
        or community_named_asset_scan.get("errors")
    ):
        fail("跨目录招募/人口/社区界面候选资产扫描与结论摘要不一致")
    if (
        community_specific_symbol_scan.get("schema") != 1
        or community_specific_symbol_scan.get("source_report") != "community-all-assets-global-scan.json"
        or community_specific_symbol_scan.get("pak_count") != 35
        or community_specific_symbol_scan.get("selected_uasset_count") != 487
        or community_specific_symbol_scan.get("selected_uncompressed_bytes") != 70601270
        or len(community_specific_symbol_scan.get("findings", [])) != 487
        or community_specific_symbol_scan.get("errors")
    ):
        fail("精确招募/社区符号候选筛选报告与预期固定构建不一致")
    if {row.get("asset", "").lower() for row in community_named_asset_scan.get("findings", [])} & {
        row.get("asset", "").lower() for row in community_specific_symbol_scan.get("findings", [])
    }:
        fail("按路径和按精确符号选出的候选资产存在未去重的路径交集")
    if community_recruitment.get("scope", {}).get("cooked_blueprint_report") != "community-cooked-blueprint-analysis.json":
        fail("社区招募结论未引用 cooked Blueprint 解析报告")
    all_hit_report = community_all_string_hit_cooked
    all_hit_scope = all_hit_report.get("scope", {})
    all_hit_provenance = all_hit_report.get("parser_provenance", {})
    all_hit_calls = all_hit_report.get("candidate_blueprint_call_references", {})
    known_enum_warning = (
        "StateOfDecay2/Content/GameSystems/Enclave/CommunityScreenLayoutMode.uasset: "
        "System.NullReferenceException; a JSON file was emitted and is syntactically valid, "
        "but Ue4Export reported the package export as failed."
    )
    if all_hit_report.get("schema") != 1 or all_hit_report.get("target") != "target.json":
        fail("全量关键词命中 cooked 解析报告 schema 或目标版本无效")
    if (
        all_hit_scope.get("candidate_asset_count") != 3798
        or all_hit_scope.get("candidate_exports_matched") != 3798
        or all_hit_scope.get("candidate_exports_missing")
        or all_hit_scope.get("candidate_json_decode_errors")
        or all_hit_scope.get("exporter_warnings") != []
        or all_hit_scope.get("initial_selected_export_warnings") != [known_enum_warning]
        or all_hit_scope.get("candidate_decoded_object_count") != 67209
        or all_hit_scope.get("candidate_function_count") != 5170
        or all_hit_scope.get("candidate_function_bytecode_count") != 5170
        or all_hit_scope.get("candidate_top_level_bytecode_expression_count") != 59087
    ):
        fail("全量关键词命中 cooked 解析覆盖率或统计与固定导出不符")
    if (
        all_hit_provenance.get("exporter_revision") != "cf112ad366842f09f43e269914dab5f4d2ee3fcc"
        or all_hit_provenance.get("parser_revision") != "cb6fba1bed6d2feaba7e1972b6b5fade9d49fb7b"
        or "ReadScriptData=true" not in all_hit_provenance.get("configuration", "")
        or all_hit_provenance.get("input_json_directories_are_external_temporary_data") is not True
    ):
        fail("全量关键词命中 cooked 解析器来源或临时输入来源未正确记录")
    full_audit_scope = community_full_uasset_audit.get("scope", {})
    full_warning_assets = full_audit_scope.get("warning_assets", [])
    if (
        community_full_uasset_audit.get("schema") != 1
        or community_full_uasset_audit.get("target") != "target.json"
        or community_full_uasset_audit.get("target_sha256", "").upper() != sha.upper()
        or full_audit_scope.get("game_process_started_or_attached") is not False
        or full_audit_scope.get("pak_index_uasset_entries") != 105357
        or full_audit_scope.get("provider_asset_matches") != 105357
        or full_audit_scope.get("json_output_files") != 105357
        or full_audit_scope.get("json_decode_errors") != 0
        or full_audit_scope.get("exporter_exit_code") != 0
        or full_audit_scope.get("exporter_warning_asset_count") != 0
        or full_audit_scope.get("exporter_warning_unique_asset_path_count") != 0
        or full_audit_scope.get("exporter_warning_exception_type_counts") != {}
        or full_warning_assets
        or full_audit_scope.get("decoded_object_count") != 494268
        or full_audit_scope.get("function_count") != 16579
        or full_audit_scope.get("function_bytecode_count") != 16579
        or full_audit_scope.get("top_level_bytecode_expression_count") != 209339
        or full_audit_scope.get("filtered_community_call_reference_count") != 654
        or full_audit_scope.get("filtered_community_call_target_count") != 167
    ):
        fail("全量 cooked 导出审计的覆盖率、字节码统计或解析器警告统计不符")
    condition_census_scope = community_full_mission_condition_census.get("scope", {})
    condition_census_summary = community_full_mission_condition_census.get("summary", {})
    condition_census = condition_census_summary.get("comparison_by_stat", [])
    missing_condition_rows = community_full_mission_condition_census.get("missing_comparison_objects", [])
    condition_definition_search = community_full_mission_condition_census.get("static_definition_search", {})
    if (
        community_full_mission_condition_census.get("schema") != 1
        or community_full_mission_condition_census.get("target") != "target.json"
        or community_full_mission_condition_census.get("target_sha256", "").upper() != sha.upper()
        or condition_census_scope.get("json_files_seen") != 105357
        or condition_census_scope.get("provider_asset_roots") != ["Engine", "StateOfDecay2"]
        or condition_census_scope.get("candidate_files") != 19
        or condition_census_scope.get("json_decode_errors") != 0
        or condition_census_scope.get("game_process_started_or_attached") is not False
        or condition_census_scope.get("class_default_inferred") is not False
        or condition_definition_search.get("searched_same_full_json_tree") is not True
        or condition_definition_search.get("default_object_name_hit_count") != 0
        or condition_definition_search.get("comparison_enum_definition_count") != 0
        or condition_definition_search.get("condition_struct_definition_count") != 0
        or condition_census_summary.get("condition_object_count") != 315
        or condition_census_summary.get("comparison_field_present_count") != 269
        or condition_census_summary.get("comparison_field_missing_count") != 46
        or condition_census_summary.get("comparison_stat_counts", {}).get("ECommunityConditionStat::CommunityMembers") != 211
        or condition_census_summary.get("missing_by_stat") != {
            "<missing>": 2,
            "ECommunityConditionStat::CommunityMembers": 43,
            "ECommunityConditionStat::CommunityOutposts": 1,
        }
        or len(missing_condition_rows) != 46
        or sum(row.get("count", 0) for row in condition_census) != 315
        or community_full_mission_condition_census.get("errors")
    ):
        fail("全包 CommunityMissionCondition 清点覆盖率或字段缺失统计不符")
    enum_pointer_group = mission_condition_enum_pointer_evidence.get("ordered_enum_name_pointer_group_candidate", {})
    enum_pointer_entries = enum_pointer_group.get("entries", [])
    if (
        mission_condition_enum_pointer_evidence.get("schema") != 1
        or mission_condition_enum_pointer_evidence.get("target_sha256", "").upper() != sha.upper()
        or mission_condition_enum_pointer_evidence.get("scope", {}).get("game_process_started_or_attached") is not False
        or enum_pointer_group.get("complete") is not True
        or [row.get("name") for row in enum_pointer_entries] != [
            "EMissionConditionComparison::Equal",
            "EMissionConditionComparison::Greater",
            "EMissionConditionComparison::GreaterOrEqual",
            "EMissionConditionComparison::Less",
            "EMissionConditionComparison::LessOrEqual",
            "EMissionConditionComparison::NotEqual",
        ]
        or [row.get("slot_rva") for row in enum_pointer_entries]
        != ["0x37d8500", "0x37d8508", "0x37d8510", "0x37d8518", "0x37d8520", "0x37d8528"]
        or len(mission_condition_enum_pointer_evidence.get("maximum_sentinel_pointer_slots", [])) != 1
        or mission_condition_enum_pointer_evidence.get("ordinal_mapping_candidates", [])[0].get("candidate_name") != "Equal"
    ):
        fail("CommunityMissionCondition 比较枚举原生字符串/指针序列候选不符")
    native_enum_mapping = mission_condition_enum_native_registration.get("candidate_numeric_value_mapping", [])
    native_enum_evidence = mission_condition_enum_native_registration.get("enumerator_builder", {}).get("instruction_evidence", {})
    if (
        mission_condition_enum_native_registration.get("schema") != 1
        or mission_condition_enum_native_registration.get("target_sha256", "").upper() != sha.upper()
        or mission_condition_enum_native_registration.get("scope", {}).get("game_process_started_or_attached") is not False
        or mission_condition_enum_native_registration.get("confidence") != "strong-static-inference"
        or [(row.get("name"), row.get("candidate_numeric_value")) for row in native_enum_mapping]
        != [("Equal", 0), ("Greater", 1), ("GreaterOrEqual", 2), ("Less", 3), ("LessOrEqual", 4), ("NotEqual", 5), ("EMissionConditionComparison_MAX", 6)]
        or not native_enum_evidence
        or not all(native_enum_evidence.values())
        or len(mission_condition_enum_native_registration.get("initializer", {}).get("enum_name_reference_instructions", [])) != 1
        or len(mission_condition_enum_native_registration.get("enumerator_builder", {}).get("chain_ranges", [])) != 5
    ):
        fail("CommunityMissionCondition 比较枚举原生注册和顺序值候选不符")
    condition_native_name_refs = community_mission_condition_native_name_xrefs.get("executable_instruction_references", {})
    class_name_refs = condition_native_name_refs.get("utf16le:CommunityMissionCondition#1", [])
    if (
        community_mission_condition_native_name_xrefs.get("schema") != 1
        or community_mission_condition_native_name_xrefs.get("target_sha256", "").upper() != sha.upper()
        or community_mission_condition_native_name_xrefs.get("scope", {}).get("game_process_started_or_attached") is not False
        or community_mission_condition_native_name_xrefs.get("scope", {}).get("executable_pdata_ranges_scanned") != 259728
        or community_mission_condition_native_name_xrefs.get("string_occurrences_utf16le", {}).get("UCommunityMissionCondition")
        != ["0x35c0398", "0x35c18b8", "0x37dbf70"]
        or not any(row.get("site_rva") == "0xa2f92b" and row.get("function_start_rva") == "0xa2f8f0" for row in class_name_refs)
    ):
        fail("CommunityMissionCondition 原生 UTF-16 名称引用审计不符")
    native_layout = community_mission_condition_native_layout
    layout_fields = native_layout.get("field_layout_candidates", [])
    layout_field_offsets = {row.get("name"): row.get("offset_candidate") for row in layout_fields}
    class_registrations = native_layout.get("class_registrations", {})
    if (
        native_layout.get("schema") != 1
        or native_layout.get("target_sha256", "").upper() != sha.upper()
        or native_layout.get("scope", {}).get("game_process_started_or_attached") is not False
        or native_layout.get("community_initializer", {}).get("root_rva") != "0xfc7c40"
        or [(row.get("site_rva"), row.get("target_rva"))
            for row in native_layout.get("community_initializer", {}).get("direct_dependency_calls", [])]
        != [("0xfc7c71", "0xf32160"), ("0xfc7c82", "0xa2f8f0")]
        or layout_field_offsets != {"Value": 0x2C, "Comparison": 0x28, "ComparisonStat": 0x30}
        or class_registrations.get("UMissionCondition", {}).get("registered_size_argument_candidate") != 0x28
        or class_registrations.get("UCommunityMissionCondition", {}).get("registered_size_argument_candidate") != 0x38
        or native_layout.get("default_value_status", {}).get("Comparison") != "unresolved"
        or native_layout.get("layout_inference", {}).get("confidence") != "strong-static-initializer-chain-inference"
    ):
        fail("CommunityMissionCondition 原生类注册/属性偏移静态证据不符")
    condition_scope = community_recruitment.get("scope", {})
    if (
        condition_scope.get("full_asset_community_mission_condition_census_report") != "community-full-uasset-mission-condition-census.json"
        or condition_scope.get("mission_condition_enum_native_pointer_evidence_report") != "mission-condition-enum-native-pointer-evidence.json"
        or condition_scope.get("mission_condition_enum_native_registration_report") != "mission-condition-enum-native-registration.json"
        or condition_scope.get("community_mission_condition_native_name_xrefs_report") != "community-mission-condition-native-name-xrefs.json"
        or condition_scope.get("community_mission_condition_native_layout_report") != "community-mission-condition-native-layout.json"
        or condition_scope.get("full_asset_community_mission_condition_objects") != 315
        or condition_scope.get("full_asset_community_mission_condition_missing_comparison") != 46
        or condition_scope.get("full_asset_community_members_missing_comparison") != 43
        or community_recruitment.get("static_phase_audit", {}).get("complete") is not False
    ):
        fail("社区招募静态结论未正确引用全包 Comparison 清点或仍误报静态语义已完成")
    full_call_scope = community_full_uasset_calls.get("scope", {})
    full_call_refs = community_full_uasset_calls.get("call_references", [])
    full_try_add = [row for row in full_call_refs if row.get("target") == "Function'Enclave:TryAddCharacterRecord'"]
    full_try_add_callers = {
        (row.get("asset_path"), row.get("blueprint_function")) for row in full_try_add
    }
    expected_full_try_add_callers = {
        ("StateOfDecay2/Content/Cinematics/Blueprints/CinematicFunctionLibrary.uasset", "AddNPCToCommunity"),
        ("StateOfDecay2/Content/UICheat/CheatMenu.uasset", "AddNpcToPlayerCommunity"),
        ("StateOfDecay2/Content/UICheat/CheatMenu.uasset", "ExecuteUbergraph_CheatMenu"),
    }
    if (
        community_full_uasset_calls.get("schema") != 1
        or community_full_uasset_audit.get("scope", {}).get("full_blueprint_call_report") != "community-full-uasset-blueprint-call-analysis.json"
        or full_call_scope.get("json_files_seen") != 105357
        or full_call_scope.get("json_decode_error_count") != 0
        or full_call_scope.get("filtered_call_reference_count") != 654
        or full_call_scope.get("filtered_call_target_count") != 167
        or len(full_try_add) != 3
        or full_try_add_callers != expected_full_try_add_callers
        or community_full_uasset_calls.get("capacity_native_wrapper_reference_counts") != {
            "CanAddCharacter": 0,
            "CanAddCharacters": 0,
            "TryAddCharacter": 0,
            "TryAddCharacterRecord": 3,
        }
        or any("CanAddCharacter" in str(row.get("target", "")) for row in full_call_refs)
        or any("CanAddCharacters" in str(row.get("target", "")) for row in full_call_refs)
    ):
        fail("全包 Blueprint 招募调用引用清单与全量导出审计不一致")
    roguelite_call_scope = community_full_uasset_roguelite_calls.get("scope", {})
    roguelite_targets = community_full_uasset_roguelite_calls.get("target_reference_counts", {})
    if (
        community_full_uasset_roguelite_calls.get("schema") != 1
        or community_full_uasset_roguelite_calls.get("target_filter") != r"(?i)(AwardExperience|AuthAwardExperience|CanGainExperience|NextLevel|OnZombieKilled|AuthOnZombieKilled|KilledZombie|AddZombieKilled|DeathOver|GetCharacterWhoHitMost|GetCurrentAttackers|GetValidCharactersAfterDeath|FinishConditionCheck|InitializeEvent|Create[A-Za-z0-9_]*MissionEvent|GetSurvivorByID|GetIncomingCharacterRecordFromId|GetLegacyCharacterRecordFromId|GenerateCharacterRecordFromSchema|ClientSetCurrentSurvivorID|ClientClearCurrentSurvivorID|GetHealth(Max|Current)?|GetStamina(Max|Current)?|ApplyStaminaLoss|GetHasBloodPlague|GetHasPlague|ContainsBloodPlagueNode)"
        or roguelite_call_scope.get("json_files_seen") != 105357
        or roguelite_call_scope.get("json_decode_error_count") != 0
        or roguelite_call_scope.get("filtered_call_reference_count") != 148
        or roguelite_call_scope.get("filtered_call_target_count") != 23
        or roguelite_targets.get("Function'CharacterBlueprintHelpers:AuthAwardExperience'") != 34
        or roguelite_targets.get("Function'MissionEventInstance:InitializeEvent'") != 7
        or any(name in roguelite_targets for name in ("Function'Enclave:OnZombieKilled'", "Function'Enclave:AuthOnZombieKilled'"))
    ):
        fail("全包击杀/经验/事件/身份 Blueprint 调用清单与固定字节码导出不一致")
    enemy_scope = roguelite_enemy_classification.get("scope", {})
    enum_usage = roguelite_enemy_classification.get("enum_usage", {})
    zombie_table = roguelite_enemy_classification.get("zombie_type_data_table", {})
    enum_mapping = roguelite_enemy_classification.get("all_zombie_types_enum", {})
    enum_pairs = enum_mapping.get("enumerator_ordinal_mapping_candidates", [])
    density_categories = roguelite_enemy_classification.get("boons_banes_density_categories", {})
    plague_flag_evidence = roguelite_enemy_classification.get("explicit_plague_flag_evidence", {})
    special_flag_rows = plague_flag_evidence.get("blood_plague_special_presets", [])
    variant_table = roguelite_enemy_classification.get("zombie_variants_data_table", {})
    generic_plague_logic = roguelite_enemy_classification.get("generic_plague_variant_logic", {})
    flag_inventory = roguelite_enemy_classification.get("serialized_plague_flag_inventory", {})
    expected_enum_labels = ["Generic", "Screamer", "Bloater", "Juggernaut", "Feral", "All"]
    expected_rows = {"Plague", "BpJuggernaut", "BpBloater", "BpScreamer", "BpFeral"}
    actual_rows = {row.get("row_name") for row in zombie_table.get("rows", [])}
    if (
        roguelite_enemy_classification.get("schema") != 1
        or roguelite_enemy_classification.get("target") != "target.json"
        or roguelite_enemy_classification.get("target_sha256", "").upper() != sha.upper()
        or enemy_scope.get("game_process_started_or_attached") is not False
        or enemy_scope.get("enum_usage_json_files") != 105357
        or enemy_scope.get("enum_usage_json_bytes_scanned") != 2332782471
        or enemy_scope.get("enum_usage_decode_errors") != 0
        or enemy_scope.get("provider_asset_roots") != ["Engine", "StateOfDecay2"]
        or enum_usage.get("serialized_reference_count") != 6
        or enum_usage.get("enumerator_reference_counts") != {
            "AllZombieTypes::NewEnumerator3": 2,
            "AllZombieTypes::NewEnumerator5": 4,
        }
        or enum_mapping.get("display_names_in_serialized_order") != expected_enum_labels
        or [row.get("ordinal") for row in enum_pairs] != list(range(6))
        or [row.get("display_name_candidate") for row in enum_pairs] != expected_enum_labels
        or enum_mapping.get("exported_names_map_values") != [0, 0, 0, 0, 0]
        or zombie_table.get("row_count") != 17
        or not expected_rows.issubset(actual_rows)
        or zombie_table.get("row_struct") != "UserDefinedStruct'ZombieTypeStruct'"
        or variant_table.get("row_count") != 28
        or variant_table.get("plague_variant_row_count") != 3
        or {row.get("row_name") for row in variant_table.get("plague_variant_rows", [])}
        != {"MalePlague01", "FemalePlague01", "MaleFatPlague01"}
        or generic_plague_logic.get("function") != "SetSpecificCharacterAppearance"
        or generic_plague_logic.get("table_lookup", {}).get("table") != "DataTable'ZombieVariants'"
        or generic_plague_logic.get("table_lookup", {}).get("row_name_source") != "ZombieVariant"
        or generic_plague_logic.get("comparison", {}).get("byte_value") != 4
        or generic_plague_logic.get("conditional_branch", {}).get("code_offset") != 1282
        or {
            (row.get("variable"), row.get("serialized_value_token"))
            for row in generic_plague_logic.get("equal_value_branch_flag_writes", [])
        } != {
            ("BoolProperty'ZombieCharacter_C:IsPlagueZombie'", "EX_True"),
            ("BoolProperty'DaytonZombieCharacter:bIsBloodPlagueZombie'", "EX_True"),
        }
        or flag_inventory.get("candidate_asset_count") != 47
        or len(flag_inventory.get("bytecode_flag_assignments", [])) != 11
        or {
            (row.get("object"), row.get("serialized_value"))
            for row in flag_inventory.get("default_object_flag_values", [])
        } != {
            ("Default__Zombie_Plague_C", True),
            ("Default__Zombie_PlagueAmbush_C", True),
        }
        or density_categories.get("base_density_reduction_category_count") != 9
        or density_categories.get("base_density_reduction_categories", []) != [
            "EBoonsBanesZombieType::SlowZombie",
            "EBoonsBanesZombieType::FastZombie",
            "EBoonsBanesZombieType::HumanTurnedZombie",
            "EBoonsBanesZombieType::Crawler",
            "EBoonsBanesZombieType::ArmoredZombie",
            "EBoonsBanesZombieType::Bloater",
            "EBoonsBanesZombieType::Screamer",
            "EBoonsBanesZombieType::Feral",
            "EBoonsBanesZombieType::Juggernaut",
        ]
        or plague_flag_evidence.get("normal_plague_preset", {}).get("default_object") != "Default__Zombie_Plague_C"
        or plague_flag_evidence.get("normal_plague_preset", {}).get("field") != "IsPlagueZombie"
        or plague_flag_evidence.get("normal_plague_preset", {}).get("serialized_value") is not True
        or len(special_flag_rows) != 4
        or {row.get("data_table_row") for row in special_flag_rows}
        != {"BpBloater", "BpFeral", "BpScreamer", "BpJuggernaut"}
        or any(
            row.get("construction_function") != "UserConstructionScript"
            or len(row.get("explicit_assignments", [])) != 1
            or row["explicit_assignments"][0].get("variable")
            != "BoolProperty'DaytonZombieCharacter:bIsBloodPlagueZombie'"
            or row["explicit_assignments"][0].get("serialized_value_token") != "EX_True"
            or row["explicit_assignments"][0].get("value_is_true") is not True
            for row in special_flag_rows
        )
    ):
        fail("全包僵尸枚举、遭遇类表或 Boons/Banes 分类静态报告与导出不符")
    mission_event_scope = community_full_mission_event_calls.get("scope", {})
    mission_event_targets = community_full_mission_event_calls.get("target_reference_counts", {})
    expected_mission_event_filter = r"(?i)(InitializeEvent|FinishConditionCheck|SendMissionToState|UpdateMissionState|CheckMissionPhase|Create[A-Za-z0-9_]*MissionEvent|TrySpawnMissionAsync|TrySpawnMission\\b|MissionComplete\\b|MissionCancelled\\b|CompleteMissionObjective|CompleteMission\\b|CancelMission\\b|FailMission\\b|SetMissionMode\\b|MulticastFireEvent\\b|ULPopupLegacyMissionFireEvent\\b|OnAsyncMissionCreationComplete|GetMissionInstance|GetMissionStateComponent|GetActiveMissions)"
    mission_event_refs = community_full_mission_event_calls.get("call_references", [])
    if (
        community_full_mission_event_calls.get("schema") != 1
        or community_full_mission_event_calls.get("target") != "target.json"
        or community_full_mission_event_calls.get("target_sha256", "").upper() != sha.upper()
        or community_full_mission_event_calls.get("target_filter") != expected_mission_event_filter
        or mission_event_scope.get("json_files_seen") != 105357
        or mission_event_scope.get("json_decode_error_count") != 0
        or mission_event_scope.get("filtered_call_reference_count") != 18
        or mission_event_scope.get("filtered_call_target_count") != 7
        or len(mission_event_refs) != 18
        or mission_event_targets.get("Function'MissionEventInstance:InitializeEvent'") != 7
        or mission_event_targets.get("Function'MissionFunctionLibrary:GetMissionInstance'") != 4
        or any(
            token in str(target)
            for target in mission_event_targets
            for token in ("FinishConditionCheck", "SendMissionToState", "MissionComplete", "MissionCancelled", "TrySpawnMission", "TrySpawnMissionAsync")
        )
    ):
        fail("全包任务事件生命周期 Blueprint 调用清点的覆盖率或观察值不符")
    mission_findings = roguelite.get("static_findings", {}).get("mission_event_lifecycle", {})
    if (
        mission_findings.get("status") != "partial-static-evidence"
        or mission_findings.get("blueprint_call_report") != "community-full-uasset-mission-event-lifecycle-call-analysis.json"
        or mission_findings.get("native_direct_call_report") != "native-full-pdata-direct-xrefs.json"
        or len(mission_findings.get("native_functions", [])) != 20
        or len(extraction.get("mission_event_direct_call_xref_focus_ids", [])) != 20
        or not any("no serialized blueprint call token" in row.casefold() for row in mission_findings.get("observations", []))
    ):
        fail("幸存者成长资料缺少任务事件生命周期的候选入口、静态证据或限制")
    call_rows = all_hit_calls.get("references", [])
    try_add_rows = [row for row in call_rows if row.get("target") == "Function'Enclave:TryAddCharacterRecord'"]
    try_add_callers = {
        (row.get("asset_package"), row.get("blueprint_function"))
        for row in try_add_rows
    }
    expected_try_add_callers = {
        ("StateOfDecay2/Content/Cinematics/Blueprints/CinematicFunctionLibrary", "AddNPCToCommunity"),
        ("StateOfDecay2/Content/UICheat/CheatMenu", "AddNpcToPlayerCommunity"),
        ("StateOfDecay2/Content/UICheat/CheatMenu", "ExecuteUbergraph_CheatMenu"),
    }
    if (
        all_hit_calls.get("matched_reference_count") != 497
        or all_hit_calls.get("unique_target_count") != 125
        or len(try_add_rows) != 3
        or try_add_callers != expected_try_add_callers
        or any("CanAddCharacter" in str(row.get("target", "")) for row in call_rows)
        or any("CanAddCharacters" in str(row.get("target", "")) for row in call_rows)
    ):
        fail("全量关键词命中 Blueprint 调用筛选观察与固定导出不符")
    all_hit_findings = community_recruitment.get("blueprint_analysis", {}).get("global_keyword_hit_structured_coverage", {})
    for key, expected in (
        ("selected_assets", 3798),
        ("exported_assets", 3798),
        ("missing_assets", 0),
        ("json_decode_errors", 0),
        ("exporter_warnings", 0),
        ("decoded_objects", 67209),
        ("functions", 5170),
        ("functions_with_bytecode", 5170),
        ("top_level_bytecode_expressions", 59087),
        ("filtered_blueprint_call_references", 497),
        ("filtered_blueprint_call_targets", 125),
    ):
        if all_hit_findings.get(key) != expected:
            fail("社区招募结论中的全量关键词命中解析摘要不符：" + key)
    cooked_scope = community_cooked_blueprint.get("scope", {})
    cooked_missions = community_cooked_blueprint.get("mission_summary", {})
    if community_cooked_blueprint.get("schema") != 1 or community_cooked_blueprint.get("target") != "target.json":
        fail("cooked Blueprint 分析报告 schema 或目标版本无效")
    if cooked_scope.get("candidate_asset_count") != 1500 or cooked_scope.get("candidate_exports_matched") != 1500:
        fail("cooked Blueprint 候选导出覆盖率不完整")
    if cooked_scope.get("candidate_exports_missing") or cooked_scope.get("candidate_json_decode_errors"):
        fail("cooked Blueprint 候选导出存在缺失或 JSON 解码错误")
    if cooked_scope.get("mission_selection_asset_count") != 248 or cooked_scope.get("mission_exports_with_missionasset") != 131:
        fail("cooked Blueprint 任务/社区资产选择范围与导出统计不符")
    if cooked_scope.get("mission_json_decode_errors") or cooked_scope.get("mission_export_ambiguous_matches"):
        fail("任务/社区 cooked JSON 解析存在错误或歧义")
    if cooked_scope.get("candidate_source_report_count") != 2 or cooked_scope.get("candidate_export_file_count") != 1502:
        fail("cooked Blueprint 路径/符号候选导出数量不符")
    if (
        cooked_scope.get("candidate_function_count") != 305
        or cooked_scope.get("candidate_function_bytecode_count") != 305
        or cooked_scope.get("candidate_top_level_bytecode_expression_count") != 4802
        or cooked_scope.get("candidate_filtered_blueprint_call_reference_count") != 213
        or cooked_scope.get("candidate_filtered_blueprint_call_target_count") != 76
    ):
        fail("候选 Blueprint 字节码及相关调用引用统计不符")
    if (
        cooked_scope.get("mission_export_function_count") != 419
        or cooked_scope.get("mission_export_function_bytecode_count") != 419
        or cooked_scope.get("mission_export_top_level_bytecode_expression_count") != 7394
    ):
        fail("任务/社区 Blueprint 字节码解析统计不符")
    recruitment_scope = community_recruitment.get("scope", {})
    for summary_key, expected in (
        ("structured_candidate_assets_selected", 1500),
        ("structured_candidate_assets_exported", 1500),
        ("structured_candidate_json_decode_errors", 0),
        ("mission_selection_assets", 248),
        ("missionasset_packages_parsed", 131),
        ("mission_records_parsed", 2323),
        ("mission_bytecode_functions_parsed", 419),
        ("mission_bytecode_top_level_expressions_parsed", 7394),
    ):
        if recruitment_scope.get(summary_key) != expected:
            fail("社区招募结论中的 cooked Blueprint 摘要不符：" + summary_key)
    if recruitment_scope.get("reachable_community_member_condition_event_occurrences") != 6:
        fail("社区招募结论中的可达人数条件事件数不符")
    if cooked_scope.get("exporter_warnings") != [] or cooked_scope.get("initial_selected_export_warnings") != [known_enum_warning] or recruitment_scope.get("structured_candidate_exporter_warnings") != 0:
        fail("cooked Blueprint 的历史警告或全量复核状态与审计报告不符")
    if recruitment_scope.get("candidate_blueprint_call_references") != 213 or recruitment_scope.get("candidate_blueprint_call_targets") != 76:
        fail("社区招募结论中的候选 Blueprint 调用引用数不符")
    parser_provenance = community_cooked_blueprint.get("parser_provenance", {})
    if (
        parser_provenance.get("exporter_revision") != "cf112ad366842f09f43e269914dab5f4d2ee3fcc"
        or parser_provenance.get("parser_revision") != "cb6fba1bed6d2feaba7e1972b6b5fade9d49fb7b"
        or "ReadScriptData=true" not in parser_provenance.get("configuration", "")
    ):
        fail("cooked Blueprint 解析器来源或脚本字节码配置未记录")
    for key, expected in (
        ("mission_record_count", 2323),
        ("mission_records_adding_characters_to_player_enclave", 97),
        ("mission_records_flagged_ignores_population_cap", 7),
        ("community_member_condition_records", 163),
        ("mission_records_with_reachable_recruit_event", 34),
        ("reachable_recruit_event_occurrences", 48),
        ("mission_records_with_reachable_community_member_condition", 5),
        ("reachable_community_member_condition_event_occurrences", 6),
    ):
        if cooked_missions.get(key) != expected:
            fail("cooked Blueprint 任务/社区语义统计不符：" + key)
    event_name_inventory = cooked_missions.get("event_name_inventory", {})
    for key, expected in (
        ("named_event_record_count", 2954),
        ("package_unique_name_count_sum", 1155),
        ("packages_with_repeated_names", 64),
        ("same_type_duplicate_group_count_per_package_sum", 433),
        ("cross_type_reuse_group_count_per_package_sum", 43),
    ):
        if event_name_inventory.get(key) != expected:
            fail("EventName 静态清点统计与固定导出不符：" + key)
    if "are not assumed to imply" not in " ".join(event_name_inventory.get("limits", [])):
        fail("EventName 清点缺少不自动扩展为图边的限制说明")
    comparison_coverage = cooked_missions.get("community_condition_comparison_coverage", {})
    if (
        comparison_coverage.get("condition_count") != 266
        or comparison_coverage.get("missing_comparison_count") != 40
        or comparison_coverage.get("explicit_equal_count") != 0
        or sum(
            comparison_coverage.get("serialized_comparison_counts_including_missing", {}).values()
        ) != 266
    ):
        fail("CommunityMissionCondition Comparison 字段缺失/显式值覆盖统计不符")
    audit_event_names = community_recruitment.get("blueprint_analysis", {}).get("semantics", {}).get("event_name_inventory", {})
    if (
        audit_event_names.get("named_event_records") != event_name_inventory.get("named_event_record_count")
        or audit_event_names.get("cross_type_reuse_groups_per_package_sum") != event_name_inventory.get("cross_type_reuse_group_count_per_package_sum")
    ):
        fail("静态结论摘要中的 EventName 清点数据与 cooked 分析报告不一致")
    audit_comparisons = community_recruitment.get("blueprint_analysis", {}).get("semantics", {}).get("community_condition_comparison_coverage", {})
    if (
        audit_comparisons.get("condition_objects") != comparison_coverage.get("condition_count")
        or audit_comparisons.get("explicit_equal_values") != comparison_coverage.get("explicit_equal_count")
        or audit_comparisons.get("community_members_missing_comparison") != 37
        or "not a verified default" not in audit_comparisons.get("inference", "")
    ):
        fail("Comparison 默认值推断未保留证据限制或与 cooked 报告不一致")
    if community_recruitment.get("native_analysis", {}).get("bounded_caller_bodies_decoded_for_selected_native_research") != xrefs.get("statistics", {}).get("decoded_caller_bodies"):
        fail("社区招募静态结论中的调用者解码数与交叉引用报告不一致")
    if community_recruitment.get("native_analysis", {}).get("verified_direct_edges_in_shared_xref_report") != xrefs.get("statistics", {}).get("verified_direct_call_edges_observed"):
        fail("社区招募静态结论中的直接调用边数与交叉引用报告不一致")

    recruitment_xrefs = community_recruitment_xrefs.get("targets", [])
    if community_recruitment_xrefs.get("schema") != 1 or community_recruitment_xrefs.get("target") != "target.json":
        fail("community-recruitment-native-xrefs.json schema 或目标版本无效")
    if community_recruitment_xrefs.get("target_sha256", "").upper() != sha.upper():
        fail("招募原生调用交叉引用与目标 EXE SHA256 不一致")
    if len(recruitment_xrefs) != community_recruitment.get("native_analysis", {}).get("recruitment_direct_call_targets"):
        fail("招募原生调用交叉引用目标数与摘要不一致")
    if any(
        not row.get("complete_for_bounded_direct_edges") or not row.get("target_in_pdata_function")
        for row in recruitment_xrefs
    ):
        fail("招募原生调用交叉引用含有未完成的受边界保护直接调用目标")
    recruitment_xref_stats = community_recruitment_xrefs.get("statistics", {})
    if recruitment_xref_stats.get("verified_direct_calls") != community_recruitment.get("native_analysis", {}).get("recruitment_direct_calls_verified"):
        fail("招募直接调用数量与静态结论摘要不一致")
    if recruitment_xref_stats.get("verified_tail_jumps") != community_recruitment.get("native_analysis", {}).get("recruitment_tail_jumps_verified"):
        fail("招募尾跳数量与静态结论摘要不一致")
    recruitment_edges = {row.get("id"): row for row in recruitment_xrefs}
    for target_id, expected_calls, expected_jumps in (
        ("population-count-helper", 58, 0),
        ("try-add-character", 2, 0),
        ("try-add-character-record", 12, 1),
    ):
        edge = recruitment_edges.get(target_id, {})
        if edge.get("verified_direct_call_count") != expected_calls or edge.get("verified_tail_jump_count") != expected_jumps:
            fail("招募关键原生调用交叉引用计数不匹配：" + target_id)

    mission_conditions = [
        condition
        for asset in mission_assets
        for condition in asset.get("community_member_conditions", [])
    ]
    mission_finding = next(
        (row for row in community_recruitment.get("asset_findings", [])
         if row.get("id") == "legacy-mission-population-conditions-remain"),
        {},
    )
    if len(mission_conditions) != mission_finding.get("community_member_condition_records"):
        fail("CommunityMembers 条件数量与结论摘要不一致")
    observed_comparisons = {}
    for condition in mission_conditions:
        comparison = condition.get("comparison")
        key = comparison.rsplit("::", 1)[-1] if comparison else "comparison_tag_incomplete"
        observed_comparisons[key] = observed_comparisons.get(key, 0) + 1
    if observed_comparisons != mission_finding.get("primitive_tag_comparison_counts"):
        fail("CommunityMembers 原始标签启发式比较统计与结论摘要不一致")
    if cooked_missions.get("community_member_condition_comparison_counts") != mission_finding.get("comparison_counts"):
        fail("CommunityMembers 结构化 Blueprint 条件比较统计与结论摘要不一致")
    if mission_finding.get("community_member_conditions_without_explicit_comparison") != 37:
        fail("缺失比较符的 CommunityMembers 条件数量未如实记录")
    direct_gate_examples = mission_finding.get("direct_recruitment_gate_examples", [])
    if len(direct_gate_examples) != 5 or any(
        row.get("asset") != "LegacyArcs/Arc_Legacy_Builder.uasset"
        or row.get("comparison") != "LessOrEqual"
        or row.get("value") not in (10, 11)
        or row.get("enclave") != "PlayerCommunity"
        for row in direct_gate_examples
    ):
        fail("直接连接到招募事件的 Builder 遗产人数门槛证据不完整")
    if sum(row.get("value") == 11 for row in direct_gate_examples) != 4 or sum(
        row.get("value") == 10 for row in direct_gate_examples
    ) != 1:
        fail("Builder 遗产直接人数门槛的阈值分布不符")
    unknown_gate = mission_finding.get("direct_recruitment_gate_unknown_comparison", {})
    if unknown_gate.get("comparison") is not None or unknown_gate.get("value") != 11:
        fail("比较符缺失的 Builder 招募条件没有保留为未知")
    if mission_finding.get("capacity_wrapper_calls_in_selected_blueprints") != 0:
        fail("候选 Blueprint 中原生容量包装调用的筛选结果不一致")
    if community_recruitment.get("implementation_boundary", {}).get("current_mod_patch_source") != "GameApi/StateOfDecay2GameApi.cs":
        fail("社区招募静态结论没有指向唯一 Game API 补丁源")

    print("PASS: unified target, 13 patches, %d functions, %d structures, %d static research domains, %d analyzed registrations and manifest exports" %
          (len(functions.get("functions", [])), len(structs.get("structures", [])),
           len(domain_ids), len(body_analysis.get("functions", []))))


if __name__ == "__main__":
    try:
        main()
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise SystemExit("FAIL: " + str(error))
