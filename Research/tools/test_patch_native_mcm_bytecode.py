from __future__ import annotations

import unittest

from patch_native_mcm_bytecode import Code


class NativeMcmBytecodeTests(unittest.TestCase):
    def test_forward_and_backward_branches_land_on_labels(self) -> None:
        code = Code()
        code.label("start").op(0x24, 1).jump(0x10, "start")
        code.jump(0x14, "finish").op(0x24, 2).label("finish").op(0x47)
        encoded = code.done()

        backward_end = 6
        backward_target = backward_end + int.from_bytes(encoded[3:6], "little", signed=True)
        forward_opcode = 6
        forward_end = forward_opcode + 4
        forward_target = forward_end + int.from_bytes(encoded[forward_opcode + 1:forward_opcode + 4], "little", signed=True)

        self.assertEqual(backward_target, 0)
        self.assertEqual(forward_target, 12)
        self.assertEqual(encoded[forward_target], 0x47)

    def test_missing_branch_label_is_rejected(self) -> None:
        code = Code().jump(0x10, "missing")
        with self.assertRaisesRegex(ValueError, "Unknown branch label"):
            code.done()


if __name__ == "__main__":
    unittest.main()
