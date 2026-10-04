"""Resolve historical provenance paths without rewriting research evidence."""
import json
import os
from pathlib import Path

_MAPPING = json.loads(Path(__file__).with_name('source-layout.json').read_text(encoding='utf-8'))
# Keep the historical provenance labels while resolving relocated compatibility owners.
for old, target in _MAPPING.items():
    for name in ('MCM', 'SoD2SE-Loader', 'NativeModSettingsEntry'):
        target = target.replace('../../Projects/'+name+'/', '../../Compatibility/'+name+'/')
    _MAPPING[old] = target

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
    base = Path(base).resolve()
    workspace = workspace_root()
    allowed_roots = [base]
    if workspace is not None:
        allowed_roots.append(workspace.resolve())
    for candidate in (base / relative, base / 'source' / relative):
        candidate = candidate.resolve()
        if not any(candidate == root or root in candidate.parents for root in allowed_roots):
            continue
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f'No source file for {relative} within {base}' + (f' or {workspace}' if workspace else ''))

def project_root():
    return Path(__file__).resolve().parents[1]

def workspace_root():
    override = os.environ.get('SOD2_WORKSPACE_ROOT')
    if override:
        candidate = Path(override).resolve()
        if (candidate / 'workspace.toml').is_file():
            return candidate
    project = project_root()
    candidate = project.parent.parent
    return candidate if (candidate / 'workspace.toml').is_file() else None

def research_root():
    override = os.environ.get('SOD2_RESEARCH_ROOT')
    if override:
        return Path(override).resolve()
    workspace = workspace_root()
    if workspace is not None:
        candidate = workspace / 'ReverseEngineering'
        if candidate.is_dir():
            return candidate
    return project_root() / 'Research'
