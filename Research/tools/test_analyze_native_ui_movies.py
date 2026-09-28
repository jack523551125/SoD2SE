from __future__ import annotations

import struct
import unittest

from analyze_native_ui_movies import (
    _analyze_hud_extension,
    _analyze_map_extension,
    _public_methods,
    extract_chained_abc_blocks,
    make_swf_wrapper_for_abc_blocks,
)


class NativeUiMovieAnalysisTests(unittest.TestCase):
    @staticmethod
    def _abc(payload: bytes = b"x") -> bytes:
        return struct.pack("<HH", 16, 46) + payload

    def test_extracts_step_linked_abc_records_and_terminal_padding(self) -> None:
        first = self._abc(b"ab")
        terminal = self._abc()
        first_step = 12 + len(first) + 5
        section = (
            struct.pack("<QI", first_step, len(first)) + first + b"\xaa" * 5
            + struct.pack("<QI", 1, len(terminal)) + terminal + b"\0\0\0\0"
        )

        blocks, layout = extract_chained_abc_blocks(
            b"prefix" + section,
            section_offset=6,
            section_end=6 + len(section),
            expected_block_count=2,
        )

        self.assertEqual(blocks, [first, terminal])
        self.assertEqual(layout["block_count"], 2)
        self.assertEqual(layout["abc_total_length"], len(first) + len(terminal))
        self.assertEqual(layout["trailing_padding_length"], 4)
        self.assertTrue(layout["trailing_padding_all_zero"])

    def test_rejects_overlapping_or_out_of_bounds_chained_steps(self) -> None:
        abc = self._abc(b"ab")
        overlapping = struct.pack("<QI", 12, len(abc)) + abc
        out_of_bounds = struct.pack("<QI", 1000, len(abc)) + abc
        for section, message in ((overlapping, "overlaps"), (out_of_bounds, "outside")):
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                extract_chained_abc_blocks(section, section_offset=0, section_end=len(section))

    def test_rejects_invalid_abc_version_and_missing_terminal_record(self) -> None:
        wrong_version = struct.pack("<HH", 16, 45) + b"x"
        section = struct.pack("<QI", 1, len(wrong_version)) + wrong_version
        with self.assertRaisesRegex(ValueError, "version"):
            extract_chained_abc_blocks(section, section_offset=0, section_end=len(section))

        valid = self._abc()
        section = struct.pack("<QI", 12 + len(valid), len(valid)) + valid
        with self.assertRaisesRegex(ValueError, "terminal"):
            extract_chained_abc_blocks(section, section_offset=0, section_end=len(section))

    def test_wraps_each_abc_block_in_a_distinct_doabc_tag(self) -> None:
        blocks = [self._abc(b"one"), self._abc(b"two")]
        wrapper = make_swf_wrapper_for_abc_blocks(blocks)
        tag_header = struct.pack("<H", (82 << 6) | 63)
        self.assertEqual(wrapper[:3], b"FWS")
        self.assertEqual(struct.unpack_from("<I", wrapper, 4)[0], len(wrapper))
        self.assertEqual(wrapper.count(tag_header), 2)

    def test_extracts_public_movie_method_shape_without_parameter_names(self) -> None:
        source = """
        public function ApiAddOrUpdateCharacterStatus(id:int, name:String, health:Number):void
        {
        }
        private function InternalLayout():void
        {
        }
        public function ApiShowCharacterOverlays():*
        {
        }
        """
        methods = _public_methods(source)
        self.assertEqual(methods["ApiAddOrUpdateCharacterStatus"], {"parameter_count": 3, "return_type": "void"})
        self.assertEqual(methods["ApiShowCharacterOverlays"], {"parameter_count": 0, "return_type": "*"})
        self.assertNotIn("InternalLayout", methods)

    def test_counts_parameters_with_default_values_and_empty_parameters(self) -> None:
        source = "public function ApiStatus(id:int, visible:Boolean = true):void {}\npublic function ApiReset():void {}"
        methods = _public_methods(source)
        self.assertEqual(methods["ApiStatus"]["parameter_count"], 2)
        self.assertEqual(methods["ApiReset"]["parameter_count"], 0)

    def test_recognizes_native_hud_notifications_and_recyclable_effect_bubbles(self) -> None:
        methods = {
            "ApiNotification": {"parameter_count": 3},
            "ApiAddMiscEffect": {"parameter_count": 4},
            "ApiUpdateMiscEffectState": {"parameter_count": 2},
            "ApiRemoveMiscEffect": {"parameter_count": 2},
            "ApiSetStats": {"parameter_count": 6},
            "ApiMissionNewMission": {"parameter_count": 6},
            "ApiMissionNewObjective": {"parameter_count": 5},
            "ApiSearchSetProgress": {"parameter_count": 2},
        }
        root = (
            "this.menu_notification.Notify(icon,header,message);"
            "this.menu_effects.container_effects.AddMiscEffect(ID,iconName,iconState,doTransitions);"
            "this.menu_effects.container_effects.UpdateMiscEffectState(ID,iconState);"
            "this.menu_effects.container_effects.RemoveMiscEffect(ID,doTransitions);"
        )
        notification = (
            "new Timer(3000,1);"
            "this.txt_notification_header.txt_notification_header_text.text.text=header;"
            "this.txt_notification_body.txt_notification_body_text.text.text=message;"
            "this.m_timer.reset();this.m_timer.start();"
        )
        effects = (
            "this.bubbleCache.NewObject();this.activeEffects.push(effectBubble);addChild(effectBubble);"
            "effect.ID==ID;this.activeEffects.splice(i,1);this.bubbleCache.StoreObject(effect);"
            "throw new Error('unknown ID');throw new Error('unknown ID');"
        )
        bubble = "this.icon_effect.icon_effect_art.SetTexture(iconName);"

        summary = _analyze_hud_extension(root, notification, effects, bubble, methods)

        self.assertEqual(summary["notification"]["auto_hide_after_ms"], 3000)
        self.assertTrue(summary["effect_bubbles"]["creates_movie_clip_and_adds_to_display_list"])
        self.assertTrue(summary["effect_bubbles"]["reuses_removed_movie_clips"])
        self.assertTrue(summary["effect_bubbles"]["unknown_update_or_remove_id_throws"])

    def test_rejects_hud_api_signature_or_lifecycle_drift(self) -> None:
        methods = {name: {"parameter_count": 0} for name in (
            "ApiNotification", "ApiAddMiscEffect", "ApiUpdateMiscEffectState", "ApiRemoveMiscEffect",
            "ApiSetStats", "ApiMissionNewMission", "ApiMissionNewObjective", "ApiSearchSetProgress",
        )}
        with self.assertRaisesRegex(ValueError, "signatures"):
            _analyze_hud_extension("", "", "", "", methods)

    def test_recognizes_map_objective_location_adapter_contract(self) -> None:
        api_signatures = {
            "ApiAddOrUpdateMission": 12,
            "ApiAddOrUpdateObjective": 7,
            "ApiAddOrUpdateObjectiveLocation": 4,
            "ApiRemoveObjectiveLocation": 2,
            "ApiRemoveMission": 1,
            "ApiRemoveObjective": 1,
        }
        root = "\n".join(
            f"public function {name}(" + ",".join(f"p{i}:int" for i in range(arity)) + "):void {"
            + "this.m_mapContainer.infoLayer.missionLayer." + call + ";"
            + "this.m_minimap.UpdateOffscreenIndicatorPriorities();}"
            for name, arity, call in (
                ("ApiAddOrUpdateMission", 12, "AddOrUpdateMission(" + ",".join(f"param{i}" for i in range(1, 13)) + ")"),
                ("ApiAddOrUpdateObjective", 7, "AddOrUpdateObjective(" + ",".join(f"param{i}" for i in range(1, 8)) + ")"),
                ("ApiAddOrUpdateObjectiveLocation", 4, "AddOrUpdateObjectiveLocation(param1,param2,param3,param4)"),
                ("ApiRemoveObjectiveLocation", 2, "RemoveObjectiveLocation(param1,param2)"),
                ("ApiRemoveMission", 1, "RemoveMission(param1)"),
                ("ApiRemoveObjective", 1, "RemoveObjectiveByHandle(param1)"),
            )
        )
        mission_layer = """
            public function AddOrUpdateObjective(param1:int,param2:int,param3:String,param4:uint,param5:String,param6:int,param7:Boolean):void {}
            public function AddOrUpdateObjectiveLocation(param1:int,param2:int,param3:Number,param4:Number):* {
              var objectiveHandle:int=param1; var locationHandle:int=param2;
              var mapLocationX:Number=param3; var mapLocationY:Number=param4;
              var foundObjective:Objective=this.m_objectives[objectiveHandle] as Objective;
              if(Boolean(foundObjective)) {
                var foundLocation:ObjectiveLocation=foundObjective.FindLocationByHandle(locationHandle);
                if(Boolean(foundLocation)) { foundLocation.x=mapLocationX; }
                else {
                  var newLocation:ObjectiveLocation=new ObjectiveLocation(locationHandle,foundObjective,this);
                  newLocation.x=mapLocationX; newLocation.y=mapLocationY+yAdjustment;
                  foundObjective.AddLocation(newLocation);
                  if(Boolean(foundObjective.owningMission)) { newLocation.Show(); }
                }
                return;
              }
              var errorMsg:String="missing objective"; throw new Error(errorMsg);
            }
            public function RemoveObjectiveLocation(param1:int,param2:int):* {
              var _loc3_:Objective=this.m_objectives[param1] as Objective;
              if(Boolean(_loc3_)) { var _loc4_:ObjectiveLocation=_loc3_.FindLocationByHandle(param2);
                if(Boolean(_loc4_)) { this.RemoveLocationFromMap(_loc4_); _loc3_.RemoveLocation(_loc4_); }
                return;
              }
              var _loc5_:String="missing objective"; throw new Error(_loc5_);
            }
        """

        result = _analyze_map_extension(root, mission_layer, _public_methods(root))

        self.assertTrue(result["objective_locations"]["requires_preexisting_objective_handle"])
        self.assertTrue(result["objective_locations"]["new_location_is_shown_only_when_objective_has_owning_mission"])
        self.assertFalse(result["custom_interactive_controls"])

    def test_rejects_map_objective_location_without_mission_handle_guard(self) -> None:
        signatures = {
            "ApiAddOrUpdateMission": 12,
            "ApiAddOrUpdateObjective": 7,
            "ApiAddOrUpdateObjectiveLocation": 4,
            "ApiRemoveObjectiveLocation": 2,
            "ApiRemoveMission": 1,
            "ApiRemoveObjective": 1,
        }
        root = " ".join(
            f"public function {name}(" + ",".join(f"p{i}:int" for i in range(arity)) + "):void {}"
            for name, arity in signatures.items()
        )
        methods = {name: {"parameter_count": arity} for name, arity in signatures.items()}
        with self.assertRaisesRegex(ValueError, "forwards"):
            _analyze_map_extension(root, "", methods)


if __name__ == "__main__":
    unittest.main()
