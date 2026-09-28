"""Append-only constants and bounded method prefixes for native MCM, build 16535856.

No ActionScript source recompilation: all original traits, method signatures,
namespaces, class indices and non-target method bodies remain identical.
"""
import copy
import xml.etree.ElementTree as ET
from patch_native_entry_bytecode import patch_xml as entry_patch, u30


class Code:
    def __init__(self):
        self.data = bytearray(); self.labels = {}; self.fixups = []
    def op(self, op, *args):
        self.data.append(op)
        for a in args: self.data.extend(u30(a))
        return self
    def raw(self, data): self.data.extend(data); return self
    def label(self, name):
        if name in self.labels: raise ValueError('Duplicate label')
        self.labels[name] = len(self.data); return self
    def jump(self, op, name):
        self.data.append(op); self.fixups.append((len(self.data), name)); self.data.extend(b'\0'*3); return self
    def done(self):
        result = bytearray(self.data)
        for offset, name in self.fixups:
            if name not in self.labels:
                raise ValueError('Unknown branch label: ' + name)
            displacement = self.labels[name] - (offset + 3)
            if displacement < -(1 << 23) or displacement >= (1 << 23):
                raise ValueError('AVM2 branch target is out of range: ' + name)
            result[offset:offset+3] = displacement.to_bytes(3,'little',signed=True)
        return bytes(result)
    def local(self, i): return self.op(0x62, i)
    def save(self, i): return self.op(0x63, i)
    def integer(self, i): return self.op(0x25, i)  # nonnegative pushshort


class Patch:
    def __init__(self, tree):
        self.abc = tree.find('.//abc'); self.c = self.abc.find('constants')
        self.strings = self.c.find('constant_string'); self.names = self.c.find('constant_multiname')
        self.bodies = {int(b.get('method_info')): b for b in self.abc.find('bodies')}
        self.traits = {int(t.get('name_index')):int(t.get('method_info')) for t in
            list(self.abc.find('instance_info'))[174].findall('instance_traits/traits/item') if t.get('method_info')}
        self.changed = {1343,1348,1365}
        self.localized_label = 0
        # Public runtime-key namespace: never resolve Mod keys in private namespaces.
        sets = self.c.find('constant_namespace_set')
        s = ET.SubElement(sets,'item', {'type':'NamespaceSet'})
        ns = ET.SubElement(s,'namespaces'); ET.SubElement(ns,'item').text='1'
        self.dynamic = len(self.names)
        ET.SubElement(self.names,'item',dict(type='Multiname',kind='27',name_index='0',namespace_index='0',namespace_set_index=str(len(sets)-1),qname_index='0'))
    def string(self, text):
        for i,v in enumerate(self.strings):
            if v.text == text: return i
        i=len(self.strings); ET.SubElement(self.strings,'item').text=text; return i
    def name(self, text):
        s=self.string(text)
        for i,v in enumerate(self.names):
            if v.get('kind')=='7' and v.get('namespace_index')=='1' and v.get('name_index')==str(s): return i
        i=len(self.names); ET.SubElement(self.names,'item',dict(type='Multiname',kind='7',name_index=str(s),namespace_index='1',namespace_set_index='0',qname_index='0')); return i
    def text(self, c, text): c.op(0x2c,self.string(text))
    def prop(self,c,text): c.op(0x66,self.name(text))
    def settings(self,c): c.local(0).op(0x66,1331)
    def key(self,c,prefix,index): self.text(c,prefix); c.local(index).op(0xa0)
    def rpc(self,c,op,token=None,index=None,value=None):
        c.op(0x60,2025); self.text(c,'SoD2SE_Mcm_v1'); c.integer(op)
        c.local(token) if token is not None else c.integer(0)
        c.local(index) if index is not None else c.integer(0)
        c.local(value) if value is not None else c.integer(0)
        c.op(0x46,2026,5)
    def checkpoint(self,c,token,marker):
        c.op(0x60,2025); self.text(c,'SoD2SE_Mcm_v1'); c.integer(18)
        c.local(token); c.integer(marker); c.integer(0)
        c.op(0x46,2026,5).op(0x29)
    def localized(self,c,chinese,english,language_register=15):
        serial=self.localized_label; self.localized_label+=1
        use_english=f'localized_english_{serial}'
        done=f'localized_done_{serial}'
        c.local(language_register).integer(1).jump(0x14,use_english)
        self.text(c,chinese); c.jump(0x10,done)
        c.label(use_english); self.text(c,english); c.label(done)
    def textblock(self,c,chinese,english,language_register=15):
        c.local(0).local(1); self.localized(c,chinese,english,language_register); c.op(0x4f,1292,2)
    def prefix(self,name,code,regs=0,stack=20):
        mid=self.traits[name]; b=self.bodies[mid]
        if len(b.find('exceptions')): raise ValueError('Unexpected existing exception table')
        b.set('codeBytes',(code+bytes.fromhex(b.get('codeBytes'))).hex())
        b.set('max_regs',str(max(regs,int(b.get('max_regs')))))
        b.set('max_stack',str(max(stack,int(b.get('max_stack')))))
        self.changed.add(mid)


