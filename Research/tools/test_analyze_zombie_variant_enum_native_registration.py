import unittest

from analyze_zombie_variant_enum_native_registration import infer_enum_mapping


class ZombieVariantEnumNativeRegistrationTests(unittest.TestCase):
    def setUp(self):
        self.names = [
            "EZombieVariantType::Slow",
            "EZombieVariantType::Unique",
            "EZombieVariantType::Fast",
            "EZombieVariantType::Armored",
            "EZombieVariantType::Plague",
            "EZombieVariantType::EZombieVariantType_MAX",
        ]

    def test_index_fallback_maps_members_and_max_sentinel(self):
        table = [{"name": name} for name in self.names]
        self.assertEqual(
            infer_enum_mapping(table, explicit_values_pointer_is_null=True),
            [
                {"name": "Slow", "candidate_numeric_value": 0},
                {"name": "Unique", "candidate_numeric_value": 1},
                {"name": "Fast", "candidate_numeric_value": 2},
                {"name": "Armored", "candidate_numeric_value": 3},
                {"name": "Plague", "candidate_numeric_value": 4},
                {"name": "EZombieVariantType_MAX", "candidate_numeric_value": 5},
            ],
        )

    def test_rejects_explicit_values_pointer(self):
        with self.assertRaisesRegex(ValueError, "explicit enum numeric values"):
            infer_enum_mapping([{"name": name} for name in self.names], explicit_values_pointer_is_null=False)

    def test_rejects_reordered_name_table(self):
        wrong_order = self.names.copy()
        wrong_order[0], wrong_order[1] = wrong_order[1], wrong_order[0]
        with self.assertRaisesRegex(ValueError, "incomplete, reordered"):
            infer_enum_mapping([{"name": name} for name in wrong_order], explicit_values_pointer_is_null=True)


if __name__ == "__main__":
    unittest.main()
