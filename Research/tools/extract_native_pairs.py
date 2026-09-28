#!/usr/bin/env python3
"""Extract probable UE FNameNativePtrPair records from a local game executable."""

import argparse
import json
from pathlib import Path

from pe_static import PeImage


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("executable", type=Path, help="local StateOfDecay2-Win64-Shipping.exe")
    parser.add_argument("--output", required=True, type=Path, help="path for derived name/RVA JSON")
    args = parser.parse_args(argv)
    try:
        image = PeImage(args.executable)
        pairs = list(image.iter_native_pairs())
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(pairs, indent=2), encoding="utf-8")
    except (OSError, ValueError, json.JSONDecodeError) as error:
        parser.error(str(error))
    print(f"image base: 0x{image.image_base:X}")
    print(f"sections: {len(image.sections)}; probable native pairs: {len(pairs)}")
    print(f"wrote derived metadata: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