def patch_xml(tree, pcode):
    original=copy.deepcopy(tree.find('.//abc'))
    entry_patch(tree,pcode)
    p=Patch(tree)
    # Existing setting_list bindings remain intact; only prefixed Mod keys are dynamic.
    cls=list(p.abc.find('instance_info'))[6]
    if cls.get('name_index')!='34' or cls.get('flags')!='9': raise ValueError('setting_list identity drift')
    cls.set('flags','8')
    # Fresh snapshot whenever entering the Mod category. Other category caches survive.
    c=Code(); c.local(1).integer(0).jump(0x14,'original')
    c.local(0).op(0x66,1346).integer(0).op(0x20).op(0x61,p.dynamic).label('original')
    p.prefix(1281,c.done())

    c=Code(); c.local(1).op(0x66,1377).integer(0).jump(0x14,'original')
    # The original method starts by installing `this` and its activation on
    # the scope stack. Mod-only code returns before the original body, so it
    # needs the same prologue before resolving Vector and dropdown_option.
    c.raw(bytes.fromhex('d0 30 57 2a d6 30'))
    c.integer(2).save(15)  # Safe fallback if the bridge is temporarily unavailable.
    p.rpc(c,0); c.op(0x73).save(4)
    p.rpc(c,14,4); c.op(0x73).save(15)
    c.local(4).integer(0).jump(0x16,'unavailable')
    p.settings(c); c.local(4).op(0x61,p.name('__sod2se_revision'))
    p.rpc(c,2,4); c.op(0x73).save(5)
    p.settings(c); c.local(5).op(0x61,p.name('__sod2se_count'))
    p.rpc(c,1,4); c.op(0x73).save(6); c.integer(0).save(7)
    c.label('page'); c.local(7).local(6).jump(0x18,'finish')
    # Pages without options are runtime status rows, not configurable toggles.
    c.integer(0).save(8); c.integer(0).save(16)
    c.label('findoption'); c.local(8).local(5).jump(0x18,'foundoptions')
    p.rpc(c,6,4,8); c.local(7).jump(0x14,'findnext')
    c.integer(1).save(16)
    c.label('findnext').op(0xc2,8).jump(0x10,'findoption')
    c.label('foundoptions'); c.local(16).jump(0x11,'pageoptions')
    c.local(0).local(1); p.rpc(c,3,4,7)
    c.integer(0).integer(1).integer(1).op(0x26)
    p.text(c,''); c.op(0x20).op(0x46,1290,8).save(13)
    # Display-only: keep the row in the display list, but do not let the
    # category refresh overwrite the load-state text with slider value 0.
    c.local(1); p.prop(c,'Settings'); c.op(0x4f,p.name('pop'),0)
    c.local(13).op(0x27).op(0x27).op(0x4f,p.name('Enable'),2)
    c.local(13); p.prop(c,'container_slider'); c.op(0x27).op(0x61,p.name('visible'))
    c.local(13); p.prop(c,'txt_value'); p.prop(c,'value'); p.prop(c,'text'); c.save(14)
    c.local(14).integer(230).op(0x61,p.name('width'))
    c.local(13); p.prop(c,'txt_value'); c.op(0x2a); p.prop(c,'x'); c.integer(170).op(0xa1).op(0x61,p.name('x'))
    p.rpc(c,5,4,7); c.integer(1).jump(0x14,'notloaded')
    c.local(14); p.localized(c,'✓ 已加载','✓ Loaded'); c.op(0x61,p.name('text'))
    c.local(14); p.text(c,str(0x63cf79)); c.op(0x74).op(0x61,p.name('textColor')).jump(0x10,'nextpage')
    c.label('notloaded')
    c.local(14); p.localized(c,'未加载','Not loaded'); c.op(0x61,p.name('text'))
    c.local(14); p.text(c,str(0xe2b166)); c.op(0x74).op(0x61,p.name('textColor')).jump(0x10,'nextpage')
    c.label('pageoptions')
    c.local(0).local(1); p.rpc(c,3,4,7); c.op(0x4f,1294,2)
    c.integer(0).save(8)
    c.label('option'); c.local(8).local(5).jump(0x18,'nextpage')
    p.rpc(c,6,4,8); c.local(7).jump(0x14,'nextoption')
    p.key(c,'__sod2se_option_',8); c.save(9)
    p.settings(c); c.local(9); p.rpc(c,10,4,8); c.op(0x61,p.dynamic)
    p.rpc(c,9,4,8); c.op(0x73).save(10)
    c.local(10).integer(0).jump(0x14,'numeric')
    c.local(0).local(1); p.rpc(c,7,4,8); p.text(c,'placeholder'); p.text(c,'placeholder')
    c.local(9).local(0).op(0x66,1240).op(0x4f,1288,6).jump(0x10,'description')
    c.label('numeric')
    p.rpc(c,11,4,8); c.save(11); p.rpc(c,12,4,8); c.save(12)
    c.local(11).local(12).jump(0x18,'description')  # degenerate range: no divide by zero
    c.local(0).local(1); p.rpc(c,7,4,8); c.local(11).local(12).integer(1).op(0x26)
    c.local(9).local(0).op(0x66,1240).op(0x46,1290,8).save(13)
    c.local(10).integer(2).jump(0x14,'description')
    c.local(13); p.prop(c,'txt_value'); p.prop(c,'value'); p.prop(c,'text'); c.save(14)
    c.local(14); p.text(c,'input'); c.op(0x61,p.name('type'))
    c.local(14).op(0x26).op(0x61,p.name('selectable'))
    c.local(14).integer(11).op(0x61,p.name('maxChars'))
    # The stock slider's value is plain text.  Turn that value into an
    # identifiable, mouse-focusable numeric field while retaining the slider.
    c.local(14); p.text(c,'0-9'); c.op(0x61,p.name('restrict'))
    c.local(14).op(0x26).op(0x61,p.name('background'))
    c.local(14); p.text(c,str(0x281b11)); c.op(0x74).op(0x61,p.name('backgroundColor'))
    c.local(14); p.text(c,str(0xf4e7cd)); c.op(0x74).op(0x61,p.name('textColor'))
    c.local(14).op(0x26).op(0x61,p.name('border'))
    c.local(14); p.text(c,str(0xb94e17)); c.op(0x74).op(0x61,p.name('borderColor'))
    c.local(14).op(0x26).op(0x61,p.name('mouseEnabled'))
    c.local(14).op(0x26).op(0x61,p.name('tabEnabled'))
    c.local(14).integer(72).op(0x61,p.name('width'))
    p.settings(c); p.key(c,'__sod2se_input_',8); c.local(14).op(0x61,p.dynamic)
    c.label('description')
    c.label('nextoption').op(0xc2,8).jump(0x10,'option')
    c.label('nextpage').op(0xc2,7).jump(0x10,'page')
    c.label('finish').op(0x47)
    c.label('unavailable'); p.textblock(c,'MCM 通道尚未就绪。请确认已启用配套 MCM，稍后返回重试。','MCM channel is not ready. Enable the matching MCM, then return and retry.'); c.op(0x47)
    c.label('original')
    # Discard v0.1.1 placeholder prefix; retain the ORIGINAL population body.
    p.bodies[1365].set('codeBytes',next(b.get('codeBytes') for b in original.find('bodies') if b.get('method_info')=='1365'))
    p.prefix(1282,c.done(),17,24)

    # One existing callback can serve all controls without new closures/bindings.
    c=Code(); c.local(0).op(0x66,1348).jump(0x12,'original')
    c.local(0).op(0x66,1348).op(0x66,1377).integer(0).jump(0x14,'original')
    p.settings(c); p.prop(c,'__sod2se_revision'); c.op(0x73).save(1)
    c.local(1).integer(0).jump(0x16,'finish')
    p.settings(c); p.prop(c,'__sod2se_count'); c.op(0x73).save(2)
    c.integer(0).save(3)
    c.label('loop'); c.local(3).local(2).jump(0x18,'finish')
    p.settings(c); p.key(c,'__sod2se_option_',3); c.op(0x66,p.dynamic).op(0x73).save(4)
    p.rpc(c,9,1,3); c.integer(2).jump(0x14,'submit')
    p.settings(c); p.key(c,'__sod2se_input_',3); c.op(0x66,p.dynamic).save(5)
    c.local(5).jump(0x12,'submit')
    c.local(5); p.prop(c,'text'); c.op(0x75).save(4) # Number: preserve NaN for native rejection
    c.label('submit'); p.rpc(c,15,1,3,4); c.op(0x29).op(0xc2,3).jump(0x10,'loop')
    c.label('finish').op(0x21).op(0x48)
    c.label('original'); p.prefix(1240,c.done(),6)
    # Commit typed values before native back/close. Callback checks active category.
    for qname in [1276,1277]:  # OnCategoryBack / RequestSettingsHide
        c=Code().local(0).op(0x66,1348).jump(0x12,'original')
        c.local(0).op(0x66,1348).op(0x66,1377).integer(0).jump(0x14,'original')
        c.local(0).op(0x4f,1240,0).label('original'); p.prefix(qname,c.done())
    # Confirm submits a typed value using the same game action for keyboard/gamepad.
    api_input = next(i for i,n in enumerate(p.names) if n.get('kind')=='7' and
        n.get('namespace_index')=='1' and p.strings[int(n.get('name_index','0'))].text=='ApiInput')
    c=Code().local(1); p.text(c,'Confirm'); c.jump(0x14,'original')
    c.local(0).op(0x66,1348).jump(0x12,'original')
    c.local(0).op(0x66,1348).op(0x66,1377).integer(0).jump(0x14,'original')
    c.local(0).op(0x4f,1240,0).label('original'); p.prefix(api_input,c.done())
    # Stock UpdateHints only tests slider_setting; slider_value_setting is a
    # sibling class. Use the game's existing left/right hint set (205).
    c=Code().local(0).op(0x66,1348).jump(0x12,'original')
    c.local(0).op(0x66,1348).op(0x66,1380).op(0x46,156,0).jump(0x12,'original')
    c.local(0).op(0x66,1348).op(0x66,1380).op(0x46,270,0).op(0xb2,1165).jump(0x12,'original')
    c.local(0).op(0x66,1367).integer(205).jump(0x13,'hintdone')
    c.local(0).integer(205).op(0x61,1367)
    c.op(0x60,287); p.text(c,'UI_Settings_SetHints'); c.integer(205).op(0x4f,1406,2)
    c.label('hintdone').op(0x47).label('original'); p.prefix(1228,c.done(),3)
    facts={'patched_methods':sorted(p.changed),'constants_append_only':True,'setting_list_dynamic_for_prefixed_mod_values':True,
           'original_traits_namespaces_signatures_preserved':True,'native_controls':True,
           'language_selection':'runtime-detected-read-only','runtime_verified':False}
    verify(original,p.abc,p.changed)
    return facts


