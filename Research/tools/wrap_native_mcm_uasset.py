"""Replace only the embedded Iggy movie in the pinned Settings UAsset."""
from __future__ import annotations

import argparse
import hashlib
import struct
from pathlib import Path

TEMPLATE_SHA256 = "15b1e4740ecd2a7ec88e39ece94afe2feccf918f844d038db8bd010626f8d423"
OLD_IGGY_SHA256 = "78969f49237fcf1b57d9884b28bd7b8d8a8157d1aa5a18f2570289f09feffd79"
IGGY_OFFSET = 60970
SIZE_FIELDS = (189, 6321, 60954, 60958)


def wrap(template: bytes, movie: bytes) -> bytes:
    if hashlib.sha256(template).hexdigest() != TEMPLATE_SHA256:
        raise ValueError("unexpected Settings UAsset template")
    old_size = struct.unpack_from("<I", template, 60954)[0]
    if template[IGGY_OFFSET + old_size:] != bytes.fromhex("c1832a9e"):
        raise ValueError("Settings UAsset trailer changed")
    if hashlib.sha256(template[IGGY_OFFSET:IGGY_OFFSET + old_size]).hexdigest() != OLD_IGGY_SHA256:
        raise ValueError("embedded Iggy movie changed")
    if old_size != struct.unpack_from("<I", template, 60958)[0]:
        raise ValueError("embedded movie size fields disagree")
    result = bytearray(template[:IGGY_OFFSET] + movie + template[IGGY_OFFSET + old_size:])
    delta = len(movie) - old_size
    for offset in SIZE_FIELDS:
        struct.pack_into("<I", result, offset, struct.unpack_from("<I", template, offset)[0] + delta)
    if result[IGGY_OFFSET:IGGY_OFFSET + len(movie)] != movie:
        raise ValueError("embedded movie does not round-trip")
    if any(a != b for i, (a, b) in enumerate(zip(template[:IGGY_OFFSET], result[:IGGY_OFFSET]))
           if i not in {byte for offset in SIZE_FIELDS for byte in range(offset, offset + 4)}):
        raise ValueError("non-size UAsset header bytes changed")
    return bytes(result)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--movie", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.write_bytes(wrap(args.template.read_bytes(), args.movie.read_bytes()))
    print(hashlib.sha256(args.output.read_bytes()).hexdigest())
