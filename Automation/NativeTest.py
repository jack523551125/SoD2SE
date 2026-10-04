"""Explicit local test preparation/rollback. Never called by offline checks.

Protected save backups and derived resources stay in the supplied local environment.
prepare does not start a game, change MO2's active profile, or rewrite saves.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import tempfile

def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()

def no_links(path):
    for entry in [path, *path.parents]:
        if entry.exists():
            info = entry.lstat()
            if entry.is_symlink() or getattr(info, 'st_file_attributes', 0) & 0x400:
                raise ValueError(f'Reparse/symlink path refused: {entry}')

def store(path, document):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=path.parent,delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(document, stream, indent=2, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary and temporary.exists():temporary.unlink()

def command(tool, *arguments):
    subprocess.run([str(tool), *map(str, arguments)], check=True)

def stopped():
    # Ask the Rust install gate to inspect processes before deployment operations.
    # Mode changes use PowerShell process enumeration with an exact name allowlist.
    script = "if (Get-Process -Name 'StateOfDecay2','StateOfDecay2-Win64-Shipping','SoD2SE.Loader' -ErrorAction SilentlyContinue) { exit 1 }"
    if subprocess.run(['pwsh', '-NoProfile', '-Command', script]).returncode:
        raise ValueError('Exit the game and loader first')

def paths(environment):
    environment = environment.absolute()
    no_links(environment)
    receipt_path = environment / 'test-session.json'
    receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
    game = Path(receipt['game_root'])
    no_links(game)
    if receipt.get('schema') != 1 or not game.is_dir():
        raise ValueError('Invalid test receipt')
    return receipt_path, receipt, game, environment / 'Package/Root/SoD2SE.DevTools.exe'

def plugin_files(root, framework_revision):
    directory = root / 'Plugins'
    files = []
    for path in sorted(directory.glob('*.native.json')):
        manifest = json.loads(path.read_text(encoding='utf-8'))
        name = manifest['file']
        if manifest.get('abi') != 1 or manifest.get('schema') != 1 or manifest.get('framework_revision') != framework_revision:
            raise ValueError('Plugin ABI/framework revision mismatch')
        if Path(name).name != name or not name.lower().endswith('.dll'):
            raise ValueError('Invalid plugin file')
        binary = directory / name
        if manifest.get('sha256') != digest(binary):
            raise ValueError('Plugin hash mismatch')
        files.extend([(path, path.name), (binary, name)])
    if not files or {p.name for p in directory.iterdir() if p.is_file()} != {n for _, n in files}:
        raise ValueError('Undeclared plugin payload or empty package')
    return files

def prepare(args):
    stopped()
    game, environment, saved = args.game_root.absolute(), args.environment.absolute(), args.save_root.absolute()
    for path in [game, environment, saved, args.framework_root.absolute()]:
        no_links(path)
    if environment.exists() or environment.is_relative_to(game) or environment.is_relative_to(saved):
        raise ValueError('A fresh test environment outside game/save directories is required')
    image = game / 'StateOfDecay2/Binaries/Win64/StateOfDecay2-Win64-Shipping.exe'
    tool = args.framework_root / 'SoD2SE.DevTools.exe'
    command(tool, 'doctor', image, '--native-ui')
    command(tool, 'verify-package', args.framework_root)
    # Framework installation cannot take over unmanaged plugins.
    if (game / 'Plugins').exists() and any((game / 'Plugins').rglob('*.dll')):
        raise ValueError('Existing game-root plugins require a separate reviewed migration')
    info = json.loads((args.framework_root / 'SoD2SE/build-info.json').read_text(encoding='utf-8'))
    payloads = []
    for root in [args.mcm_root, args.followers_root, *([args.example_root] if args.example_root else [])]:
        payloads.extend(plugin_files(root, info['revision']))
    if len({name.casefold() for _, name in payloads}) != len(payloads):
        raise ValueError('Plugin packages collide')
    for _, name in payloads:
        target = game / 'Plugins' / name
        no_links(target)
        if target.exists():
            raise ValueError(f'Foreign target exists: {target}')
    legacy = [game / n for n in ['SoD2SE.Loader.exe','SoD2SE.Core.dll','SoD2SE.GameApi.dll'] if (game / n).exists()]
    if legacy and not args.legacy_review:
        raise ValueError('Existing legacy framework requires a reviewed hash inventory')
    environment.mkdir(parents=True)
    shutil.copytree(args.framework_root, environment / 'Package/Root')
    tool = environment / 'Package/Root/SoD2SE.DevTools.exe'
    backups = []
    for name in ['Steam', 'SaveGames', 'Release', 'Config']:
        source = saved / name
        if source.exists():
            for path in source.rglob('*'):
                no_links(path)
            destination = environment / 'SaveBackup' / name
            shutil.copytree(source, destination)
            for path in source.rglob('*'):
                if path.is_file():
                    relative = path.relative_to(saved)
                    if digest(path) != digest(environment / 'SaveBackup' / relative):
                        raise ValueError('Save backup verification failed')
                    backups.append({'path': relative.as_posix(), 'sha256': digest(path)})
    if not any(v['path'].lower().endswith('.sav') for v in backups):
        raise ValueError('No save files found; preparation stopped before installation')
    staged = environment / 'Plugins'
    staged.mkdir()
    for source, name in payloads:
        shutil.copyfile(source, staged / name)
        if digest(source) != digest(staged / name):
            raise ValueError('Staging verification failed')
    receipt = {'schema':1, 'game_root':str(game), 'save_root':str(saved), 'profile':'rust-acceptance',
        'framework_revision':info['revision'], 'stage':'prepared', 'legacy_archived':False,
        'save_backup':backups, 'plugins':[{'name':name,'sha256':digest(staged/name)} for _,name in payloads],
        'input_device':'Xbox controller via Bluetooth', 'live_acceptance':'NOT_RUN'}
    destination = environment / 'test-session.json'
    store(destination, receipt)
    if legacy:
        shutil.copyfile(args.legacy_review, environment / 'legacy-review.json')
        command(tool, 'archive-legacy', game, environment / 'legacy-review.json')
        receipt['legacy_archived'] = True
        store(destination, receipt)
    command(tool, 'install', environment / 'Package/Root', game)
    receipt['stage'] = 'installing-plugins'
    store(destination, receipt)
    (game / 'Plugins').mkdir(exist_ok=True)
    for entry in receipt['plugins']:
        target = game / 'Plugins' / entry['name']
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=target.parent,delete=False,suffix='.tmp') as dst, (staged / entry['name']).open('rb') as src:
                temporary=Path(dst.name)
                shutil.copyfileobj(src,dst)
                dst.flush()
                os.fsync(dst.fileno())
            if digest(temporary)!=entry['sha256']:raise ValueError('Plugin staging hash mismatch')
            os.link(temporary,target)
        finally:
            if temporary and temporary.exists():temporary.unlink()
        if digest(target) != entry['sha256']:
            raise ValueError('Plugin installation verification failed; use rollback')
    receipt['stage'] = 'ready'
    store(destination, receipt)
    command(tool, 'verify-package', game)
    command(tool, 'verify-plugins', game)
    print('READY. Game has not been started. Environment:', environment)

def verify_plugins(receipt, game, environment):
    for entry in receipt['plugins']:
        name = entry['name']
        if Path(name).name != name or not name.lower().endswith(('.dll','.native.json')):
            raise ValueError('Invalid receipt plugin path')
        target = game / 'Plugins' / name
        disabled = environment / 'Disabled' / name
        for path in [target, disabled]:
            no_links(path)
            if path.exists() and digest(path) != entry['sha256']:
                raise ValueError('Modified plugin preserved; operation refused')
        if target.exists() and disabled.exists():
            raise ValueError('Ambiguous plugin ownership')

def mode(args):
    stopped()
    path, receipt, game, _ = paths(args.environment)
    if receipt['stage'] != 'ready':
        raise ValueError('Session is not ready')
    verify_plugins(receipt, game, args.environment)
    (args.environment / 'Disabled').mkdir(exist_ok=True)
    for entry in receipt['plugins']:
        name = entry['name']
        active, disabled = game / 'Plugins' / name, args.environment / 'Disabled' / name
        disable = args.mode=='mo2' or (args.mode=='without-mcm' and name.lower() in ['mcm.dll','mcm.native.json'])
        source, destination = (active, disabled) if disable else (disabled, active)
        if source.exists():
            if destination.exists():
                raise ValueError('Mode destination exists')
            os.rename(source,destination)
    receipt['mode'] = args.mode
    store(path,receipt)
    print('Mode:',args.mode,'; restart the game to apply')

def rollback(args):
    stopped()
    path, receipt, game, tool = paths(args.environment)
    verify_plugins(receipt, game, args.environment)
    command(tool,'recover-overlay',receipt['profile'])
    if (game / 'SoD2SE/install.pending.json').exists():
        command(tool,'recover-install',game)
    if (game / 'SoD2SE/install.json').exists():
        command(tool,'uninstall',game)
    for entry in receipt['plugins']:
        target=game/'Plugins'/entry['name']
        if target.exists():
            if digest(target)!=entry['sha256']:
                raise ValueError('Modified plugin preserved')
            target.unlink()
    if (game/'SoD2SE/legacy-transition.json').exists():
        command(tool,'restore-legacy',game)
    receipt['stage']='rolled-back'
    store(path,receipt)
    print('Legacy framework restored. Saves and their verified backup were retained.')

def report(args):
    _,receipt,_,tool=paths(args.environment)
    folder=args.environment/'Reports'
    folder.mkdir(exist_ok=True)
    session=Path(os.environ['LOCALAPPDATA'])/'StateOfDecay2/SoD2SE/Rust'/receipt['profile']/'session.json'
    destination=folder/f'diagnostics-{time.time_ns()}.json'
    command(tool,'report',session,destination)
    print('Report:',destination)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest='command',required=True)
    prepare_parser=commands.add_parser('prepare')
    for name in ['game-root','environment','save-root','framework-root','mcm-root','followers-root']:
        prepare_parser.add_argument('--'+name,type=Path,required=True)
    prepare_parser.add_argument('--example-root',type=Path)
    prepare_parser.add_argument('--legacy-review',type=Path)
    for name in ['mode','rollback','report']:
        sub=commands.add_parser(name)
        sub.add_argument('--environment',type=Path,required=True)
        if name=='mode':sub.add_argument('--mode',choices=['with-mcm','without-mcm','mo2'],required=True)
    args=parser.parse_args()
    globals()[args.command](args)

if __name__=='__main__':
    try: main()
    except (OSError,ValueError,KeyError,subprocess.CalledProcessError) as error:
        raise SystemExit(f'TEST_PREPARATION_REFUSED: {error}; preserve the environment and use rollback after resolving conflicts')
