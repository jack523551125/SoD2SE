#!/usr/bin/env python3
"""Record verifiable fixed-build links between vanilla settings assets.

Reads only local cooked-export JSON and installed PAK files. The resulting
report contains hashes and selected metadata, never game asset payloads.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from probe_native_settings_asset import ASSET, EXPECTED_SHA256, read_asset


ASSETS = ("Art/UI/settings.json", "UI/SettingsUI_BP.json", "UI/PauseUI_BP.json")


def find_default(exports, class_name):
    candidates = [entry for entry in exports if entry.get("Name") == "Default__" + class_name]
    if len(candidates) != 1:
        raise ValueError("Missing or ambiguous class default: " + class_name)
    return candidates[0]


def walk_json_nodes(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk_json_nodes(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_json_nodes(child)


def get_function(exports, name):
    matches = [
        entry for entry in exports
        if entry.get("Type") == "Function" and entry.get("Name") == name
    ]
    if len(matches) != 1:
        raise ValueError("Missing or ambiguous function: " + name)
    return matches[0]


def get_graph_node(graph, statement_index):
    matches = [
        node for node in graph.get("ScriptBytecode", [])
        if node.get("StatementIndex") == statement_index
    ]
    if len(matches) != 1:
        raise ValueError("Missing or ambiguous graph statement: " + str(statement_index))
    return matches[0]


def get_graph_entry(function, graph_name):
    nodes = function.get("ScriptBytecode", [])
    if len(nodes) < 1 or nodes[0].get("Inst") != "EX_VirtualFunction" or nodes[0].get("Function") != graph_name:
        raise ValueError("Unexpected Blueprint event entry: " + function.get("Name", "<unnamed>"))
    parameters = nodes[0].get("Parameters", [])
    if len(parameters) != 1 or parameters[0].get("Inst") != "EX_IntConst":
        raise ValueError("Unexpected Blueprint entry-point parameter: " + function.get("Name", "<unnamed>"))
    return parameters[0].get("Value")


def get_call(node, expected_name):
    calls = []
    for child in walk_json_nodes(node):
        function = child.get("Function")
        if isinstance(function, dict) and function.get("ObjectName") == expected_name:
            calls.append(child)
    if len(calls) != 1:
        raise ValueError("Missing or ambiguous Blueprint call: " + expected_name)
    return calls[0]


def summarize_settings_navigation(pause):
    graph = get_function(pause, "ExecuteUbergraph_PauseUI_BP")
    display_entry = get_graph_entry(get_function(pause, "DisplaySettings"), "ExecuteUbergraph_PauseUI_BP")
    hide_entry = get_graph_entry(get_function(pause, "HideSettings"), "ExecuteUbergraph_PauseUI_BP")
    display_jump = get_graph_node(graph, display_entry)
    hide_jump = get_graph_node(graph, hide_entry)
    if display_jump.get("Inst") != "EX_Jump" or hide_jump.get("Inst") != "EX_Jump":
        raise ValueError("Settings Blueprint entry points no longer resolve through graph jumps")

    push_statement = 821
    assign_statement = 669
    clear_statement = 657
    push_node = get_graph_node(graph, push_statement)
    push_call = get_call(push_node, "Function'UIManagerComponent:PushMoviePlayer'")
    parameters = push_call.get("Parameters", [])
    class_argument = None
    if len(parameters) == 1 and parameters[0].get("Inst") == "EX_ObjectConst":
        class_argument = parameters[0].get("Value", {}).get("ObjectPath")
    if class_argument != "/game/ui/settingsui_bp":
        raise ValueError("Settings menu PushMoviePlayer class changed")

    assigned = get_graph_node(graph, assign_statement)
    assignment_target = assigned.get("Variable", {}).get("Variable", {}).get("Name")
    assignment_source = assigned.get("Expression", {}).get("Variable", {}).get("Name")
    if assignment_target != "SettingsMovie" or assignment_source != "CallFunc_PushMoviePlayer_ReturnValue2":
        raise ValueError("Settings menu player assignment changed")
    cleared = get_graph_node(graph, clear_statement)
    clear_target = cleared.get("Variable", {}).get("Variable", {}).get("Name")
    if clear_target != "SettingsMovie" or cleared.get("Expression", {}).get("Inst") != "EX_NoObject":
        raise ValueError("Settings menu close cleanup changed")

    close_delegate = get_graph_node(graph, 323)
    closed_event = None
    for child in walk_json_nodes(close_delegate):
        prop = child.get("RValuePointer")
        if isinstance(prop, dict) and prop.get("ObjectName") == "MulticastDelegateProperty'CommonUIMoviePlayer:Closed'":
            closed_event = prop["ObjectName"]
            break
    if closed_event is None:
        raise ValueError("Settings menu Closed delegate binding changed")
    bound_callbacks = [
        child.get("FunctionName")
        for child in walk_json_nodes(graph)
        if child.get("Inst") == "EX_BindDelegate" and child.get("StatementIndex") == 300
    ]
    if bound_callbacks != ["OnSettingsClosed"]:
        raise ValueError("Settings menu close callback binding changed")

    return {
        "display_settings": {
            "entry_point": display_entry,
            "graph_jump_target": display_jump.get("CodeOffset"),
            "operations": [
                "GameplayStatics.GetPlayerController(0)",
                "DaytonFunctionLibrary.GetComponentByClass(UIManagerComponent)",
                "UIManagerComponent.PushMoviePlayer(" + class_argument + ")",
                "store returned player in PauseUI_BP.SettingsMovie",
            ],
        },
        "closed_delegate": {
            "property": closed_event,
            "callback": bound_callbacks[0],
        },
        "hide_settings": {
            "entry_point": hide_entry,
            "graph_jump_target": hide_jump.get("CodeOffset"),
            "operation": "PauseUI_BP.SettingsMovie = null",
            "note": "This verifies reference cleanup; it does not prove a generic close or back-navigation contract.",
        },
        "evidence": {
            "push_statement_index": push_statement,
            "player_assignment_statement_index": assign_statement,
            "close_binding_statement_index": 300,
            "closed_delegate_statement_index": 323,
            "clear_reference_statement_index": clear_statement,
        },
    }


def analyze(pak_root: Path, parser: Path, export_root: Path) -> dict:
    raw, source_pak = read_asset(pak_root, parser)
    if hashlib.sha256(raw).hexdigest() != EXPECTED_SHA256:
        raise ValueError("Unexpected cooked settings asset build")
    cooked_hashes = {}
    for asset_name in (ASSET, "UI/SettingsUI_BP.uasset", "UI/PauseUI_BP.uasset"):
        payload, archive = read_asset(pak_root, parser, asset_name)
        cooked_hashes[asset_name] = {
            "pak": archive,
            "sha256": hashlib.sha256(payload).hexdigest(),
            "size": len(payload),
        }
    exports = {}
    hashes = {}
    for rel in ASSETS:
        path = export_root / rel
        data = path.read_bytes()
        hashes[rel] = hashlib.sha256(data).hexdigest()
        exports[rel] = json.loads(data.decode("utf-8-sig"))
    movie = exports[ASSETS[0]]
    if len(movie) != 1 or movie[0].get("Type") != "IggyPlayer":
        raise ValueError("Expected one IggyPlayer export")
    properties = movie[0]["Properties"]
    settings_default = find_default(exports[ASSETS[1]], "SettingsUI_BP_C")
    player = settings_default["Properties"]["Player"]["ObjectPath"]
    if player.casefold() != "/game/art/ui/settings":
        raise ValueError("SettingsUI_BP player reference changed")
    pause = exports[ASSETS[2]]
    setting_fields = [entry for entry in pause if entry.get("Name") == "SettingsMovie"]
    if len(setting_fields) != 1 or setting_fields[0]["PropertyClass"]["ObjectPath"].casefold() != "/game/ui/settingsui_bp":
        raise ValueError("PauseUI settings class reference changed")
    pause_functions = {entry["Name"] for entry in pause if entry.get("Type") == "Function"}
    required = {"DisplaySettings", "HideSettings", "GetSettingsUI"}
    if not required <= pause_functions:
        raise ValueError("PauseUI settings functions changed")
    settings_navigation = summarize_settings_navigation(pause)
    settings_functions = [entry["Name"] for entry in exports[ASSETS[1]] if entry.get("Type") == "Function"]
    input_functions = [name for name in settings_functions if "DaytonInp" in name]
    controller_path = export_root / "GameModes" / "VanillaPlayerController_BP.json"
    controller_bytes = controller_path.read_bytes()
    hashes["GameModes/VanillaPlayerController_BP.json"] = hashlib.sha256(controller_bytes).hexdigest()
    controller = json.loads(controller_bytes.decode("utf-8-sig"))
    create_character_ui = next(
        (entry for entry in controller if entry.get("Type") == "Function" and entry.get("Name") == "CreateCharacterUI"),
        None,
    )
    if create_character_ui is None:
        raise ValueError("VanillaPlayerController_BP.CreateCharacterUI is missing")
    create_calls = []
    for node in walk_json_nodes(create_character_ui.get("ScriptBytecode", [])):
        function = node.get("Function")
        if isinstance(function, dict) and function.get("ObjectName") == "Function'UIManagerComponent:CreateMoviePlayer'":
            parameters = node.get("Parameters", [])
            value = parameters[0].get("Value", {}) if parameters and isinstance(parameters[0], dict) else {}
            create_calls.append({
                "function": "UIManagerComponent:CreateMoviePlayer",
                "source_asset": "GameModes/VanillaPlayerController_BP.json",
                "class_argument": value.get("ObjectPath") if isinstance(value, dict) else None,
            })
    if not create_calls or any(call["class_argument"] != "/game/ui/characterui_bp" for call in create_calls):
        raise ValueError("Could not verify the built-in movie player class argument")
    api_names = [entry["Name"] for entry in properties["ApiFunctions"]]
    generic_entry_names = [name for name in api_names if any(term in name.casefold() for term in ("modpage", "plugin", "page", "button", "option"))]
    return {
        "schema": 2,
        "target_build": 16535856,
        "method": "offline cooked-export structure inspection and PAK payload hashing",
        "cooked_settings_pak": source_pak,
        "cooked_settings_sha256": EXPECTED_SHA256,
        "cooked_settings_size": len(raw),
        "cooked_assets": cooked_hashes,
        "export_sha256": hashes,
        "resource_chain": [
            "PauseUI_BP.SettingsMovie -> /game/ui/settingsui_bp",
            "PauseUI_BP.DisplaySettings / HideSettings / GetSettingsUI",
            "SettingsUI_BP default Player -> /game/art/ui/settings",
            "Art/UI/settings -> IggyPlayer with TextTable and ApiFunctions",
            "VanillaPlayerController_BP.CreateCharacterUI -> UIManagerComponent.CreateMoviePlayer(CharacterUI_BP_C)",
        ],
        "movie_player_factory_callsite": create_calls,
        "settings_navigation_source": {
            "asset": "UI/PauseUI_BP.json",
            "asset_sha256": hashes["UI/PauseUI_BP.json"],
        },
        "settings_navigation": settings_navigation,
        "settings_text_table_rows": len(properties["TextTable"]),
        "settings_api_functions": api_names,
        "settings_api_name_scan": {
            "generic_page_or_plugin_candidates": generic_entry_names,
            "note": "Name-only scan; absence of a matching name does not prove an undocumented capability is absent.",
        },
        "settings_input_binding_functions": input_functions,
        "limitations": [
            "Serialized references and input event names do not prove focus or gamepad behavior.",
            "TextTable and ApiFunctions metadata do not reveal an editable Iggy control tree.",
            "No compatible Iggy content authoring/rebuild path or in-game loading of edited assets is established.",
        ],
    }


def main():
    arg = argparse.ArgumentParser(description=__doc__)
    arg.add_argument("--pak-root", required=True, type=Path)
    arg.add_argument("--u4pak-module", required=True, type=Path)
    arg.add_argument("--export-root", required=True, type=Path)
    arg.add_argument("--report", required=True, type=Path)
    options = arg.parse_args()
    result = analyze(options.pak_root, options.u4pak_module, options.export_root)
    options.report.parent.mkdir(parents=True, exist_ok=True)
    options.report.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("PASS: vanilla settings resource chain documented")


if __name__ == "__main__":
    main()
