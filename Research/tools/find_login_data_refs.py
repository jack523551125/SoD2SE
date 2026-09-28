"""Find absolute VA data references to fixed-build login reflection names."""
import struct
import sys
from pe_static import PeImage

image = PeImage(sys.argv[1])
print("image base", hex(image.image_base))
for rva in (0x371A178, 0x3719A88, 0x37BD220, 0x37BB3F0):
    needle = struct.pack("<Q", image.image_base + rva)
    offsets = []
    position = 0
    while (offset := image.data.find(needle, position)) >= 0:
        offsets.append(offset)
        position = offset + 1
    print(hex(rva), len(offsets), [hex(offset) for offset in offsets[:20]])
