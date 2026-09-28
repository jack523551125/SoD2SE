"""Fixed-build entry patch retaining all original AVM2 binding identities.

The hidden CATEGORY_DEBUG slot (0) is reused without extending any class.
Only three method bodies and four appended string constants may change.
"""
from __future__ import annotations

import copy
import re
import xml.etree.ElementTree as ET


METHOD_IDS = {"InitializeCategoryMenu": 1343, "SetCategory": 1348, "PopulateSettingsCategory": 1365}


def u30(value: int) -> bytes:
    if not 0 <= value < (1 << 30):
        raise ValueError("u30 overflow")
    out = bytearray()
    while value >= 128:
        out.append((value & 127) | 128)
        value >>= 7
    out.append(value)
    return bytes(out)


class EntryCode:
    def __init__(self):
        self.data = bytearray()
        self.labels = {}
        self.fixups = []

    def op(self, opcode: int, *args: int):
        self.data.append(opcode)
        for arg in args:
            self.data.extend(u30(arg))
        return self

    def text(self, index: int): return self.op(0x2c, index)
    def integer(self, value: int): return self.op(0x25, value)
    def local(self, index: int): return self.op(0x62, index)
    def save(self, index: int): return self.op(0x63, index)

    def label(self, name: str):
        if name in self.labels:
            raise ValueError("Duplicate entry bytecode label: " + name)
        self.labels[name] = len(self.data)
        return self

    def jump(self, opcode: int, name: str):
        self.data.append(opcode)
        self.fixups.append((len(self.data), name))
        self.data.extend(b"\0" * 3)
        return self

    def done(self) -> bytes:
        result = bytearray(self.data)
        for offset, name in self.fixups:
            if name not in self.labels:
                raise ValueError("Unknown entry bytecode label: " + name)
            displacement = self.labels[name] - (offset + 3)
            if displacement < -(1 << 23) or displacement >= (1 << 23):
                raise ValueError("Entry bytecode branch out of range: " + name)
            result[offset:offset + 3] = displacement.to_bytes(3, "little", signed=True)
        return bytes(result)


def instruction_spans(pcode: str, method: str, expected: bytes) -> list[tuple[int, bytes]]:
    marker = f"private function {method}("
    if pcode.count(marker) != 1:
        raise ValueError("Ambiguous P-code method: " + method)
    section = pcode.split(marker, 1)[1]
    match = re.search(r"(?m)^\s*code\s*$", section)
    if not match:
        raise ValueError("No method code")
    section = section[match.end():].split("end ; code", 1)[0]
    parts = [bytes.fromhex(h) for h in re.findall(r"(?m)^\s*; ([0-9a-f]{2}(?: [0-9a-f]{2})*)\s*$", section)]
    if b"".join(parts) != expected:
        raise ValueError("P-code bytes disagree with XML method: " + method)
    spans = []
    offset = 0
    for part in parts:
        spans.append((offset, part))
        offset += len(part)
    return spans


def insert_code(code: bytes, spans: list[tuple[int, bytes]], at: int, extra: bytes) -> bytes:
    """Relocate original branch targets; a jump to insertion enters the new code."""
    starts = {o for o, _ in spans} | {len(code)}
    if at not in starts or b"".join(p for _, p in spans) != code:
        raise ValueError("Insertion must be on a verified instruction boundary")
    out = bytearray(code[:at] + extra + code[at:])
    for offset, instruction in spans:
        opcode = instruction[0]
        if opcode == 0x1b:
            raise ValueError("Switch relocation is not supported by this bounded patcher")
        if 0x0c <= opcode <= 0x1a:
            if len(instruction) != 4:
                raise ValueError("Invalid branch width")
            target = offset + 4 + int.from_bytes(instruction[1:], 'little', signed=True)
            if target not in starts:
                raise ValueError("Original branch does not target an instruction")
            relocated = offset + (len(extra) if offset >= at else 0)
            target += len(extra) if target > at else 0
            relative = target - relocated - 4
            out[relocated + 1:relocated + 4] = relative.to_bytes(3, 'little', signed=True)
    return bytes(out)


