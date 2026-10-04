"""Build fresh native candidate/release packages from Cargo outputs; never deploy or launch."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import tomllib
import zipfile

REQUIRED = ['save-compat', 'safe-uninstall', 'update-compat', 'original-file-integrity', 'fail-closed', 'api-docs', 'diagnostics', 'git-provenance', 'shared-gameapi', 'gameapi-only', 'rust-abi', 'input-support', 'live-tools', 'translations', 'mcm-optional', 'mcm-adapter', 'risk-markers', 'settings-authority']

def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()

def release_gate(report, revision, version):
    if report.get('schema') != 1 or report.get('reviewed') is not True or report.get('revision') != revision or report.get('version') != version:
        raise ValueError('Release acceptance must be reviewed and match this exact source revision/version')
    checks = report.get('checks', {})
    missing = [key for key in REQUIRED if checks.get(key, {}).get('status') != 'PASS' or not checks[key].get('evidence')]
    if missing:
        raise ValueError('Release refused; missing acceptance: ' + ', '.join(missing))

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--product-root', type=Path, required=True)
    parser.add_argument('--build-root', type=Path, required=True)
    parser.add_argument('--native-settings-asset', type=Path)
    parser.add_argument('--native-ui-receipt', type=Path)
    parser.add_argument('--acceptance', type=Path)
    parser.add_argument('--candidate', action='store_true')
    args = parser.parse_args(argv)
    product = args.product_root.resolve()
    cargo = tomllib.loads((product / 'Cargo.toml').read_text(encoding='utf-8'))
    framework = 'workspace' in cargo
    version = cargo['workspace']['package']['version'] if framework else cargo['package']['version']
    revision = subprocess.check_output(['git','-C',str(product),'rev-parse','HEAD'], text=True).strip()
    if not args.candidate:
        if not args.acceptance:
            raise ValueError('Release refused: reviewed live acceptance report required; use --candidate for offline artifacts')
        release_gate(json.loads(args.acceptance.read_text(encoding='utf-8')), revision, version)
        if subprocess.check_output(['git','-C',str(product),'status','--porcelain'],text=True).strip():
            raise ValueError('Release refused: source checkout is dirty')
    output = args.build_root.resolve() / 'packages'
    output.mkdir(parents=True, exist_ok=True)
    name = 'SoD2SE' if framework else product.name
    archive = output / f'{name}-v{version}{"-candidate" if args.candidate else ""}.zip'
    if archive.exists():
        raise FileExistsError(f'Existing package is preserved: {archive}')
    with tempfile.TemporaryDirectory(prefix='package-', dir=output) as temporary:
        stage = Path(temporary)
        root = stage / 'Root'
        root.mkdir()
        def copy(source, target):
            target = root / target
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
        build = args.build_root / 'release'
        if framework:
            for source, target in [('sod2se-loader.exe','SoD2SE.Loader.exe'),('sod2se_runtime.dll','SoD2SE.Runtime.dll'),('sod2se-devtools.exe','SoD2SE.DevTools.exe')]:
                copy(build / source, target)
            copy(product / 'Docs/RUST-API.md', 'SoD2SE/Docs/API.md')
            copy(product / 'Rust/abi/include/sod2se.h', 'SoD2SE/SDK/sod2se.h')
            copy(product / 'Rust/locales/template.json', 'SoD2SE/Localization/template.json')
            copy(product / 'Native/vendor/minhook/LICENSE.txt', 'SoD2SE/Licenses/MinHook.txt')
            shutil.copyfile(product / 'Automation/Install-Rust.ps1', stage / 'Install.ps1')
            ui_status = 'SKIPPED'
            if args.native_settings_asset and args.native_ui_receipt:
                receipt = json.loads(args.native_ui_receipt.read_text(encoding='utf-8'))
                target = json.loads((product / 'patch-manifest.json').read_text(encoding='utf-8'))
                if receipt.get('schema') != 1 or receipt.get('reviewed') is not True or receipt.get('game_sha256') != target['sha256'].lower() or receipt.get('sha256') != digest(args.native_settings_asset):
                    raise ValueError('Native UI resource receipt/hash/target mismatch')
                copy(args.native_settings_asset, 'SoD2SE/Assets/settings.uasset')
                copy(args.native_ui_receipt, 'SoD2SE/Assets/native-ui.json')
                ui_status = 'PACKAGED_NOT_LIVE_VERIFIED'
            elif not args.candidate:
                raise ValueError('SKIPPED: reviewed fixed-build native UI resource and receipt are required')
            info = {'schema':1, 'native_abi':1, 'version':version, 'revision':revision, 'publish':not args.candidate, 'native_ui':ui_status, 'live_acceptance':'NOT_RUN' if args.candidate else 'REVIEWED'}
            (root / 'SoD2SE/build-info.json').parent.mkdir(parents=True, exist_ok=True)
            (root / 'SoD2SE/build-info.json').write_text(json.dumps(info,indent=2)+'\n',encoding='utf-8')
            entries = [{'path':p.relative_to(root).as_posix(),'sha256':digest(p)} for p in sorted(root.rglob('*')) if p.is_file()]
            (root / 'framework.manifest.json').write_text(json.dumps({'schema':1,'version':version,'files':entries},indent=2)+'\n',encoding='utf-8')
        else:
            mapping = {'MCM':('Mcm','mcm',['sod2.ui.native-settings'],['settings.frontend']), 'UnlimitedFollowers':('UnlimitedFollowers','unlimited-followers',['sod2.followers.quantity'],[])}
            binary, plugin_id, capabilities, permissions = mapping[product.name]
            copy(build / f'{binary}.dll', f'Plugins/{binary}.dll')
            manifest = {'schema':1,'abi':1,'id':plugin_id,'version':version,'file':f'{binary}.dll','sha256':digest(build/f'{binary}.dll'),'capabilities':capabilities,'permissions':permissions,'publish':not args.candidate,'framework_revision':json.loads((product/'rust-dependencies.lock.json').read_text(encoding='utf-8'))['SoD2SE']['revision']}
            (root / f'Plugins/{binary}.native.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
            (stage / 'meta.ini').write_text(f'[General]\nname={product.name}\nversion={version}\n',encoding='utf-8')
        (stage / 'README.txt').write_text('SoD2SE native ABI 1.\n'+('DEVELOPMENT CANDIDATE: live/save/controller acceptance is NOT_RUN.\n' if args.candidate else 'Reviewed native release.\n')+'Install the SoD2SE prerequisite once. Install MCM and UnlimitedFollowers separately. Legacy managed plugins require the legacy framework.\n',encoding='utf-8')
        # Exclusive creation prevents any historical/candidate archive being overwritten.
        with zipfile.ZipFile(archive,'x',compression=zipfile.ZIP_DEFLATED) as zipped:
            for path in sorted(stage.rglob('*')):
                if path.is_file(): zipped.write(path,path.relative_to(stage).as_posix())
    print(f'CREATED: {archive}; SHA256={digest(archive)}')
    return 0

if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        print(f'ERROR: {error}')
        raise SystemExit(1)
