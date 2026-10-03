"""Package one independently owned product using the shared safe resolver."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from Automation.Package import package_mo2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--product-root', type=Path, required=True)
    parser.add_argument('--build-root', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--native-settings-asset', type=Path)
    parser.add_argument('--validate-only', action='store_true')
    args = parser.parse_args(argv)

    product_root = args.product_root.resolve()
    build_root = args.build_root.resolve()
    output = args.output_dir.resolve()
    manifest_path = product_root / 'src' / 'mod.json'
    data = json.loads(manifest_path.read_text(encoding='utf-8'))
    mod = package_mo2.read_mod(manifest_path, expected_id=data.get('id'))
    external = {}
    if args.native_settings_asset is not None:
        external['native-settings-asset'] = args.native_settings_asset.resolve()

    if args.validate_only:
        missing = [source.split(':', 1)[1] for source, _ in mod.files
                   if source.startswith('external:') and source.split(':', 1)[1] not in external]
        if missing:
            print('SKIPPED: approved external input is not attached: ' + ', '.join(missing))
            return 0
        for source, _ in mod.files:
            if source.startswith('build:'):
                generated = build_root.joinpath(*package_mo2.safe_relative(source.split(':', 1)[1]).parts)
                if not generated.exists():
                    continue
            package_mo2.resolve_input(source, product_root, build_root, external)
        print(f'PASS: {mod.id} manifest and package inputs are safe and present')
        return 0

    output.mkdir(parents=True, exist_ok=True)
    package_mo2.package_mod(mod, product_root, build_root, output, external)
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f'ERROR: {error}', file=sys.stderr)
        raise SystemExit(1)
