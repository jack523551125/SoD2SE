"""License/source inventory from locked local Cargo inputs; no protected game inputs."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tomllib

def write(product:Path,destination:Path):
    destination.mkdir(parents=True,exist_ok=True)
    metadata=json.loads(subprocess.check_output(['cargo','metadata','--locked','--offline','--format-version','1','--manifest-path',str(product/'Cargo.toml')],text=True,cwd=product))
    lock=tomllib.loads((product/'Cargo.lock').read_text(encoding='utf-8'))
    checksums={(p['name'],p['version']):p.get('checksum') for p in lock['package']}
    entries=[]
    for package in sorted(metadata['packages'],key=lambda p:(p['name'],p['version'])):
        entry={'name':package['name'],'version':package['version'],'source':package.get('source') or 'owner-authored path dependency',
            'checksum':checksums.get((package['name'],package['version'])),'license':package.get('license'),'license_files':[]}
        if package.get('source'):
            root=Path(package['manifest_path']).parent
            names={p for pattern in ['LICENSE*','NOTICE*','COPYING*'] for p in root.glob(pattern) if p.is_file()}
            if package.get('license_file'):names.add(root/package['license_file'])
            for source in sorted(names):
                output=destination/f"{package['name']}-{package['version']}"/source.name
                output.parent.mkdir(exist_ok=True)
                shutil.copyfile(source,output)
                entry['license_files'].append({'path':output.relative_to(destination).as_posix(),'sha256':hashlib.sha256(output.read_bytes()).hexdigest()})
            if not entry['license_files'] or not entry['license']:
                raise ValueError(f"Dependency license evidence is missing: {package['name']}")
        entries.append(entry)
    (destination/'third-party.json').write_text(json.dumps({'schema':1,'packages':entries,
        'authored_license':'No redistribution license grant is declared by the private authored source repositories.',
        'scope':'Locked dependency source/license evidence; build dependencies may be included.'},indent=2)+'\n',encoding='utf-8')

def bundle(evidence: Path, destination: Path, additional=()):
    """Consolidate complete notices, deduplicating identical texts with explicit attribution."""
    inventory = json.loads((evidence/'third-party.json').read_text(encoding='utf-8'))
    texts = {}
    for package in inventory['packages']:
        for item in package['license_files']:
            source = evidence/item['path']
            if hashlib.sha256(source.read_bytes()).hexdigest() != item['sha256']:
                raise ValueError(f'License evidence hash mismatch: {source.name}')
            text = source.read_text(encoding='utf-8-sig').replace('\r\n', '\n')
            label = f"{package['name']} {package['version']} / {source.name} / {package['source']}"
            texts.setdefault(text, []).append(label)
    for label, source in additional:
        text = Path(source).read_text(encoding='utf-8-sig').replace('\r\n', '\n')
        texts.setdefault(text, []).append(label)
    if not texts:
        raise ValueError('No third-party license evidence found')
    destination.parent.mkdir(parents=True, exist_ok=True)
    parts = ['Third-party notices supplied with this distribution.\nNo in-game acknowledgment is required.\n']
    for text, labels in texts.items():
        parts.append('\n'+'='*78+'\nApplies to:\n'+'\n'.join(labels)+'\n\n'+text+'\n')
    destination.write_text(''.join(parts), encoding='utf-8')
