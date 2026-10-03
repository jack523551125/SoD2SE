"""Build MO2 archives from per-Mod manifests without reading an installed game.

Only the package metadata and files named in mod.json enter an archive. The
framework package intentionally has no meta.ini because it is installed beside
the game rather than managed as an MO2 Mod.
"""

from __future__ import annotations

# Standalone script execution resolves imports from its source-owning project.
import sys as _layout_sys
from pathlib import Path as _LayoutPath
_layout_sys.path.insert(0, str(_LayoutPath(__file__).resolve().parents[2]))

from Automation.source_layout import work_root
import argparse
import hashlib
import json
import re
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


SOURCE_ROOT = Path(__file__).resolve().parents[2]
VERSION_RE = re.compile(r'^\d+\.\d+\.\d+(?:-[A-Za-z0-9.-]+)?$')
ID_RE = re.compile(r'^[A-Za-z][A-Za-z0-9]*$')
FRAMEWORK_RE = re.compile(r'public\s+const\s+string\s+Version\s*=\s*"([^"]+)"\s*;')
FIXED_DATE = (2026, 1, 1, 0, 0, 0)


class PackageError(ValueError):
    pass


@dataclass(frozen=True)
class Mod:
    id: str
    name: str
    version: str
    publish: bool
    requires: tuple[str, ...]
    files: tuple[tuple[str, str], ...]
    manifest: Path


def safe_relative(value: str) -> PurePosixPath:
    if not isinstance(value, str) or not value or '\\' in value:
        raise PackageError(f"Use a nonempty forward-slash relative path: {value!r}")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in ('', '.', '..') for part in value.split('/')):
        raise PackageError(f"Unsafe relative path: {value!r}")
    return path


def read_mod(path: Path, expected_id: str | None = None) -> Mod:
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise PackageError(f"Cannot read {path}: {error}") from error
    if not isinstance(data, dict) or data.get('schema') != 1:
        raise PackageError(f"Unsupported Mod manifest: {path}")
    mod_id, name, version = data.get('id'), data.get('name'), data.get('version')
    if not isinstance(mod_id, str) or not ID_RE.fullmatch(mod_id) or mod_id != (expected_id if expected_id is not None else path.parent.name):
        raise PackageError(f"Mod ID must equal its folder name: {path}")
    if not isinstance(name, str) or not name.strip() or '\n' in name or '\r' in name:
        raise PackageError(f"Invalid display name: {path}")
    if not isinstance(version, str) or not VERSION_RE.fullmatch(version):
        raise PackageError(f"Invalid version: {path}")
    if type(data.get('publish')) is not bool:
        raise PackageError(f"publish must be boolean: {path}")
    requires = data.get('requires')
    if not isinstance(requires, list) or any(not isinstance(x, str) or not x.strip() or '\n' in x for x in requires):
        raise PackageError(f"Invalid dependencies: {path}")
    rows = data.get('files')
    if not isinstance(rows, list) or not rows:
        raise PackageError(f"No package files: {path}")
    files: list[tuple[str, str]] = []
    targets: set[str] = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != {'input', 'target'}:
            raise PackageError(f"Invalid file mapping: {path}")
        source, target = row['input'], row['target']
        if not isinstance(source, str) or ':' not in source:
            raise PackageError(f"Invalid input: {path}")
        origin, relative = source.split(':', 1)
        if origin not in {'build', 'source', 'external'}:
            raise PackageError(f"Unknown input origin: {source}")
        safe_relative(relative)
        destination = safe_relative(target).as_posix()
        if destination.split('/')[0] not in {'Root', 'Saved'} or destination.lower() == 'meta.ini':
            raise PackageError(f"Invalid MO2 target: {target}")
        if destination.lower() in targets:
            raise PackageError(f"Duplicate MO2 target: {target}")
        targets.add(destination.lower())
        files.append((source, destination))
    return Mod(mod_id, name, version, data['publish'], tuple(requires), tuple(files), path)


def discover_mods(source_root: Path = SOURCE_ROOT) -> list[Mod]:
    mods: list[Mod] = []
    seen: set[str] = set()
    for group in ('Plugins', 'Mods'):
        directory = source_root / group
        for folder in sorted((p for p in directory.iterdir() if p.is_dir()), key=lambda p: p.name.lower()):
            manifest = folder / 'mod.json'
            if not manifest.is_file():
                raise PackageError(f"Missing mod.json: {folder}")
            mod = read_mod(manifest)
            if mod.id.lower() in seen:
                raise PackageError(f"Duplicate Mod ID: {mod.id}")
            seen.add(mod.id.lower())
            mods.append(mod)
    return mods


def framework_version(source_root: Path = SOURCE_ROOT) -> str:
    source = (source_root / 'Core' / 'SoD2SE.Core.cs').read_text(encoding='utf-8')
    matches = FRAMEWORK_RE.findall(source)
    if len(matches) != 1 or not VERSION_RE.fullmatch(matches[0]):
        raise PackageError('FrameworkInfo.Version must have one valid value')
    return matches[0]


def resolve_input(spec: str, source_root: Path, build_root: Path, external: dict[str, Path]) -> Path:
    origin, relative = spec.split(':', 1)
    if origin == 'external':
        if relative not in external:
            raise PackageError(f"Missing external input: {relative}")
        candidate = external[relative].resolve()
    else:
        root = (build_root if origin == 'build' else source_root).resolve()
        candidate = root.joinpath(*safe_relative(relative).parts).resolve()
        if not candidate.is_relative_to(root):
            raise PackageError(f"Input escapes {origin} root: {spec}")
    if not candidate.is_file():
        raise PackageError(f"Package input missing: {candidate}")
    return candidate


