"""Offline instruction inspection; never opens or modifies a process."""
import argparse
import capstone
from pe_static import PeImage


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image")
    parser.add_argument("rva", type=lambda value: int(value, 0))
    parser.add_argument("--size", type=lambda value: int(value, 0), default=0x600)
    args = parser.parse_args()
    image = PeImage(args.image)
    decoder = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    decoder.detail = True
    offset = image.rva_to_offset(args.rva, args.size)
    for instruction in decoder.disasm(image.data[offset:offset + args.size], args.rva):
        annotations = []
        for operand in instruction.operands:
            if operand.type != capstone.CS_OP_MEM or operand.mem.base != capstone.x86.X86_REG_RIP:
                continue
            target = instruction.address + instruction.size + operand.mem.disp
            annotations.append(hex(target))
            try:
                start = image.rva_to_offset(target)
                raw = image.data[start:start + 240]
                ascii_text = raw.split(b"\0", 1)[0]
                if len(ascii_text) >= 4 and all(32 <= item < 127 for item in ascii_text):
                    annotations.append(repr(ascii_text.decode("ascii")))
                else:
                    wide = raw.decode("utf-16-le", errors="replace").split("\0", 1)[0]
                    if len(wide) >= 4 and all(32 <= ord(item) < 127 for item in wide):
                        annotations.append(repr(wide))
            except ValueError:
                pass
        print(f"{instruction.address:08x} {instruction.mnemonic:8} {instruction.op_str:52} {'; '.join(annotations)}")


if __name__ == "__main__":
    main()
