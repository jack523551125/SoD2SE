"""Generate the legacy baseline and provenance without protected inputs or live operations."""
from __future__ import annotations
import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

PRODUCT = Path(__file__).resolve().parents[2]
WORKSPACE = PRODUCT.parents[1]
REPOS = ['SoD2SE', 'SoD2SE-Loader', 'NativeModSettingsEntry', 'MCM', 'UnlimitedFollowers', 'MO2-Support']

def git(repo, *args):
    return subprocess.run(['git', '-C', str(repo), *args], check=True, capture_output=True, text=True, encoding='utf-8').stdout.strip()

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-checks', action='store_true')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = {'schema': 1, 'captured_utc': datetime.now(timezone.utc).isoformat(), 'repositories': {}, 'comparison': {}, 'checks': []}
    for name in REPOS:
        repo = WORKSPACE / ('Compatibility' if name in ('SoD2SE-Loader','NativeModSettingsEntry','MCM') else 'Projects') / name
        report['repositories'][name] = {'head': git(repo, 'rev-parse', 'HEAD'), 'branch': git(repo, 'branch', '--show-current'), 'status': git(repo, 'status', '--porcelain=v1'), 'remotes': git(repo, 'remote', '-v')}
    # Source only: do not traverse builds, game installs, research inputs or vendor.
    for directory in ['Core', 'GameApi', 'Loader']:
        left = PRODUCT / directory
        right = WORKSPACE / 'Compatibility/SoD2SE-Loader' / directory
        for root, label in [(left,'framework'),(right,'loader')]:
            report['comparison'][label+'.'+directory] = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.rglob('*.cs'))}
    if args.run_checks:
        log_root = WORKSPACE / '.work/migration/sod2se-rust/baseline'
        log_root.mkdir(parents=True, exist_ok=True)
        commands = [('check','workspace')] + [(action,name) for name in REPOS for action in ['build','check','test']]
        for action, name in commands:
            command = ['pwsh','-NoProfile','-File',str(WORKSPACE/'Automation/dev.ps1'),action,name]
            result = subprocess.run(command, cwd=WORKSPACE, capture_output=True, text=True, encoding='utf-8', errors='replace')
            output = result.stdout + result.stderr
            log = log_root / f'{name}-{action}.log'
            log.write_text(output, encoding='utf-8')
            status = 'FAIL' if result.returncode else 'SKIPPED' if 'SKIPPED:' in output else 'PASS'
            report['checks'].append({'product':name,'action':action,'status':status,'exit':result.returncode,'log':log.relative_to(WORKSPACE).as_posix(),'log_sha256':hashlib.sha256(log.read_bytes()).hexdigest()})
            print(f'{status}: {action} {name}', flush=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

if __name__ == '__main__': main()
