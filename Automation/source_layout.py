"""Resolve historical provenance paths without rewriting research evidence."""
import json
from pathlib import Path

_MAPPING = json.loads(Path(__file__).with_name('source-layout.json').read_text(encoding='utf-8'))

def resolve(relative):
    original = relative
    relative = relative.replace('\\', '/')
    if relative in _MAPPING:
        return _MAPPING[relative]
    for old, new in _MAPPING.items():
        if relative.startswith(old + '/'):
            return new + relative[len(old):]
    return original

def work_root(source_root):
    source_root = Path(source_root).resolve()
    workspace = source_root.parent.parent
    return workspace / '.work/SoD2SE' if (workspace / 'workspace.toml').is_file() else source_root / '.work'

def source_file(base, relative):
    relative = resolve(relative)
    base = Path(base)
    for candidate in (base / relative, base / 'source' / relative):
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f'No source file for {relative} in {base} or its source directory')

def project_root():
    return Path(__file__).resolve().parents[1]

def research_root():
    return project_root() / 'Research'

def workspace_root():
    project = project_root()
    candidate = project.parent.parent
    return candidate if (candidate / 'workspace.toml').is_file() else None
