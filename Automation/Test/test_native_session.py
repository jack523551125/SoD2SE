"""Authored filesystem/metadata fixtures; no game process, input, save or MO2 is used."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
path=Path(__file__).resolve().parents[1]/'NativeTest.py'
spec=importlib.util.spec_from_file_location('native_test_session',path)
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

def test_plugin_preflight_refuses_hash_pin_and_undeclared_payload(tmp_path):
    root=tmp_path/'package'
    directory=root/'Plugins'
    directory.mkdir(parents=True)
    binary=directory/'Example.dll'
    binary.write_bytes(b'Authored inert binary fixture')
    manifest={'schema':1,'abi':1,'file':binary.name,'sha256':module.digest(binary),'framework_revision':'a'*40}
    sidecar=directory/'Example.native.json'
    sidecar.write_text(json.dumps(manifest))
    assert len(module.plugin_files(root,'a'*40))==2
    with pytest.raises(ValueError):module.plugin_files(root,'b'*40)
    binary.write_bytes(b'changed')
    with pytest.raises(ValueError):module.plugin_files(root,'a'*40)
    binary.write_bytes(b'Authored inert binary fixture')
    (directory/'Foreign.dll').write_bytes(b'Authored foreign fixture')
    with pytest.raises(ValueError):module.plugin_files(root,'a'*40)

def environment(tmp_path):
    game=tmp_path/'game'
    plugins=game/'Plugins'
    plugins.mkdir(parents=True)
    test=tmp_path/'environment'
    test.mkdir()
    files=[]
    for name in ['Mcm.dll','Mcm.native.json','UnlimitedFollowers.dll','UnlimitedFollowers.native.json']:
        path=plugins/name
        path.write_bytes(b'Authored mode fixture')
        files.append({'name':name,'sha256':module.digest(path)})
    receipt={'schema':1,'stage':'ready','game_root':str(game),'profile':'fixture','plugins':files}
    module.store(test/'test-session.json',receipt)
    return game,test

def test_modes_are_reversible_and_do_not_start_any_process(tmp_path,monkeypatch):
    game,test=environment(tmp_path)
    monkeypatch.setattr(module,'stopped',lambda:None)
    for mode in ['without-mcm','with-mcm','mo2','with-mcm']:
        module.mode(SimpleNamespace(environment=test,mode=mode))
        assert (game/'Plugins/Mcm.dll').exists()==(mode=='with-mcm')
        assert (game/'Plugins/UnlimitedFollowers.dll').exists()==(mode!='mo2')

def test_rollback_refuses_foreign_files_before_mutations(tmp_path,monkeypatch):
    game,test=environment(tmp_path)
    monkeypatch.setattr(module,'stopped',lambda:None)
    commands=[]
    monkeypatch.setattr(module,'command',lambda *args:commands.append(args))
    target=game/'Plugins/Mcm.dll'
    target.write_bytes(b'Foreign replacement must survive')
    with pytest.raises(ValueError):module.rollback(SimpleNamespace(environment=test))
    assert commands==[]
    assert target.read_bytes()==b'Foreign replacement must survive'
