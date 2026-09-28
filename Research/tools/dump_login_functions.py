"""Dump bounded native bodies for login string registrations."""
import sys
import capstone
from pe_static import PeImage

image = PeImage(sys.argv[1])
decoder = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
for start in (0x84BE3A, 0xC9CD10, 0xCE0940, 0xF47242, 0xF7B849):
    end = next(end for entry, end in image.function_ranges if entry == start)
    size = max(end - start, 700 if start in (0x84BE3A, 0xCE0940) else 0)
    offset = image.rva_to_offset(start, size)
    print(f"\nFUNCTION {start:x}-{end:x}")
    for instruction in decoder.disasm(image.data[offset:offset + size], start):
        if start == 0x84BE3A and not 0x84C150 <= instruction.address <= 0x84C2C0:
            continue
        if instruction.address >= start + (1500 if start == 0x84BE3A else 600 if start == 0xCE0940 else 300):
            break
        print(f"{instruction.address:x}: {instruction.mnemonic} {instruction.op_str}")