def meta_ini(mod: Mod, version: str, archive_name: str) -> bytes:
    notes = f"Requires: {', '.join(mod.requires)}" if mod.requires else 'No framework dependency.'
    lines = ('[General]', 'gameName=State of Decay 2', 'modID=0',
             f'version={version}', f'newestVersion={version}', 'category=SoD2SE',
             f'installationFile={archive_name}', f'name={mod.name}',
             f'soD2seId={mod.id}', f'notes={notes}', '')
    return '\n'.join(lines).encode('utf-8')


def write_archive(path: Path, entries: dict[str, bytes]) -> str:
    if path.exists():
        raise PackageError(f"Archive already exists; choose a fresh output directory: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(prefix='.sod2-package-', suffix='.zip', dir=path.parent, delete=False) as tmp:
        temporary = Path(tmp.name)
    try:
        with ZipFile(temporary, 'w', compression=ZIP_DEFLATED) as archive:
            for name, contents in sorted(entries.items()):
                info = ZipInfo(name, FIXED_DATE)
                info.compress_type = ZIP_DEFLATED
                info.external_attr = 0o644 << 16
                archive.writestr(info, contents)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def package_mod(mod: Mod, source_root: Path, build_root: Path, output: Path,
                external: dict[str, Path]) -> Path:
    path, entries = prepare_mod(mod, source_root, build_root, output, external)
    digest = write_archive(path, entries)
    print(f'PACKAGED {path} SHA256={digest}')
    return path


def prepare_mod(mod: Mod, source_root: Path, build_root: Path, output: Path,
                external: dict[str, Path]) -> tuple[Path, dict[str, bytes]]:
    archive_name = f'SoD2-{mod.id}-MO2-v{mod.version}.zip'
    entries = {'meta.ini': meta_ini(mod, mod.version, archive_name)}
    for source, target in mod.files:
        entries[target] = resolve_input(source, source_root, build_root, external).read_bytes()
    return output / archive_name, entries


def package_framework(source_root: Path, build_root: Path, output: Path) -> Path:
    path, entries = prepare_framework(source_root, build_root, output)
    digest = write_archive(path, entries)
    print(f'PACKAGED {path} SHA256={digest}')
    return path


def prepare_framework(source_root: Path, build_root: Path, output: Path) -> tuple[Path, dict[str, bytes]]:
    version = framework_version(source_root)
    names = ('SoD2SE.Loader.exe', 'SoD2SE.Core.dll', 'SoD2SE.GameApi.dll')
    entries = {name: resolve_input(f'build:{name}', source_root, build_root, {}).read_bytes() for name in names}
    path = output / f'SoD2SE-Framework-MO2-v{version}.zip'
    return path, entries


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build-dir', type=Path, default=work_root(SOURCE_ROOT) / 'build')
    parser.add_argument('--output-dir', type=Path, default=SOURCE_ROOT.parent.parent / 'dist')
    parser.add_argument('--native-settings-asset', type=Path)
    parser.add_argument('--id', action='append', default=[], help='Package one Mod ID (repeatable)')
    parser.add_argument('--include-framework', action='store_true')
    parser.add_argument('--require-complete', action='store_true', help='Fail if any publishable Mod needs a missing external input')
    parser.add_argument('--validate-only', action='store_true')
    args = parser.parse_args(argv)
    try:
        mods = discover_mods(SOURCE_ROOT)
        available = {mod.id.lower(): mod for mod in mods}
        requested = {name.lower() for name in args.id}
        unknown = requested - available.keys()
        if unknown:
            raise PackageError(f"Unknown Mod ID: {', '.join(sorted(unknown))}")
        selected = [mod for mod in mods if mod.id.lower() in requested] if requested else [mod for mod in mods if mod.publish]
        if not requested and any(not mod.publish for mod in mods):
            print('SKIP unpublished: ' + ', '.join(mod.id for mod in mods if not mod.publish))
        if args.validate_only:
            print(f'VALID {len(mods)} Mod manifests; selected {len(selected)}')
            return 0
        external = {}
        if args.native_settings_asset is not None:
            external['native-settings-asset'] = args.native_settings_asset
        skipped = []
        jobs: list[tuple[Path, dict[str, bytes]]] = []
        for mod in selected:
            missing = [source.split(':', 1)[1] for source, _ in mod.files
                       if source.startswith('external:') and source.split(':', 1)[1] not in external]
            if missing:
                if requested or args.require_complete:
                    raise PackageError(f"{mod.id} needs --native-settings-asset")
                skipped.append(mod.id)
                continue
            jobs.append(prepare_mod(mod, SOURCE_ROOT, args.build_dir, args.output_dir, external))
        if skipped:
            print('SKIP external input missing: ' + ', '.join(skipped))
        if args.include_framework or not requested:
            jobs.append(prepare_framework(SOURCE_ROOT, args.build_dir, args.output_dir))
        for path, _ in jobs:
            if path.exists():
                raise PackageError(f'Archive already exists; choose a fresh output directory: {path}')
        for path, entries in jobs:
            digest = write_archive(path, entries)
            print(f'PACKAGED {path} SHA256={digest}')
        return 0
    except (PackageError, OSError) as error:
        print(f'ERROR: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
