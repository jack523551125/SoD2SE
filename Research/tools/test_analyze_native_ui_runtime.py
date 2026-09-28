import unittest
from types import SimpleNamespace

from analyze_native_ui_runtime import check_required_calls, direct_call_targets


class NativeUiDisassemblyTests(unittest.TestCase):
    def test_keeps_only_direct_immediate_calls(self):
        def call(target):
            return SimpleNamespace(
                group=lambda group: True,
                operands=[SimpleNamespace(type=1, imm=target)],
            )

        def indirect_call():
            return SimpleNamespace(
                group=lambda group: True,
                operands=[SimpleNamespace(type=2, imm=None)],
            )

        def non_call():
            return SimpleNamespace(group=lambda group: False, operands=[])

        self.assertEqual(direct_call_targets([call(0x1234), indirect_call(), non_call()], 5, 1), [0x1234])

    def test_required_edges_fail_closed(self):
        summaries = {
            name: {"direct_call_targets": [hex(value) for value in values]}
            for name, values in {
                "create_movie_player": (0x7CB060,),
                "create_movie_player_filter": (0x7CC2E0, 0xA2F090),
                "push_movie_player": (0x7DFB80,),
                "push_movie_player_internal": (0x7CC2E0, 0xA2F090),
                "get_movie_source_path_info": (0x74CB20, 0x1B540D0, 0x10AB810),
                "pass_input_to_iggy": (0x759C60,),
            }.items()
        }
        check_required_calls(summaries)
        summaries["create_movie_player"]["direct_call_targets"] = []
        with self.assertRaisesRegex(ValueError, "create_movie_player"):
            check_required_calls(summaries)


if __name__ == "__main__":
    unittest.main()
