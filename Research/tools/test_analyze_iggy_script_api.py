from __future__ import annotations

import struct
import unittest

from analyze_iggy_script_api import extract_abc_block, parse_settings_script


def _settings_source(extra_public: str = "") -> str:
    categories = {
        "CATEGORY_DEBUG": 0,
        "CATEGORY_GAMEPLAY": 1,
        "CATEGORY_MULTIPLAYER": 2,
        "CATEGORY_CONTROLS": 3,
        "CATEGORY_ACCESS": 4,
        "CATEGORY_HUD": 5,
        "CATEGORY_VIDEO": 6,
        "CATEGORY_ADVANCED_VIDEO": 7,
        "CATEGORY_AUDIO": 8,
        "CATEGORY_HELP_SUPPORT": 9,
        "CATEGORY_COUNT": 10,
    }
    constants = "\n".join(
        f"private static const {name}:int = {value};"
        for name, value in categories.items()
    )
    category_calls = "\n".join(
        f'this.AddCategory({name}, "ID_{name.removeprefix("CATEGORY_")}", 0);'
        for name in (
            "CATEGORY_GAMEPLAY",
            "CATEGORY_MULTIPLAYER",
            "CATEGORY_CONTROLS",
            "CATEGORY_ACCESS",
            "CATEGORY_HUD",
            "CATEGORY_VIDEO",
            "CATEGORY_ADVANCED_VIDEO",
            "CATEGORY_AUDIO",
            "CATEGORY_HELP_SUPPORT",
        )
    )
    required = {
        "InitializeCategoryMenu": ("private", 0, "void"),
        "AddCategory": ("private", 3, "int"),
        "GetSettingsCategory": ("private", 1, "CategoryTracker"),
        "PopulateSettingsCategory": ("private", 1, "void"),
        "AddSettingToTracker": ("private", 2, "*"),
        "AddTextSetting": ("private", 4, "btn_setting_text"),
        "AddToggleSetting": ("private", 6, "btn_setting_toggle_class"),
        "AddSliderSetting": ("private", 10, "btn_setting_slider"),
        "AddSliderSettingWithValue": ("private", 10, "btn_setting_slider_value"),
        "AddDropdownSetting": ("private", 5, "btn_setting_dropdown"),
        "AddTextBlock": ("private", 2, "container_setting_status_description"),
        "AddSubHeader": ("private", 2, "container_setting_subheader"),
        "ApiInit": ("public", 11, "void"),
        "ApiShow": ("public", 0, "void"),
    }
    methods = []
    for name, (visibility, arity, return_type) in required.items():
        params = ", ".join(f"param{i}:Object" for i in range(arity))
        body = ""
        if name == "InitializeCategoryMenu":
            body = category_calls
        elif name == "AddCategory":
            body = "categoryList.addChild(newButton);"
        elif name == "AddSettingToTracker":
            body = (
                "param1.SettingsList.container_settings.addChild(param2);"
                "param1.ButtonSet.AddButton(param2);param1.Settings.push(param2);"
            )
        methods.append(
            f"{visibility} function {name}({params}) : {return_type} {{ {body} }}"
        )
    methods.append("public function ApiAddKeybindingCategory(a:String,b:int):void {}")
    if extra_public:
        methods.append(extra_public)
    return "\n".join(
        [
            "package {",
            "public class settings extends base_window {",
            constants,
            *methods,
            "}",
            "}",
        ]
    )


class IggyScriptApiTests(unittest.TestCase):
    def test_extracts_bounded_abc_and_rejects_version_or_section_overrun(self) -> None:
        abc = bytes.fromhex("10 00 2e 00") + b"abc-fixture"
        section = struct.pack("<Q", 1) + struct.pack("<I", len(abc)) + abc + bytes(7)
        payload = b"prefix" + section + b"tail"
        extracted, layout = extract_abc_block(
            payload,
            section_offset=6,
            section_end=6 + len(section),
        )
        self.assertEqual(extracted, abc)
        self.assertEqual(layout["abc_length"], len(abc))
        with self.assertRaisesRegex(ValueError, "bounds"):
            extract_abc_block(
                payload,
                section_offset=6,
                section_end=6 + 12 + len(abc) - 1,
            )
        with self.assertRaisesRegex(ValueError, "version"):
            extract_abc_block(
                struct.pack("<Q", 1) + struct.pack("<I", 4) + bytes(4),
                section_offset=0,
                section_end=16,
            )

    def test_settings_builders_are_private_and_keybinding_api_is_not_settings_registration(self) -> None:
        report = parse_settings_script(_settings_source())
        self.assertEqual(report["category_constants"]["CATEGORY_COUNT"], 10)
        self.assertEqual(len(report["initialized_category_calls"]), 9)
        self.assertEqual(report["public_custom_registration_methods"], [])
        self.assertEqual(report["key_method_access"]["AddTextSetting"]["visibility"], "private")
        self.assertTrue(report["private_setting_builder_attaches_control_and_focus_entry"])

    def test_detects_a_new_public_settings_registration_entry_point(self) -> None:
        source = _settings_source("public function ApiAddSetting(a:Object):void {}")
        report = parse_settings_script(source)
        self.assertEqual(report["public_custom_registration_methods"], ["ApiAddSetting"])

    def test_rejects_a_visibility_change_in_the_pinned_script_contract(self) -> None:
        source = _settings_source().replace(
            "private function AddTextSetting(",
            "public function AddTextSetting(",
        )
        with self.assertRaisesRegex(ValueError, "method/access contract changed"):
            parse_settings_script(source)


if __name__ == "__main__":
    unittest.main()
