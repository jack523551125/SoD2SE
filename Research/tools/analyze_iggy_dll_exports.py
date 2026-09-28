#!/usr/bin/env python3
"""Read Iggy DLL export names statically; do not load or call the DLL."""

import argparse
import hashlib
import json
import struct
from pathlib import Path

from pe_static import PeImage


def export_names(image):
    data = image.data
    pe_offset = struct.unpack_from("<I", data, 0x3C)[0]
    optional = pe_offset + 24
    directory_rva, directory_size = struct.unpack_from("<II", data, optional + 112)
    if not directory_rva or directory_size < 40:
        raise ValueError("DLL has no export directory")
    directory = image.rva_to_offset(directory_rva, 40)
    fields = struct.unpack_from("<IIHHIIIIIII", data, directory)
    count, names_rva = fields[7], fields[9]
    if count > 100000:
        raise ValueError("Implausible export count")
    names = []
    for index in range(count):
        pointer = image.rva_to_offset(names_rva + 4 * index, 4)
        name_rva = struct.unpack_from("<I", data, pointer)[0]
        start = image.rva_to_offset(name_rva)
        end = data.find(b"\0", start, start + 1024)
        if end < 0:
            raise ValueError("Unterminated export name")
        names.append(data[start:end].decode("ascii"))
    return names


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dll", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    image = PeImage(args.dll)
    names = export_names(image)
    selected = [name for name in names if name.startswith(("IggyPlayerCall", "IggyPlayerSetFocus", "IggyValueRef", "IggyValueSet"))]
    report = {
        "schema": 1,
        "scope": "DLL export names only; no invocation, parameter contract or display-list semantics",
        "dll_name": args.dll.name,
        "dll_sha256": hashlib.sha256(image.data).hexdigest(),
        "export_count": len(names),
        "selected_exports": selected,
        "limit": "Call/ValueRef APIs suggest a possible runtime research route, but do not prove arbitrary Iggy controls can be created or inserted into the current settings movie.",
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print("PASS: statically enumerated %d Iggy DLL exports" % len(names))


if __name__ == "__main__":
    main()
