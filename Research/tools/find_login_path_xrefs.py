"""Find RIP-relative references to login strings in the pinned native image."""
from __future__ import annotations

import bisect
import hashlib
import json
import sys
from pathlib import Path
import capstone
from pe_static import PeImage

image = PeImage(Path(sys.argv[1]))
names = (b"FrontendLoginCallbackProxy.cpp\0", b"EDaytonLoginStatus\0",
         b"SaveGame_NoUser\0", b"Login_NoOfflineCredentials\0", b"OnUserLoggedIn\0")
targets = {}
for needle in names:
    start = 0
    while (offset := image.data.find(needle, start)) >= 0:
        for section in image.sections:
            if section.raw_offset <= offset < section.raw_offset + section.raw_size:
                targets[section.virtual_address + offset - section.raw_offset] = needle[:-1].decode()
                break
        start = offset + 1

decoder = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
decoder.detail = True
rows = []
for section in image.sections:
    if not section.is_executable:
        continue
    code = image.data[section.raw_offset:section.raw_offset + section.raw_size]
    for offset in range(1, len(code) - 7):
        if code[offset] not in (0x8d, 0x8b, 0x89) or code[offset - 1] not in range(0x40, 0x50):
            continue
        rva = section.virtual_address + offset - 1
        decoded = list(decoder.disasm(code[offset - 1:offset + 7], rva, count=1))
        if not decoded:
            continue
        instruction = decoded[0]
        for operand in instruction.operands:
            if operand.type == capstone.CS_OP_MEM and operand.mem.base == capstone.x86.X86_REG_RIP:
                target = instruction.address + instruction.size + operand.mem.disp
                if target in targets:
                    index = bisect.bisect_right(image._function_starts, rva) - 1
                    fn = image.function_ranges[index] if index >= 0 else None
                    rows.append(dict(string=targets[target], string_rva=hex(target), site_rva=hex(rva),
                                     instruction=f"{instruction.mnemonic} {instruction.op_str}",
                                     function_rva=hex(fn[0]) if fn and rva < fn[1] else None))
                break
print(json.dumps(dict(image_sha256=hashlib.sha256(image.data).hexdigest(), xrefs=rows), indent=2))