def patch_xml(tree: ET.ElementTree, pcode: str) -> dict:
    abc = tree.getroot().find('.//abc')
    if abc is None:
        raise ValueError("Missing ABC")
    before = copy.deepcopy(abc)
    strings = abc.find('constants/constant_string')
    if strings is None or len(strings) != 2925:
        raise ValueError("Pinned original string pool required")
    labels = ['Mod 设置', '返回 / Back', 'SoD2SE_Mcm_v1', 'SoD2SE_ModSettings_Back',
              '入口验证页面；Mod 设置项尚未接入。 / Entry validation page; Mod settings are not connected yet.',
              'Mod Settings', 'Mod 设置 / Mod Settings']
    indices = []
    for value in labels:
        indices.append(len(strings))
        ET.SubElement(strings, 'item').text = value
    push = lambda i: b'\x2c' + u30(indices[i])
    bodies = abc.find('bodies')
    if bodies is None:
        raise ValueError("Missing bodies")
    body_map = {int(b.get('method_info')): b for b in bodies}
    for method in METHOD_IDS.values():
        if len(body_map[method].find('exceptions')):
            raise ValueError("Unexpected exception ranges in entry methods")

    body = body_map[METHOD_IDS['InitializeCategoryMenu']]
    code = bytes.fromhex(body.get('codeBytes'))
    if len(code) != 195 or not code.endswith(bytes.fromhex('d02668c00a47')):
        raise ValueError("Original category initializer does not match")
    # Query the detected game language through the read-only MCM channel, then
    # add the category using the same original button/focus path. If the bridge
    # is not ready yet, use a bilingual label instead of guessing a locale.
    category = EntryCode()
    category.op(0x60, 2025).text(indices[2]).integer(0).integer(0).integer(0).integer(0).op(0x46, 2026, 5).save(2)
    category.op(0x60, 2025).text(indices[2]).integer(14).local(2).integer(0).integer(0).op(0x46, 2026, 5).save(3)
    # AVM2 0x13 is ifeq; 0x14 is ifne.  Branch to the matching language.
    category.local(3).integer(1).jump(0x13, 'chinese')
    category.local(3).integer(2).jump(0x13, 'english')
    category.text(indices[6]).jump(0x10, 'add_category')
    category.label('chinese').text(indices[0]).jump(0x10, 'add_category')
    category.label('english').text(indices[5])
    category.label('add_category')
    extra = bytes.fromhex('d0 24 00') + category.done() + bytes.fromhex('d1 46 f7 09 03 82 d5')
    body.set('codeBytes', insert_code(code, instruction_spans(pcode, 'InitializeCategoryMenu', code),
        len(code) - 6, extra).hex())
    body.set('max_regs', str(max(4, int(body.get('max_regs', '0')))))
    body.set('max_stack', str(max(10, int(body.get('max_stack', '0')))))

    body = body_map[METHOD_IDS['SetCategory']]
    code = bytes.fromhex(body.get('codeBytes'))
    callback = bytes.fromhex('609f022c8115d14ffe0a0247')
    if len(code) != 245 or not code.endswith(callback):
        raise ValueError("Original category callback does not match")
    # if (category == 0) return; never send the private Mod category to C++.
    extra = bytes.fromhex('d124001401000047')
    body.set('codeBytes', insert_code(code, instruction_spans(pcode, 'SetCategory', code),
        len(code) - len(callback), extra).hex())

    body = body_map[METHOD_IDS['PopulateSettingsCategory']]
    code = bytes.fromhex(body.get('codeBytes'))
    if len(code) != 3991:
        raise ValueError("Original population method does not match")
    # Stack-based calls need no new lexical scope, activation, or closure.
    custom = (b'\xd0\xd1' + push(1) + push(2) + bytes.fromhex('d066fc094f870a04')
              + b'\xd0\xd1' + push(3) + bytes.fromhex('4f8c0a0247'))
    condition = bytes.fromhex('d166e10a240014') + len(custom).to_bytes(3, 'little', signed=True)
    body.set('codeBytes', (condition + custom + code).hex())
    verify_only_entry_changes(before, abc)
    return {'category_id': 0, 'category_count': 10, 'category_language': 'runtime-detected-read-only',
            'patched_method_ids': METHOD_IDS, 'appended_string_count': 7,
            'class_method_trait_namespace_identity_preserved': True,
            'unmodified_method_bodies_preserved': True}


def verify_only_entry_changes(before: ET.Element, after: ET.Element) -> None:
    """Fail if the serializer/compiler changes anything outside the allowlist."""
    def normalized(element):
        # FFDec's fileOffset and cached bytes describe serialization, not traits.
        return (element.tag,
                tuple(sorted((k, v) for k, v in element.attrib.items() if k not in ('fileOffset', 'bytes'))),
                (element.text or '').strip() if len(element) else (element.text or ''),
                [normalized(child) for child in element])
    for a, b in zip(before, after, strict=True):
        if a.tag == 'constants':
            for p, q in zip(a, b, strict=True):
                if p.tag == 'constant_string':
                    if len(q) != len(p) + 7:
                        raise ValueError("String append count mismatch")
                    if [normalized(v) for v in p] != [normalized(v) for v in list(q)[:len(p)]]:
                        raise ValueError("Original string indices changed")
                elif normalized(p) != normalized(q):
                    raise ValueError("Original constant pool changed: " + p.tag)
        elif a.tag == 'bodies':
            for p, q in zip(a, b, strict=True):
                copy_q = copy.deepcopy(q)
                if int(p.get('method_info')) in METHOD_IDS.values():
                    copy_q.set('codeBytes', p.get('codeBytes'))
                    for attribute in ('max_regs', 'max_stack'):
                        if p.get(attribute) is None:
                            copy_q.attrib.pop(attribute, None)
                        else:
                            copy_q.set(attribute, p.get(attribute))
                if normalized(p) != normalized(copy_q):
                    raise ValueError("Unexpected method metadata/body change")
        elif normalized(a) != normalized(b):
            raise ValueError("Original binding identity changed: " + a.tag)
