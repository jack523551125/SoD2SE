import unittest

from analyze_native_settings_chain import summarize_settings_navigation


def local_variable(name):
    return {"Inst": "EX_InstanceVariable", "Variable": {"Name": name}}


def fixture():
    graph = {
        "Type": "Function",
        "Name": "ExecuteUbergraph_PauseUI_BP",
        "ScriptBytecode": [
            {"Inst": "EX_Jump", "StatementIndex": 1075, "CodeOffset": 713},
            {"Inst": "EX_Jump", "StatementIndex": 906, "CodeOffset": 657},
            {
                "Inst": "EX_LetObj",
                "StatementIndex": 821,
                "Expression": {
                    "Inst": "EX_Context",
                    "ContextExpression": {
                        "Inst": "EX_FinalFunction",
                        "Function": {"ObjectName": "Function'UIManagerComponent:PushMoviePlayer'"},
                        "Parameters": [
                            {"Inst": "EX_ObjectConst", "Value": {"ObjectPath": "/game/ui/settingsui_bp"}}
                        ],
                    },
                },
            },
            {
                "Inst": "EX_LetObj",
                "StatementIndex": 669,
                "Variable": local_variable("SettingsMovie"),
                "Expression": {"Inst": "EX_LocalVariable", "Variable": {"Name": "CallFunc_PushMoviePlayer_ReturnValue2"}},
            },
            {
                "Inst": "EX_LetObj",
                "StatementIndex": 657,
                "Variable": local_variable("SettingsMovie"),
                "Expression": {"Inst": "EX_NoObject"},
            },
            {
                "Inst": "EX_AddMulticastDelegate",
                "StatementIndex": 323,
                "MulticastDelegate": {
                    "RValuePointer": {"ObjectName": "MulticastDelegateProperty'CommonUIMoviePlayer:Closed'"}
                },
            },
            {"Inst": "EX_BindDelegate", "StatementIndex": 300, "FunctionName": "OnSettingsClosed"},
        ],
    }
    entry = lambda target: {
        "Inst": "EX_VirtualFunction",
        "Function": "ExecuteUbergraph_PauseUI_BP",
        "Parameters": [{"Inst": "EX_IntConst", "Value": target}],
    }
    return [
        graph,
        {"Type": "Function", "Name": "DisplaySettings", "ScriptBytecode": [entry(1075)]},
        {"Type": "Function", "Name": "HideSettings", "ScriptBytecode": [entry(906)]},
    ]


class NativeSettingsNavigationTests(unittest.TestCase):
    def test_reports_settings_open_and_close_resource_flow(self):
        report = summarize_settings_navigation(fixture())
        self.assertEqual(report["display_settings"]["entry_point"], 1075)
        self.assertEqual(report["display_settings"]["graph_jump_target"], 713)
        self.assertIn("UIManagerComponent.PushMoviePlayer(/game/ui/settingsui_bp)", report["display_settings"]["operations"])
        self.assertEqual(report["closed_delegate"]["callback"], "OnSettingsClosed")
        self.assertEqual(report["hide_settings"]["operation"], "PauseUI_BP.SettingsMovie = null")

    def test_rejects_unexpected_movie_class(self):
        data = fixture()
        node = next(x for x in data[0]["ScriptBytecode"] if x.get("StatementIndex") == 821)
        node["Expression"]["ContextExpression"]["Parameters"][0]["Value"]["ObjectPath"] = "/game/ui/unverified_mod_page"
        with self.assertRaisesRegex(ValueError, "class changed"):
            summarize_settings_navigation(data)


if __name__ == "__main__":
    unittest.main()