def verify(before,after,changed):
    def norm(e):
        return (e.tag,sorted((k,v) for k,v in e.attrib.items() if k not in ('fileOffset','bytes')),
            (e.text or '').strip() if len(e) else (e.text or ''),[norm(x) for x in e])
    for a,b in zip(before,after,strict=True):
        if a.tag=='constants':
            for x,y in zip(a,b,strict=True):
                if x.tag in ('constant_string','constant_multiname','constant_namespace_set'):
                    if len(y)<len(x) or [norm(v) for v in x]!=[norm(v) for v in list(y)[:len(x)]]:raise ValueError('Constant identity drift')
                elif norm(x)!=norm(y):raise ValueError('Constant pool changed')
        elif a.tag=='bodies':
            for x,y in zip(a,b,strict=True):
                z=copy.deepcopy(y)
                if int(x.get('method_info')) in changed:
                    for attr in ('codeBytes','max_regs','max_stack'):z.set(attr,x.get(attr))
                if norm(x)!=norm(z):raise ValueError('Unexpected method change')
        elif a.tag=='instance_info':
            z=copy.deepcopy(b); list(z)[6].set('flags','9')
            if list(b)[6].get('flags')!='8' or norm(a)!=norm(z):raise ValueError('Class identity drift')
        elif norm(a)!=norm(b):raise ValueError('Binding identity changed: '+a.tag)
