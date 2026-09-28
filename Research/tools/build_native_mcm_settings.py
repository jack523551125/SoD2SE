"""Reproducible native MCM asset patch. Never reads a running game."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from analyze_iggy_script_api import make_swf_wrapper, _run_ffdec_export
from build_native_mod_settings_entry import abc_from_iggy, abc_from_swf, replace_settings_abc, PINNED_SETTINGS_SHA256
from patch_native_entry_bytecode import u30
from patch_native_mcm_bytecode import patch_xml, verify


def build(iggy, ffdec, output):
    source=iggy.read_bytes()
    if hashlib.sha256(source).hexdigest()!=PINNED_SETTINGS_SHA256:raise ValueError('Pinned original required')
    output.mkdir(parents=True,exist_ok=False)
    original=abc_from_iggy(source)
    with tempfile.TemporaryDirectory(prefix='sod2-native-mcm-') as td:
        root=Path(td); swf=root/'original.swf'; swf.write_bytes(make_swf_wrapper(original))
        def run(*args):
            r=subprocess.run([str(ffdec),*map(str,args)],capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=180)
            if r.returncode or 'SEVERE:' in r.stderr:raise ValueError(r.stdout+r.stderr)
        run('-swf2xml',swf,root/'original.xml')
        run('-xml2swf',root/'original.xml',root/'noop.swf')
        if abc_from_swf((root/'noop.swf').read_bytes())!=original:raise ValueError('No-op ABC changed')
        run('-selectclass','settings','-format','script:pcodehex','-export','script',root/'pcode',swf)
        tree=ET.parse(root/'original.xml'); before=copy.deepcopy(tree.find('.//abc'))
        facts=patch_xml(tree,(root/'pcode/scripts/settings.pcode').read_text(encoding='utf-8'))
        category_body=next(b for b in tree.find('.//abc/bodies') if b.get('method_info')=='1343')
        category_code=bytes.fromhex(category_body.get('codeBytes'))
        if b'\x62\x03\x25\x01\x13' not in category_code or b'\x62\x03\x25\x02\x13' not in category_code:
            raise ValueError('Mod category language branches do not compare for equality')
        settings_body=next(b for b in tree.find('.//abc/bodies') if b.get('method_info')=='1365')
        settings_code=bytes.fromhex(settings_body.get('codeBytes'))
        if bytes.fromhex('d0 30 57 2a d6 30') not in settings_code[:32]:
            raise ValueError('Mod category runs before the original method scope prologue')
        language_rpc=bytes.fromhex('25 0e 62 04 25 00 25 00 46 ea 0f 05')
        if language_rpc not in settings_code:
            raise ValueError('Settings page does not query the read-only detected language')
        if b'SoD2SE_ModSettings_Back' in settings_code:
            raise ValueError('Redundant Mod Settings Back row survived')
        tree.write(root/'patched.xml',encoding='utf-8',xml_declaration=True)
        run('-xml2swf',root/'patched.xml',root/'patched.swf')
        run('-swf2xml',root/'patched.swf',root/'verified.xml')
        verify(before,ET.parse(root/'verified.xml').find('.//abc'),set(facts['patched_methods']))
        run('-selectclass','settings','-export','script',root/'decompiled',root/'patched.swf')
        script=(root/'decompiled/scripts/settings.as').read_text(encoding='utf-8')
        for token in [
            'SoD2SE_Mcm_v1','__sod2se_revision','new Vector.<dropdown_option>()',
            'this.AddToggleSetting','this.AddSliderSettingWithValue',
            'this.AddDropdownSetting','_loc13_.txt_value.value.text','_loc14_.type = "input"',
            '_loc14_.maxChars = 11','_loc14_.background = true',
            '_loc14_.border = true','_loc14_.backgroundColor =',
            '_loc14_.borderColor =','_loc14_.textColor =','_loc14_.width = 72','Number(_loc5_.text)',
            'ExternalInterface.call("SoD2SE_Mcm_v1",14,','ExternalInterface.call("SoD2SE_Mcm_v1",15,',
            'UI_Settings_SetHints",205', '✓ 已加载', '✓ Loaded',
            '.container_slider.visible = false', '.Enable(false,false)',
            'param1.Settings.pop()',
        ]:
            if token not in script:raise ValueError('Missing re-decoded binding: '+token)
        if '__sod2se_language' in script or '菜单语言 / Language' in script:
            raise ValueError('Manual MCM language setting survived the patch')
        if 'SoD2SE_ModSettings_Back' in script:
            raise ValueError('Redundant Mod Settings Back row survived')
        if '正在保存' in script or 'Saving...' in script or '设置已同步。' in script:
            raise ValueError('Visible save status survived the compact layout')
        abc=abc_from_swf((root/'patched.swf').read_bytes())
        movie=replace_settings_abc(source,abc)
        if abc_from_iggy(movie)!=abc:raise ValueError('Iggy writeback drift')
        # Persist local developer test fixtures separately from all distributable packages.
        for name in ['original.xml','patched.xml','verified.xml']:(output/name).write_bytes((root/name).read_bytes())
        (output/'settings.as').write_text(script,encoding='utf-8')
        (output/'settings-mcm.iggy').write_bytes(movie)
    report=dict(target_build=16535856,version='0.3.1-preview',language='runtime-detected-from-game',**facts,
        empty_page_load_status=True,slider_value_native_directional_hints=205,
        xml_noop_identical=True,non_target_movie_bytes_preserved=True,roundtrip_identity_check=True,
        input_control_static_verified=True,integer_input_conversion_static_verified=True,
        save_callback_static_verified=True,native_operations={'detected_language':14,'set_option':15,'status':17},
        input_sha256=hashlib.sha256(source).hexdigest(),output_sha256=hashlib.sha256(movie).hexdigest(),
        original_abc_size=len(original),modified_abc_size=len(abc),static_only=True)
    (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return report


if __name__=='__main__':
    a=argparse.ArgumentParser(description=__doc__)
    a.add_argument('--iggy',required=True,type=Path);a.add_argument('--ffdec',required=True,type=Path)
    a.add_argument('--output',required=True,type=Path)
    args=a.parse_args();print(json.dumps(build(args.iggy,args.ffdec,args.output),indent=2))
