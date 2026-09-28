from __future__ import annotations

import struct
import unittest
import copy
import xml.etree.ElementTree as ET

from analyze_iggy_script_api import make_swf_wrapper
from build_native_mod_settings_entry import abc_from_swf, replace_settings_abc
from patch_native_entry_bytecode import EntryCode, insert_code, verify_only_entry_changes


class ModSettingsEntryTests(unittest.TestCase):
    def test_swf_roundtrip_preserves_abc_bytes(self):
        abc = b"\x10\x00\x2e\x00" + bytes(range(256))
        self.assertEqual(abc_from_swf(make_swf_wrapper(abc)), abc)

    def test_swf_rejects_truncation_extra_tags_and_corrupt_lengths(self):
        original = make_swf_wrapper(b"\x10\x00\x2e\x00abcd")
        for malformed in (original[:-1], original + b"extra", b"CWS" + original[3:]):
            with self.assertRaises(ValueError):
                abc_from_swf(malformed)
        malformed = bytearray(original)
        struct.pack_into("<I", malformed, 22, 0xffffffff)
        with self.assertRaises(ValueError):
            abc_from_swf(bytes(malformed))

    def test_unpinned_game_resource_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "pinned"):
            replace_settings_abc(b"not the target game resource", b"\x10\x00\x2e\x00")

    def test_forward_branch_relocated_across_insertion(self):
        code = bytes.fromhex('11020000020247')
        spans = [(0, code[:4]), (4, b'\x02'), (5, b'\x02'), (6, b'\x47')]
        out = insert_code(code, spans, 5, b'\x02\x02')
        self.assertEqual(out[:4], bytes.fromhex('11040000'))
        self.assertEqual(out[8], 0x47)

    def test_branch_to_insertion_enters_new_guard(self):
        code = bytes.fromhex('110100000247')
        spans = [(0, code[:4]), (4, b'\x02'), (5, b'\x47')]
        out = insert_code(code, spans, 5, b'\x02\x02')
        self.assertEqual(out[:4], code[:4])

    def test_backward_branch_still_reaches_original_target(self):
        code = bytes.fromhex('0210fbffff47')
        spans = [(0, b'\x02'), (1, code[1:5]), (5, b'\x47')]
        out = insert_code(code, spans, 1, b'\x02\x02')
        self.assertEqual(7 + int.from_bytes(out[4:7], 'little', signed=True), 0)

    def test_insertion_inside_instruction_is_rejected(self):
        code = bytes.fromhex('1100000047')
        with self.assertRaises(ValueError):
            insert_code(code, [(0, code[:4]), (4, b'\x47')], 2, b'\x02')

    def test_runtime_language_branch_has_chinese_english_and_unavailable_fallback(self):
        code = EntryCode()
        code.local(3).integer(1).jump(0x14, 'chinese')
        code.local(3).integer(2).jump(0x14, 'english')
        code.text(5).jump(0x10, 'done')
        code.label('chinese').text(6).jump(0x10, 'done')
        code.label('english').text(7).label('done').op(0x47)
        encoded = code.done()
        self.assertIn(bytes.fromhex('62 03 25 01 14'), encoded)
        self.assertIn(bytes.fromhex('62 03 25 02 14'), encoded)
        self.assertIn(bytes.fromhex('2c 05'), encoded)
        self.assertIn(bytes.fromhex('2c 06'), encoded)
        self.assertIn(bytes.fromhex('2c 07'), encoded)

    def test_binding_guard_rejects_namespace_and_unrelated_method_changes(self):
        before = ET.fromstring('<abc><constants><constant_string><item>old</item></constant_string>'
            '<constant_namespace><item kind="5" name_index="0"/></constant_namespace></constants>'
            '<instance_info><item iinit_index="1269"/></instance_info>'
            '<bodies><item method_info="5" codeBytes="47"/><item method_info="1343" codeBytes="47" max_regs="2" max_stack="3"/></bodies></abc>')
        after = copy.deepcopy(before)
        for text in ['entry', 'back', 'channel', 'target', 'status', 'english', 'bilingual']:
            ET.SubElement(after.find('constants/constant_string'), 'item').text = text
        after.find('bodies')[1].set('codeBytes', '0247')
        after.find('bodies')[1].set('max_regs', '4')
        after.find('bodies')[1].set('max_stack', '10')
        verify_only_entry_changes(before, after)
        mutations = [
            ('constants/constant_namespace/item', 'name_index', '2925'),
            ('instance_info/item', 'iinit_index', '1462'),
            ('bodies/item', 'codeBytes', '0247'),
            ('constants/constant_string/item', 'isNull', 'true'),
        ]
        for path, key, value in mutations:
            broken = copy.deepcopy(after)
            broken.find(path).set(key, value)
            with self.assertRaises(ValueError):
                verify_only_entry_changes(before, broken)


if __name__ == "__main__":
    unittest.main()
