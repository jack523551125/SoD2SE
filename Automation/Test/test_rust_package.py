"""Release gate negative fixtures contain authored metadata, never fixed game inputs."""
import importlib.util
from pathlib import Path
import pytest
path = Path(__file__).resolve().parents[1] / 'Package/package_rust.py'
spec = importlib.util.spec_from_file_location('native_package', path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

def test_unreviewed_and_missing_evidence_refused():
    with pytest.raises(ValueError, match='reviewed'):
        module.release_gate({'schema':1,'reviewed':False},'revision','version')
    with pytest.raises(ValueError, match='missing acceptance'):
        module.release_gate({'schema':1,'reviewed':True,'revision':'revision','version':'version','checks':{}},'revision','version')

def test_skipped_is_not_pass_and_wrong_revision_refused():
    checks = {key:{'status':'PASS','evidence':'authored fixture'} for key in module.REQUIRED}
    checks['input-support']['status'] = 'SKIPPED'
    report = {'schema':1,'reviewed':True,'revision':'revision','version':'version','checks':checks}
    with pytest.raises(ValueError, match='input-support'):
        module.release_gate(report,'revision','version')
    with pytest.raises(ValueError, match='exact source'):
        module.release_gate(report,'other-revision','version')
