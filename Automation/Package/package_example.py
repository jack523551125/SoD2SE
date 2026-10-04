"""Generate an explicitly optional, non-gameplay developer fixture package."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tomllib

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--framework',type=Path,required=True)
    parser.add_argument('--binary',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=False)
    destination=args.output/'Plugins'
    destination.mkdir()
    binary=destination/'SoD2SE.Example.dll'
    shutil.copyfile(args.binary,binary)
    revision=subprocess.check_output(['git','-C',str(args.framework),'rev-parse','HEAD'],text=True).strip()
    version=tomllib.loads((args.framework/'Cargo.toml').read_text(encoding='utf-8'))['workspace']['package']['version']
    manifest={'schema':1,'abi':1,'id':'example','version':version,'file':binary.name,
        'sha256':hashlib.sha256(binary.read_bytes()).hexdigest(),'capabilities':[],'permissions':[],
        'publish':False,'framework_revision':revision}
    (destination/'SoD2SE.Example.native.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    print('CREATED optional developer fixture:',args.output)

if __name__=='__main__':main()
