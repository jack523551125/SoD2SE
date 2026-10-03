"""Keep the native components tied to the research database and to C#.

Game-version offsets live in exactly one place, ``GameApi/native/MeleeOffsets.h``, and
every entry names the record it was read from.  This script proves the record
and the value still agree and that nobody reintroduced an anonymous number:

* ``rva::NAME = 0x…;  // <function id>`` must match that record's ``rva``,
* ``field::NAME = 0x…;  // <structure id>`` must be one of its field offsets,
* no other native source may spell a module RVA or a structure offset,
* every constant declared in the header must be referenced by native code,
* every native module entry point the managed side asks for must be exported,
* the MCM state record must match ``Native/src/Mcm/McmProtocol.h``'s static_assert block.
"""

# Standalone script execution resolves imports from its source-owning project.
import sys as _layout_sys
_layout_sys.dont_write_bytecode = True
from pathlib import Path as _LayoutPath
_layout_sys.path.insert(0, str(_LayoutPath(__file__).resolve().parents[2]))
import json
import re
import sys
from pathlib import Path


class VerificationError(Exception):
    pass


COMMENT_RE = re.compile(r'//[^\n]*')
NAMESPACE_RE = re.compile(r'namespace\s+(rva|field)\s*\{(.*?)\n\}', re.S)
CONSTANT_RE = re.compile(
    r'constexpr\s+uintptr_t\s+(\w+)\s*=\s*(0x[0-9A-Fa-f]+)\s*;\s*//\s*([A-Za-z0-9._\-]+)\s*$',
    re.M)
RAW_RVA_RE = re.compile(r'base\s*\+\s*(0x[0-9A-Fa-f]+|\d+)')
RAW_ARGUMENT_RE = re.compile(
    r'\b(?:Read\s*<[^>]*>|Write)\s*\(\s*[^,()]+,\s*(0x[0-9A-Fa-f]+|\d+)\s*[,)]')
MANAGED_ENTRY_RE = re.compile(
    r'NativeModule\s*\(\s*[^,()]+,\s*[^,()]+,\s*[^,()]+,\s*"([^"]+)"')
MANAGED_DIRECT_ENTRY_RE = re.compile(
    r'NativePluginModule\.LoadAndStart\s*\(\s*[^,()]+,\s*[^,()]+,\s*"([^"]+)"')
EXPORT_RE = re.compile(r'__declspec\s*\(\s*dllexport\s*\)[^;{]*?\b(\w+)\s*\(')
MCM_FIELD_RE = re.compile(
    r'offsetof\(\s*State\s*,\s*(\w+)\s*\)\s*==\s*(\d+)')
MCM_SIZE_RE = re.compile(r'sizeof\(\s*State\s*\)\s*==\s*(\d+)')


def native_files(root, pattern):
    groups = [root / kind / group for kind in ('src','tests') for group in ('Growth','Mcm','Melee','Shared')]
    groups.append(root.parent / 'GameApi/native')
    return list(root.glob(pattern)) + [file for group in groups for file in group.rglob(pattern)]


def locate(base, relative):
    from Automation.source_layout import resolve
    relative = resolve(relative)
    for candidate in (base / relative, base / 'source' / relative):
        if candidate.is_file():
            return candidate
    raise VerificationError('找不到文件：' + relative)


def locate_native(base):
    for candidate in (base / 'Native', base / 'source' / 'Native'):
        if candidate.is_dir():
            return candidate
    raise VerificationError('找不到 Native 源码目录')


def load_database(base):
    for root in (base / 'Research', base / 'source' / 'Research'):
        if not root.is_dir():
            continue
        databases = sorted(root.glob('*/*/structs.json'))
        if not databases:
            continue
        if len(databases) != 1:
            # A fixed-version framework pins one build; two databases would make
            # "the offset is recorded" ambiguous.
            raise VerificationError('逆向资料库必须只描述一个游戏版本：' + ', '.join(
                str(path.parent.name) for path in databases))
        structs = json.loads(databases[0].read_text(encoding='utf-8'))
        functions_path = databases[0].parent / 'functions.json'
        functions = json.loads(functions_path.read_text(encoding='utf-8'))
        return databases[0].parent.name, structs, functions
    raise VerificationError('找不到 Research/*/*/structs.json')


def check_offset_constants(header_text, build, structs, functions):
    sections = {name: body for name, body in NAMESPACE_RE.findall(header_text)}
    if set(sections) != {'rva', 'field'}:
        raise VerificationError('MeleeOffsets.h 必须只有 rva 与 field 两个命名空间')

    function_rvas = {}
    for function in functions.get('functions', []):
        if 'rva' in function:
            function_rvas.setdefault(function['id'], []).append(int(str(function['rva']), 16))

    struct_offsets = {}
    for structure in structs.get('structures', []):
        offsets = set()
        for field in structure.get('fields', []):
            token = str(field.get('offset', ''))
            if re.fullmatch(r'0x[0-9A-Fa-f]+', token):
                offsets.add(int(token, 16))
        struct_offsets.setdefault(structure.get('id'), set()).update(offsets)

    checked = 0
    declared = []
    for namespace in ('rva', 'field'):
        entries = CONSTANT_RE.findall(sections[namespace])
        if not entries:
            raise VerificationError('%s 命名空间没有带研究记录注释的常量' % namespace)
        for name, value, record in entries:
            declared.append(name)
            number = int(value, 16)
            if namespace == 'rva':
                if record not in function_rvas:
                    raise VerificationError(
                        '%s 引用的函数记录 %s 不在 %s 的 functions.json 中' % (name, record, build))
                if number not in function_rvas[record]:
                    raise VerificationError(
                        '%s = %s 与记录 %s 的 RVA %s 不一致' % (
                            name, value, record, ', '.join(hex(item) for item in function_rvas[record])))
            else:
                if record not in struct_offsets:
                    raise VerificationError(
                        '%s 引用的结构体记录 %s 不在 %s 的 structs.json 中' % (name, record, build))
                if number not in struct_offsets[record]:
                    raise VerificationError(
                        '%s = %s 不是记录 %s 记录的字段偏移 %s' % (
                            name, value, record,
                            ', '.join(sorted(hex(item) for item in struct_offsets[record])) or '（无）'))
            checked += 1
    return declared, checked


def check_guarded_iggy_rvas_text(header_text, evidence):
    """Allow only the fixed Iggy DLL RVAs protected by its hash/export guards."""
    abi = evidence.get('iggy_callback_abi', {})
    expected_hash = str(abi.get('dll_sha256', '')).lower()
    if not re.fullmatch(r'[0-9a-f]{64}', expected_hash):
        raise VerificationError('Iggy RVA evidence has no pinned DLL SHA-256')
    text = COMMENT_RE.sub('', header_text)
    digest = re.search(r'expected\s*\[\s*32\s*\]\s*=\s*\{([^}]*)\}', text)
    if digest is None:
        raise VerificationError('NativeSettingsIggy.h has no pinned DLL digest guard')
    actual_bytes = [int(value, 16) for value in re.findall(r'0x([0-9A-Fa-f]{1,2})', digest.group(1))]
    expected_bytes = [int(expected_hash[i:i + 2], 16) for i in range(0, 64, 2)]
    if actual_bytes != expected_bytes:
        raise VerificationError('NativeSettingsIggy.h SHA-256 guard differs from the research record')
    initializer = re.search(
        r'inline\s+InitStatus\s+Initialize\([^)]*\)\s*\{(.*?)\n\}', text, re.S)
    if initializer is None:
        raise VerificationError('Iggy ABI initialization routine is missing')
    initializer_text = initializer.group(1)
    module_guard = re.search(
        r'if\s*\(\s*!module\s*\)\s*return\s+initStatus\s*=\s*InitStatus::WaitingForModule\s*;',
        initializer_text)
    hash_guard = re.search(
        r'if\s*\(\s*!PinnedFile\(\s*module\s*\)\s*\)\s*return\s+initStatus\s*=\s*InitStatus::UnsupportedHash\s*;',
        initializer_text)
    get_proc = initializer_text.find('GetProcAddress')
    if (module_guard is None or hash_guard is None or get_proc < 0 or
            module_guard.start() > hash_guard.start() or hash_guard.end() > get_proc):
        raise VerificationError('Iggy export RVAs are used before module and pinned-hash checks')
    if not re.search(
            r'if\s*\(\s*!verified\s*&&\s*CanRetryInitialization\(\)\s*&&\s*'
            r'InitializationRetryDue\(initializeRetry\)\s*\)\s*Initialize\(channel,\s*channelGate\)',
            text):
        raise VerificationError('Iggy initialization does not retry a module loaded after MCM startup')

    exports = abi.get('disassembly_rvas', {})
    allowed = set()
    for symbol, export_name in (
        ('resultPath', 'result_path_export'),
        ('setInt', 'set_s32_export'),
        ('setText', 'set_string_utf8_export'),
    ):
        token = str(exports.get(export_name, ''))
        if not re.fullmatch(r'0x[0-9A-Fa-f]+', token):
            raise VerificationError('Research record has no RVA for ' + export_name)
        value = int(token, 16)
        expression = r'reinterpret_cast<void\*>\(\s*' + re.escape(symbol) + \
            r'\s*\)\s*!=\s*base\s*\+\s*0x[0-9A-Fa-f]+'
        match = re.search(expression, text)
        if match is None or int(re.search(r'0x([0-9A-Fa-f]+)$', match.group(0)).group(1), 16) != value:
            raise VerificationError('Iggy export RVA guard differs from the research record: ' + export_name)
        allowed.add(value)

    slots = abi.get('callback', {}).get('registration_slots', {})
    narrow = str(slots.get('narrow_function_pointer_rva', ''))
    wide = str(slots.get('wide_function_pointer_rva', ''))
    if not (re.fullmatch(r'0x[0-9A-Fa-f]+', narrow) and re.fullmatch(r'0x[0-9A-Fa-f]+', wide)):
        raise VerificationError('Research record has no narrow/wide Iggy callback slots')
    narrow_value, wide_value = int(narrow, 16), int(wide, 16)
    callback = re.search(r'callbackSlot\s*=\s*reinterpret_cast<Callback\*>\(\s*base\s*\+\s*0x([0-9A-Fa-f]+)\s*\)', text)
    if callback is None or int(callback.group(1), 16) != narrow_value or wide_value - narrow_value != 16:
        raise VerificationError('Iggy callback slot guard differs from the research record')
    allowed.add(narrow_value)

    pump = text.find('inline void Pump()')
    if pump < 0:
        raise VerificationError('Iggy input hook has no Pump routine')
    pump_text = text[pump:]
    verified_guard = re.search(r'if\s*\(\s*!verified\s*\)\s*return\s*;', pump_text)
    tick_lookup = re.search(r'GetProcAddress\(module,\s*"IggyPlayerTickRS"\)', pump_text)
    input_guard = re.search(
        r'if\s*\(\s*module\s*&&\s*address\s*==\s*base\s*\+\s*0x[0-9A-Fa-f]+\s*&&.*?\)\s*\{',
        pump_text, re.S)
    if (verified_guard is None or tick_lookup is None or input_guard is None or
            verified_guard.start() > tick_lookup.start() or tick_lookup.start() > input_guard.start()):
        raise VerificationError('Iggy input export RVAs are used before the pinned DLL guard')
    for symbol, export_name in (
        ('address', 'player_tick_export'),
        ('dispatchEvent', 'dispatch_event_export'),
        ('makeEventChar', 'make_event_char_export'),
        ('makeEventKey', 'make_event_key_export'),
        ('hasFocusedEditable', 'focused_editable_export'),
    ):
        token = str(exports.get(export_name, ''))
        if not re.fullmatch(r'0x[0-9A-Fa-f]+', token):
            raise VerificationError('Research record has no RVA for ' + export_name)
        if symbol != 'address':
            export_symbol = {
                'dispatchEvent': 'IggyPlayerDispatchEventRS',
                'makeEventChar': 'IggyMakeEventChar',
                'makeEventKey': 'IggyMakeEventKey',
                'hasFocusedEditable': 'IggyPlayerHasFocusedEditableTextfield',
            }[symbol]
            binding = (symbol + ' = reinterpret_cast<')
            if not re.search(re.escape(binding) + r'[^>]+>\(GetProcAddress\(module,\s*"' +
                             re.escape(export_symbol) + r'"\)\)', initializer_text):
                raise VerificationError('Iggy input export is not bound to the recorded name: ' + export_symbol)
        expression = (r'(?<!\w)' + re.escape(symbol) if symbol == 'address' else
                      r'reinterpret_cast<void\*>\(\s*' + re.escape(symbol) + r'\s*\)')
        match = re.search(expression + r'\s*==\s*base\s*\+\s*0x([0-9A-Fa-f]+)', input_guard.group(0))
        if match is None or int(match.group(1), 16) != int(token, 16):
            raise VerificationError('Iggy input export RVA guard differs from research record: ' + export_name)
        allowed.add(int(token, 16))
    return allowed


def check_no_raw_offsets(native_root, header_name, guarded_iggy_rvas=()):
    """Reject an anonymous offset anywhere but the offsets header."""
    for path in sorted(native_files(native_root, '*.cpp')) + sorted(native_files(native_root, '*.h')):
        if path.name == header_name:
            continue
        text = COMMENT_RE.sub('', path.read_text(encoding='utf-8'))
        for pattern, hint in ((RAW_RVA_RE, '模块 RVA'), (RAW_ARGUMENT_RE, '结构体偏移')):
            for match in pattern.finditer(text):
                if (path.name == 'NativeSettingsIggy.h' and pattern is RAW_RVA_RE
                        and int(match.group(1), 0) in guarded_iggy_rvas):
                    continue
                line = text[:match.start()].count('\n') + 1
                raise VerificationError(
                    '%s:%d 直接写裸%s（%s）；请在 Native/%s 中记名并注明研究记录'
                    % (path.name, line, hint, match.group(0).strip(), header_name))


def check_constants_are_used(header_names, native_root, header_name):
    text = '\n'.join(
        COMMENT_RE.sub('', path.read_text(encoding='utf-8'))
        for path in sorted(native_files(native_root, '*.cpp')) + sorted(native_files(native_root, '*.h'))
        if path.name != header_name)
    for name in header_names:
        if not re.search(r'\b' + name + r'\b', text):
            raise VerificationError('MeleeOffsets.h 的 %s 没有被原生代码引用' % name)


def check_growth_stat_offsets(header, runtime, evidence):
    """Check generated hook guards and enum values against pinned derivation."""
    digest = evidence.get('target_sha256', '')
    if not re.fullmatch('[0-9A-F]{64}', digest) or ('ImageSha256[] = "' + digest + '"') not in header:
        raise VerificationError('Growth stat image hash differs from its derivation')
    rows = evidence.get('functions', [])
    actual = re.findall(r'HookSpec\s+(\w+)\s*=\s*\{(0x[0-9a-f]+),\s*\{([^}]*)\}\}', header)
    if len(actual) != len(rows) or len({name for name, _, _ in actual}) != len(rows):
        raise VerificationError('Growth stat hook catalog differs from its derivation')
    parsed = {name: (rva, ''.join(re.findall(r'0x([0-9a-f]{2})', guard))) for name, rva, guard in actual}
    for row in rows:
        if parsed.get(row['symbol']) != (row['rva'], row['guard']):
            raise VerificationError('Growth stat RVA/guard differs: ' + row['symbol'])
        if ('&stat_native::' + row['symbol']) not in runtime:
            raise VerificationError('Growth stat hook is not guarded at installation: ' + row['symbol'])
    enums = {name: int(value) for name, value in re.findall(r'uint8_t\s+(\w+)\s*=\s*(\d+)', header)}
    if enums != evidence.get('hook_stat_mapping'):
        raise VerificationError('Growth stat enum mappings differ from native registration')
    text = COMMENT_RE.sub('', runtime)
    hash_check = text.find('sod2_native::PinnedImageFile(module, stat_native::ImageSha256)')
    instruction_check = text.find('std::memcmp(image + spec.rva, spec.guard, sizeof(spec.guard))')
    hook_creation = text.find('MH_CreateHook(')
    if not (0 <= hash_check < instruction_check < hook_creation):
        raise VerificationError('Growth stat hooks are created before image/instruction verification')
    if any(evidence.get('scope', {}).get(name) is not False for name in
           ('game_process_started_or_attached', 'runtime_effects_verified', 'vanilla_skill_suppression_verified')):
        raise VerificationError('Growth stat derivation is incorrectly presented as runtime verification')
    return len(rows), len(enums)


def check_growth_skill_offsets(header, runtime, evidence, target_sha256):
    if evidence.get('target_sha256') != target_sha256:
        raise VerificationError('Growth skill derivation differs from the pinned stat image')
    rows = evidence.get('hooks', []) + evidence.get('helpers', [])
    actual = re.findall(r'HookSpec\s+(\w+)\s*=\s*\{(0x[0-9a-f]+),\s*\{([^}]*)\}\}', header)
    if len(rows) != 10 or len(actual) != len(rows) or len({name for name, _, _ in actual}) != len(rows):
        raise VerificationError('Growth skill hook/helper catalog differs from its derivation')
    parsed = {name: (rva, ''.join(re.findall(r'0x([0-9a-f]{2})', guard))) for name, rva, guard in actual}
    for row in rows:
        if parsed.get(row['symbol']) != (row['rva'], row['guard']) or ('&skill_native::' + row['symbol']) not in runtime:
            raise VerificationError('Growth skill hook/helper guard differs: ' + row['symbol'])
    fields = {name: int(value) for name, value in re.findall(r'uintptr_t\s+(\w+)\s*=\s*(\d+)\s*;', header)}
    if fields != evidence.get('fields'):
        raise VerificationError('Growth skill fields differ from registration/accessor evidence')
    if ('CharacterPackage[] = L"' + evidence.get('character_class_package', '') + '"') not in header:
        raise VerificationError('Growth skill class getter package argument differs')
    if any(evidence.get('scope', {}).get(name) is not False for name in ('runtime_verified', 'existing_provider_cache_refresh_verified')):
        raise VerificationError('Growth skill derivation is incorrectly presented as live verification')
    primary = evidence.get('assets', {}).get('primary', [])
    if not primary or {r.get('base_id') for r in primary} != {'Cardio', 'Wits', 'Fighting', 'Shooting'}:
        raise VerificationError('Growth skill core flag is not confined to four primary families')
    text = COMMENT_RE.sub('', runtime)
    if not re.search(r'for\s*\(\s*const auto\* helper\s*:\s*helpers\s*\).*?std::memcmp\(image \+ helper->rva, helper->guard', text, re.S):
        raise VerificationError('Growth skill helper guards not checked before engine calls')
    helper_check = text.find('std::memcmp(image + helper->rva, helper->guard')
    class_call = text.find('characterClass = getClass(skill_native::CharacterPackage)')
    hook_creation = text.find('MH_CreateHook(')
    if not (0 <= helper_check < class_call < hook_creation):
        raise VerificationError('Growth skill class getter executes before helper verification')
    return len(rows), len(fields), len(primary)


def check_growth_fatigue_offsets(header, runtime, evidence, target_sha256):
    if evidence.get('target_sha256') != target_sha256:
        raise VerificationError('Growth fatigue derivation differs from the pinned image')
    rows = evidence.get('hooks', []) + evidence.get('helpers', [])
    parsed = {name: (rva, ''.join(re.findall(r'0x([0-9a-f]{2})', guard)))
              for name, rva, guard in re.findall(r'HookSpec\s+(\w+)\s*=\s*\{(0x[0-9a-f]+),\s*\{([^}]*)\}\}', header)}
    if set(parsed) != {'FatigueSet', 'RecoverFatigue'} or len(rows) != 2:
        raise VerificationError('Growth fatigue mutation/recovery catalog differs')
    for row in rows:
        if parsed.get(row['symbol']) != (row['rva'], row['guard']) or ('&fatigue_native::' + row['symbol']) not in runtime:
            raise VerificationError('Growth fatigue guard differs: ' + row['symbol'])
    fields = {name: int(value) for name, value in re.findall(r'uintptr_t\s+(\w+)\s*=\s*(\d+)\s*;', header)}
    if fields != evidence.get('fields') or set(fields) != {'CharacterFatigue'}:
        raise VerificationError('Growth fatigue field differs from recovery/mutation evidence')
    if any(evidence.get('scope', {}).get(name) is not False for name in
           ('runtime_verified', 'all_existing_fatigue_clear_paths_verified')):
        raise VerificationError('Growth fatigue derivation falsely claims complete live clearing')
    text = COMMENT_RE.sub('', runtime)
    if ('recoverFatigue(character, current);' not in text or
            'return ReadFatigue(character, current) && current == 0;' not in text or
            'originalFatigue(character, prevent ? 0.0f : value, resource);' not in text):
        raise VerificationError('Growth fatigue clear does not check original mutation outcome')
    return len(rows), len(fields)


def check_growth_skill_cache_offsets(header, runtime, evidence, target_sha256):
    if evidence.get('target_sha256') != target_sha256:
        raise VerificationError('Growth skill cache derivation differs from the pinned image')
    rows = evidence.get('hooks', []) + evidence.get('helpers', [])
    parsed = {name: (rva, ''.join(re.findall(r'0x([0-9a-f]{2})', guard)))
              for name, rva, guard in re.findall(r'HookSpec\s+(\w+)\s*=\s*\{(0x[0-9a-f]+),\s*\{([^}]*)\}\}', header)}
    if set(parsed) != {'PersonalStatCount', 'CommunityStatCount', 'InvalidateStat'} or len(rows) != 3:
        raise VerificationError('Growth skill cache hook/helper catalog differs')
    for row in rows:
        if parsed.get(row['symbol']) != (row['rva'], row['guard']) or ('&skill_cache_native::' + row['symbol']) not in runtime:
            raise VerificationError('Growth skill cache guard differs: ' + row['symbol'])
    fields = {name: int(value) for name, value in re.findall(r'uintptr_t\s+(\w+)\s*=\s*(\d+)\s*;', header)}
    if fields != evidence.get('fields'):
        raise VerificationError('Growth skill cache owner/container fields differ')
    if ('CommunityVtable = ' + evidence.get('community_provider_vtable_rva', '') + ';') not in header:
        raise VerificationError('Growth community provider vtable differs')
    table = re.search(r'CommunityFunctions\[\]\s*=\s*\{([^}]*)\}', header)
    if table is None or re.findall(r'0x[0-9a-f]+', table.group(1)) != evidence.get('community_provider_functions'):
        raise VerificationError('Growth community provider virtual methods differ')
    if evidence.get('stat_count') != 195 or 'StatCount = 195;' not in header:
        raise VerificationError('Growth skill cache stat domain differs')
    if any(evidence.get('scope', {}).get(name) is not False for name in ('runtime_verified', 'live_cache_restore_verified')):
        raise VerificationError('Growth cache derivation falsely claims live restoration')
    text = COMMENT_RE.sub('', runtime)
    community = re.search(r'int32_t __fastcall CommunityCount\(.*?\n\}', text, re.S)
    if community is None or not (0 <= community.group().find('if (!IsCommunityProvider(provider)) return baseline;') <
            community.group().find('skill_cache_native::SkillCommunityProvider')) or '== communityVtable' not in text:
        raise VerificationError('Shared count accessor derives a skill owner before checking provider type')
    vtable_check = text.find('methods[i] != reinterpret_cast<uintptr_t>(image) + skill_cache_native::CommunityFunctions[i]')
    if not (0 <= vtable_check < text.find('MH_CreateHook(')):
        raise VerificationError('Community provider vtable is not guarded before hooks')
    if 'i < skill_cache_native::StatCount' not in text or 'invalidateStat(characterStats, static_cast<uint8_t>(i));' not in text:
        raise VerificationError('Original stat invalidation path missing')
    return len(rows), len(fields)


def check_growth_thread_offsets(header, runtime, evidence, target_sha256):
    if evidence.get('target_sha256') != target_sha256:
        raise VerificationError('Growth thread evidence differs from pinned image')
    rows = evidence.get('guards', [])
    parsed = {name: (rva, ''.join(re.findall(r'0x([0-9a-f]{2})', guard)))
              for name, rva, guard in re.findall(r'HookSpec\s+(\w+)\s*=\s*\{(0x[0-9a-f]+),\s*\{([^}]*)\}\}', header)}
    if len(parsed) != 6 or len(rows) != 6 or len(evidence.get('assertions', [])) != 4:
        raise VerificationError('Growth engine thread initialization/assertion evidence missing')
    for row in rows:
        if parsed.get(row['symbol']) != (row['rva'], row['guard']) or ('&thread_native::' + row['symbol']) not in runtime:
            raise VerificationError('Growth engine thread proof guard differs: ' + row['symbol'])
    globals_ = {name: int(value) for name, value in re.findall(r'uintptr_t\s+(\w+)\s*=\s*(\d+)\s*;', header)}
    if globals_ != evidence.get('globals') or set(globals_) != {'GameThreadId', 'GameThreadInitialized'}:
        raise VerificationError('Growth engine thread globals differ from original assertions')
    if any(evidence.get('scope', {}).get(name) is not False for name in ('runtime_verified', 'bootstrap_verified')):
        raise VerificationError('Growth thread static evidence falsely claims live bootstrap')
    text = COMMENT_RE.sub('', runtime)
    guard = text.find('std::memcmp(image + proof->rva, proof->guard, sizeof(proof->guard))')
    read = text.find('if (!*engineThreadInitialized || *engineThreadId != registration.gameThread)')
    creation = text.find('MH_CreateHook(')
    if not (0 <= guard < read < creation):
        raise VerificationError('Growth registration trusts a thread before checking engine proof')
    if '*engineThreadId == owner.gameThread' not in text or '*engineThreadInitialized' not in text or text.count('!ThreadAllowed()') < 4:
        raise VerificationError('Growth consumer runtime trusts a self-reported thread ID')
    return len(rows), len(globals_)


def check_growth_world_offsets(header, runtime, evidence, target_sha256):
    if evidence.get('target_sha256') != target_sha256:
        raise VerificationError('Growth world derivation differs from the pinned image')
    rows = evidence.get('helpers', [])
    actual = re.findall(r'HookSpec\s+(\w+)\s*=\s*\{(0x[0-9a-f]+),\s*\{([^}]*)\}\}', header)
    parsed = {name: (rva, ''.join(re.findall(r'0x([0-9a-f]{2})', guard))) for name, rva, guard in actual}
    expected = {'WorldDelta', 'WorldTime', 'WorldPaused', 'ResolveController', 'ControllerClass', 'SetPauseContext'}
    if len(rows) != 6 or len(actual) != 6 or set(parsed) != expected:
        raise VerificationError('Growth world clock/pause helper catalog differs')
    for row in rows:
        if parsed.get(row['symbol']) != (row['rva'], row['guard']) or ('&world_native::' + row['symbol']) not in runtime:
            raise VerificationError('Growth world helper is not guarded: ' + row['symbol'])
    fields = {name: int(value) for name, value in re.findall(r'uintptr_t\s+(\w+)\s*=\s*(\d+)\s*;', header)}
    if fields != evidence.get('fields'):
        raise VerificationError('Growth world controller fields differ')
    if ('ControllerPackage = L"' + evidence.get('package', '') + '"') not in header:
        raise VerificationError('Growth world controller class package differs')
    if evidence.get('pause_comparison', {}).get('name') != '_wcsicmp':
        raise VerificationError('Growth world pause removal comparison is unproven')
    if any(evidence.get('scope', {}).get(name) is not False for name in
           ('runtime_verified', 'world_frame_source_verified', 'pause_navigation_verified')):
        raise VerificationError('Growth world derivation falsely claims live frame/pause delivery')
    text = COMMENT_RE.sub('', runtime)
    positions = [text.find(value) for value in (
        'sod2_native::PinnedImageFile(module, stat_native::ImageSha256)',
        'std::memcmp(image + proof->rva, proof->guard, sizeof(proof->guard))',
        'if (!*engineThreadInitialized || *engineThreadId != registration.gameThread)',
        'controllerClass = getClass(world_native::ControllerPackage)')]
    if any(p < 0 for p in positions) or positions != sorted(positions):
        raise VerificationError('Growth world engine helpers execute before pinned thread/ABI guards')
    if '*engineThreadId == ownerThread' not in text or text.count('!ThreadAllowed()') < 4:
        raise VerificationError('Growth world operations are not bound to the actual engine thread')
    for fragment in ('frame.serial <= lastSerial', 'lastSerial = frame.serial;',
                     'if (!frame.singlePlayer || frame.loading) return true;',
                     'if (result.paused) return true;', 'remainderMilliseconds + static_cast<double>(delta) * 1000.0',
                     'setContext(current, false, &pauseString);', 'if (!ContextMatches(current, matches) || matches) return false;',
                     'current != pauseController', 'frame.epoch != pauseEpoch'):
        if fragment not in text:
            raise VerificationError('Growth world frame/pause ownership check missing: ' + fragment)
    return len(rows), len(fields)


def check_growth_frame_offsets(header, runtime, evidence, target_sha256):
    if evidence.get('target_sha256') != target_sha256 or evidence.get('abi') != 'void(void*, uint32_t, float)':
        raise VerificationError('Growth frame producer build/ABI differs')
    rows = evidence.get('guards', [])
    actual = re.findall(r'HookSpec\s+(\w+)\s*=\s*\{(0x[0-9a-f]+),\s*\{([^}]*)\}\}', header)
    parsed = {name: (rva, ''.join(re.findall(r'0x([0-9a-f]{2})', guard))) for name, rva, guard in actual}
    expected = {'WorldTick', 'DeltaWrite', 'TimeWrite', 'LevelTickSource', 'TickCaller0', 'TickCaller1'}
    if len(rows) != 6 or len(actual) != 6 or set(parsed) != expected:
        raise VerificationError('Growth frame producer/caller guard catalog differs')
    for row in rows:
        if parsed.get(row['symbol']) != (row['rva'], row['guard']) or ('&frame_native::' + row['symbol']) not in runtime:
            raise VerificationError('Growth frame producer proof is not guarded: ' + row['symbol'])
    if not evidence.get('source', '').endswith('Engine\\Source\\Runtime\\Engine\\Private\\LevelTick.cpp') or len(evidence.get('callers', [])) != 2:
        raise VerificationError('Growth frame producer lacks original source/caller proof')
    if any(evidence.get('scope', {}).get(name) is not False for name in ('runtime_verified', 'main_world_classification_verified')):
        raise VerificationError('Growth frame static proof falsely claims live world ownership')
    text = COMMENT_RE.sub('', runtime)
    positions = [text.find(fragment) for fragment in (
        'sod2_native::PinnedImageFile(module, stat_native::ImageSha256)',
        'std::memcmp(image + proof->rva, proof->guard, sizeof(proof->guard))',
        'if (!*engineThreadInitialized || !*engineThreadId)', 'MH_CreateHook(')]
    if any(p < 0 for p in positions) or positions != sorted(positions):
        raise VerificationError('Growth frame installs before original producer/thread guards')
    for fragment in ('*engineThreadId == boundThread', 'GetCurrentThreadId() == boundThread',
                     'boundThread = *engineThreadId;', '!ThreadAllowed() || dispatching',
                     'const uint64_t serial = ++nextSerial;', 'Phase::Before', 'Phase::After',
                     'originalTick(world, kind, delta);', 'if (ready.load(std::memory_order_acquire) && !failed.load(std::memory_order_acquire))'):
        if fragment not in text: raise VerificationError('Growth frame dispatch guard missing: ' + fragment)
    if '__try' in text or 'MH_ALL_HOOKS' in text:
        raise VerificationError('Growth frame swallows engine exceptions or changes unrelated hooks')
    return len(rows), len(evidence['callers'])


def check_growth_infection_offsets(header, runtime, evidence, target_sha256):
    if evidence.get('target_sha256') != target_sha256 or evidence.get('abi') != 'float(void*, float, uint8_t)':
        raise VerificationError('Growth infection consumer build/ABI differs')
    rows = evidence.get('guards', [])
    actual = re.findall(r'HookSpec\s+(\w+)\s*=\s*\{(0x[0-9a-f]+),\s*\{([^}]*)\}\}', header)
    parsed = {name: (rva, ''.join(re.findall(r'0x([0-9a-f]{2})', guard))) for name, rva, guard in actual}
    if len(rows) != 5 or len(actual) != 5 or set(parsed) != {'InfectionGain', 'InfectionSetCall', 'InfectionAddCall', 'CountdownGain', 'CountdownCall'}:
        raise VerificationError('Growth infection/countdown proof catalog differs')
    for row in rows:
        if parsed.get(row['symbol']) != (row['rva'], row['guard']) or ('&infection_native::' + row['symbol']) not in runtime:
            raise VerificationError('Growth infection/countdown proof is not guarded: ' + row['symbol'])
    if evidence.get('hook') != 'InfectionGain' or evidence.get('enum_mapping') != {
        'SicknessFromAttacksMultiplier': 143, 'SicknessFromConsumablesMultiplier': 144,
        'BloodPlagueFromAttacksMultiplier': 145, 'BloodPlagueFromConsumablesMultiplier': 146}:
        raise VerificationError('Growth infection incorrectly merges infection and blood-plague countdown')
    if any(evidence.get('scope', {}).get(name) is not False for name in ('runtime_verified', 'all_infection_sources_verified')):
        raise VerificationError('Growth infection proof falsely claims all-source live verification')
    text = COMMENT_RE.sub('', runtime)
    specs = re.search(r'HookSpec\* specs\[\]\s*=\s*\{([^}]*)\}', text)
    if specs is None or '&infection_native::InfectionGain' not in specs.group(1) or 'Countdown' in specs.group(1):
        raise VerificationError('Growth infection hooks the established blood-plague decrement')
    for fragment in ('const float baseline = originalInfection(character, amount, kind);',
                     'std::isfinite(baseline) && baseline > 0 ? Resolved(character, Consumer::IncomingPlague, baseline) : baseline',
                     'reinterpret_cast<void**>(&originalInfection)'):
        if fragment not in text: raise VerificationError('Growth infection original result/ABI preservation missing')
    return len(rows), 1


def check_growth_object_offsets(header, runtime, evidence, target_sha256):
    if evidence.get('schema') != 1 or evidence.get('target_sha256') != target_sha256:
        raise VerificationError('Growth object lifetime build differs')
    if evidence.get('abi') != {'AssignWeak': 'void(void*, void*)', 'ResolveWeak': 'void*(const void*)'}:
        raise VerificationError('Growth original weak reference ABI differs')
    guards = {'AssignWeak', 'ResolveWeak', 'AllocateSerial', 'SkillWeakWriter'}
    actual = re.findall(r'HookSpec\s+(\w+)\s*=\s*\{(0x[0-9a-f]+),\s*\{([^}]*)\}\}', header)
    parsed = {name: (rva, ''.join(re.findall(r'0x([0-9a-f]{2})', guard))) for name, rva, guard in actual}
    rows = evidence.get('guards', [])
    if len(rows) != 4 or len(actual) != 4 or set(parsed) != guards:
        raise VerificationError('Growth object helper proof set differs')
    for row in rows:
        if parsed.get(row['symbol']) != (row['rva'], row['guard']) or ('&object_native::' + row['symbol']) not in runtime:
            raise VerificationError('Growth object helper proof is not guarded: ' + row['symbol'])
    fields = {'ObjectIndex': 12, 'ItemStride': 24, 'ItemPointer': 0, 'ItemFlags': 8, 'ItemSerial': 16}
    globals_ = {'ObjectCount': '0x46326bc', 'ObjectData': '0x46326b0'}
    if evidence.get('fields') != fields or evidence.get('globals') != globals_ or evidence.get('weak_size') != 8 or evidence.get('invalid_item_flags') != '0x30000000':
        raise VerificationError('Growth original weak object array layout differs')
    for name, value in dict(fields, **globals_).items():
        if 'uintptr_t ' + name + ' = ' + str(value) + ';' not in header:
            raise VerificationError('Growth weak object field/global differs: ' + name)
    if 'uint32_t InvalidItemFlags = 0x30000000;' not in header:
        raise VerificationError('Growth original weak object invalid flags differ')
    if any(evidence.get('scope', {}).get(name) is not False for name in
           ('runtime_verified', 'persistent_survivor_identity_verified', 'world_owner_lifetime_verified')):
        raise VerificationError('Growth weak object proof falsely claims persistent identity or live world ownership')
    text = COMMENT_RE.sub('', runtime)
    positions = [text.find(fragment) for fragment in ('sod2_native::PinnedImageFile(module, stat_native::ImageSha256)',
        'std::memcmp(image + proof->rva, proof->guard, sizeof(proof->guard))', 'if (!ThreadAllowed()) return ERROR_INVALID_THREAD_ID;',
        'originalAssign = reinterpret_cast<Assign>')]
    if any(p < 0 for p in positions) or positions != sorted(positions):
        raise VerificationError('Growth original lifetime helpers bind before pinned/thread guards')
    for fragment in ('*engineThreadId == boundThread', 'GetCurrentThreadId() == boundThread',
        'live == object', '*objectCount == count && *objectData == data', 'Guard guard;',
        'originalAssign(&candidate, object);', 'candidate.index != index || candidate.serial <= 0 || originalResolve(&candidate) != object',
        'if (!Preflight(object, after) || after != index)', 'return originalResolve(&token);'):
        if fragment not in text: raise VerificationError('Growth original weak object guard missing: ' + fragment)
    if 'MH_CreateHook' in text or re.search(r'memcpy\s*\(\s*(?:item|object|data)\b', text):
        raise VerificationError('Growth lifetime service replaces original helpers or writes original object array')
    if 'bool CaptureExisting(' not in text or 'bool Existing(' not in text:
        raise VerificationError('Growth readonly pre-call incarnation capture is missing')
    readonly = text.split('bool CaptureExisting(', 1)[1].split('bool OnGameThread()', 1)[0]
    helper = text.split('bool Existing(', 1)[1].split('#pragma optimize', 1)[0]
    if 'if (!OnGameThread() || resolving) return false;' not in readonly or 'Existing(object, candidate)' not in readonly or 'Current(candidate, object)' not in readonly:
        raise VerificationError('Growth readonly capture lacks thread or current-incarnation revalidation')
    if re.search(r'\b(?:originalAssign|originalResolve|AllocateSerial|CreateThread|Sleep|WaitForSingleObject)\s*\(', readonly + helper):
        raise VerificationError('Growth readonly existing-token capture invokes engine work or waits')
    return len(rows), len(fields)


def check_growth_ranged_offsets(header, runtime, evidence, target_sha256):
    if evidence.get('target_sha256') != target_sha256 or evidence.get('abi') != 'void(void*, void*, float*)':
        raise VerificationError('Growth ranged reflected output build/ABI differs')
    hooks = {'ReloadDuration', 'KickAngle', 'KickLeftMaxAngle', 'KickLeftMinAngle', 'KickRightMaxAngle', 'KickRightMinAngle'}
    guards = hooks | {'RangedStatsClass', 'RangedStatsConstructor', 'RangedStatsRebuild', 'RangedStatsCreate', 'RangedOwnerSource', 'RangedStatsLookup', 'RangedStatsLookupLeaf'}
    rows = evidence.get('guards', [])
    actual = re.findall(r'HookSpec\s+(\w+)\s*=\s*\{(0x[0-9a-f]+),\s*\{([^}]*)\}\}', header)
    parsed = {name: (rva, ''.join(re.findall(r'0x([0-9a-f]{2})', guard))) for name, rva, guard in actual}
    if len(rows) != 13 or len(actual) != 13 or set(parsed) != guards or set(evidence.get('hooks', [])) != hooks:
        raise VerificationError('Growth ranged getter/owner catalog differs')
    for row in rows:
        if parsed.get(row['symbol']) != (row['rva'], row['guard']) or ('&ranged_native::' + row['symbol']) not in runtime:
            raise VerificationError('Growth ranged output/owner proof is not guarded: ' + row['symbol'])
    if evidence.get('fields') != {'ReloadDuration': '0x16c', 'KickAngle': '0x124', 'KickLeftMaxAngle': '0x134',
            'KickLeftMinAngle': '0x12c', 'KickRightMaxAngle': '0x144', 'KickRightMinAngle': '0x13c'}:
        raise VerificationError('Growth ranged final getter fields differ')
    if 'StatsVtable = ' + evidence.get('StatsVtable', '') + ';' not in header or evidence.get('StatsVtable') != '0x341c038':
        raise VerificationError('Growth ranged stats native type differs')
    if evidence.get('owner_source', {}).get('holder_stats') != '0x28' or evidence.get('owner_source', {}).get('holder_pawn') != '0x60':
        raise VerificationError('Growth ranged separate holder owner source differs')
    if any(evidence.get('scope', {}).get(name) is not False for name in
           ('runtime_verified', 'stats_owner_lifetime_verified', 'all_reload_paths_verified', 'all_recoil_paths_verified')):
        raise VerificationError('Growth ranged static evidence falsely claims live owner or complete consumer coverage')
    text = COMMENT_RE.sub('', runtime)
    positions = [text.find(fragment) for fragment in ('sod2_native::PinnedImageFile(module, stat_native::ImageSha256)',
        'std::memcmp(image + proof->rva, proof->guard, sizeof(proof->guard))', 'if (!ThreadAllowed()) return ERROR_INVALID_THREAD_ID;', 'MH_CreateHook(')]
    if any(p < 0 for p in positions) or positions != sorted(positions):
        raise VerificationError('Growth ranged hooks install before pinned/thread guards')
    for original, detour, consumer in (('Reload', 'Reload', 'ReloadDuration'), ('Kick', 'Kick', 'Recoil'),
            ('LeftMax', 'LeftMax', 'Recoil'), ('LeftMin', 'LeftMin', 'Recoil'), ('RightMax', 'RightMax', 'Recoil'), ('RightMin', 'RightMin', 'Recoil')):
        if ('original' + original + '(stats, frame, output); Adjust(stats, output, Consumer::' + consumer + ');') not in text:
            raise VerificationError('Growth ranged getter no longer preserves original final output: ' + detour)
    for fragment in ('*static_cast<const uintptr_t*>(stats) != qualifiedVtable', '*engineThreadId == boundThread',
        'GetCurrentThreadId() == boundThread', '!ThreadAllowed() || resolving', 'baseline = *output;',
        'consumer == Consumer::ReloadDuration && baseline < 0', 'owner.lookup(owner.context, stats, &policy)', 'Write(output, result);'):
        if fragment not in text: raise VerificationError('Growth ranged actor/output guard missing: ' + fragment)
    if 'MH_ALL_HOOKS' in text or re.search(r'\+\s*(?:0x28|0x60)\b', text):
        raise VerificationError('Growth ranged consumer touches unrelated hooks or guesses owner from stats fields')
    return len(rows), len(hooks)


def check_growth_knockdown_offsets(header, runtime, evidence, target_sha256):
    if evidence.get('schema') != 1 or evidence.get('target_sha256') != target_sha256 or evidence.get('abi') != 'void(void*, void*, float*)':
        raise VerificationError('Growth melee knockdown build/ABI differs')
    guards = {'Knockdown', 'KnockdownDelta', 'ItemClass', 'ItemConstructor', 'SetPawn', 'OwnerConsumer', 'Rebuild', 'PawnStatSource'}
    rows = evidence.get('guards', [])
    actual = re.findall(r'HookSpec\s+(\w+)\s*=\s*\{(0x[0-9a-f]+),\s*\{([^}]*)\}\}', header)
    parsed = {name: (rva, ''.join(re.findall(r'0x([0-9a-f]{2})', guard))) for name, rva, guard in actual}
    if len(rows) != 8 or len(actual) != 8 or set(parsed) != guards:
        raise VerificationError('Growth melee item knockdown/type/owner proof set differs')
    for row in rows:
        if parsed.get(row['symbol']) != (row['rva'], row['guard']) or ('&knockdown_native::' + row['symbol']) not in runtime:
            raise VerificationError('Growth melee item knockdown proof is not guarded: ' + row['symbol'])
    if evidence.get('fields') != {'OwnerPawn': '0xf0', 'PrivateStats': '0xf8', 'Knockdown': '0x54', 'KnockdownDelta': '0x5c'}:
        raise VerificationError('Growth melee item knockdown/owner layout differs')
    if evidence.get('ItemVtable') != '0x3395008' or 'ItemVtable = 0x3395008;' not in header or 'OwnerPawn = 0xf0;' not in header:
        raise VerificationError('Growth melee item native class/owner differs')
    if any(evidence.get('scope', {}).get(name) is not False for name in
        ('runtime_verified', 'all_melee_knockdown_paths_verified', 'enemy_immunity_runtime_verified')):
        raise VerificationError('Growth melee item proof falsely claims all paths or live enemy immunity')
    text = COMMENT_RE.sub('', runtime)
    positions = [text.find(fragment) for fragment in ('sod2_native::PinnedImageFile(module, stat_native::ImageSha256)',
        'std::memcmp(image + proof->rva, proof->guard, sizeof(proof->guard))', 'if (!ThreadAllowed()) return ERROR_INVALID_THREAD_ID;', 'MH_CreateHook(')]
    if any(p < 0 for p in positions) or positions != sorted(positions): raise VerificationError('Growth knockdown hooks precede pinned/thread checks')
    for fragment in ('originalKnockdown(item, frame, output); Adjust(item, output);', 'originalDelta(item, frame, output); Adjust(item, output);',
        'knockdown_native::OwnerPawn', '*static_cast<const uintptr_t*>(item) != qualifiedVtable', 'owner.lookup(owner.context, pawn, &policy)',
        '*engineThreadId == boundThread', 'GetCurrentThreadId() == boundThread', 'Resolve(policy, Consumer::Knockdown, baseline, result)', 'Write(output, result);'):
        if fragment not in text: raise VerificationError('Growth original melee knockdown output guard missing: ' + fragment)
    if 'MH_ALL_HOOKS' in text or '3647b0' in text or re.search(r'memcpy\s*\(\s*(?:item|pawn)\b', text):
        raise VerificationError('Growth knockdown consumer writes original objects or scales target vulnerability')
    return len(rows), 2


def check_growth_kill_offsets(header, runtime, evidence, target_sha256):
    if evidence.get('schema') != 1 or evidence.get('target_sha256') != target_sha256 or evidence.get('abi') != 'void(void*, void*, uint8_t, uint8_t, uint8_t)':
        raise VerificationError('Growth original kill build/ABI differs')
    guards = {'Notification': '0x3d8aa0', 'ReflectedNotification': '0xb3a690', 'HumanEvent': '0xa59100',
        'NativeDeathCaller': '0x329060', 'TypeConversion': '0x334830', 'TypeEnum': '0xb5e920', 'EnumBuilder': '0x11b4d10'}
    rows = evidence.get('guards', [])
    actual = re.findall(r'HookSpec\s+(\w+)\s*=\s*\{(0x[0-9a-f]+),\s*\{([^}]*)\}\}', header)
    parsed = {name: (rva, ''.join(re.findall(r'0x([0-9a-f]{2})', guard))) for name, rva, guard in actual}
    if len(rows) != 7 or len(actual) != 7 or set(parsed) != set(guards): raise VerificationError('Growth original kill guard set differs')
    for row in rows:
        if row['rva'] != guards.get(row['symbol']) or parsed.get(row['symbol']) != (row['rva'], row['guard']) or ('&kill_native::' + row['symbol']) not in runtime:
            raise VerificationError('Growth original kill proof unguarded or changed: ' + row['symbol'])
    if evidence.get('fields') != {'Notified': '0xbd8', 'OriginalType': '0x868', 'Plague': '0xb88'} or 'Notified = 0xbd8;' not in header:
        raise VerificationError('Growth original kill notification fields differ')
    names = ['None', 'SlowZombie', 'FastZombie', 'Bloater', 'HumanTurnedZombie', 'Crawler', 'Screamer', 'Feral', 'Juggernaut', 'Count', 'EZombieType_MAX']
    if evidence.get('type_ordinals') != {name: index for index, name in enumerate(names)}: raise VerificationError('Growth original zombie type map differs')
    if any(evidence.get('scope', {}).get(name) is not False for name in ('runtime_verified', 'all_kill_sources_verified', 'persistent_killer_identity_verified')):
        raise VerificationError('Growth kill proof falsely claims live source coverage or persistent identity')
    text = COMMENT_RE.sub('', runtime)
    positions = [text.find(fragment) for fragment in ('sod2_native::PinnedImageFile(module, stat_native::ImageSha256)',
        'std::memcmp(image + proof->rva, proof->guard, sizeof(proof->guard))', 'if (!ThreadAllowed() || actors.Initialize()', 'MH_CreateHook(')]
    if any(p < 0 for p in positions) or positions != sorted(positions): raise VerificationError('Growth kill hook precedes build or actual-thread qualification')
    for fragment in ('*engineThreadId == boundThread', 'GetCurrentThreadId() == boundThread', 'owner->IdentifyPawn(killer, event.killer, event.killerCharacter)',
        'object_runtime::Capture(victim, event.victim)', 'original(victim, killer, style, type, plague);',
        'object_runtime::Matches(event.victim, victim)', 'count == Capacity', 'generation == std::numeric_limits<uint64_t>::max()',
        'ReadVictim(victim, event)', 'kill_native::OriginalType', 'kill_native::Plague',
        'queue[first].world != epoch || queue[first].sequence != sequence', 'epoch <= lastWorld', 'owner->Suspend();'):
        if fragment not in text: raise VerificationError('Growth attributed kill queue guard missing: ' + fragment)
    if text.find('original(victim, killer, style, type, plague);') > text.find('event.sequence = ++generation;'):
        raise VerificationError('Growth kill event is queued before original notification succeeds')
    if 'MH_ALL_HOOKS' in text or re.search(r'(?:WriteFile|Sleep|WaitForSingleObject|PostMessage|SendMessage|GetLocalPlayer)\s*\(', text):
        raise VerificationError('Growth original kill callback blocks, writes storage or substitutes the current player')
    return len(rows), 1


def check_growth_actor_source(header, runtime, evidence, target_sha256):
    if evidence.get('schema') != 1 or evidence.get('target_sha256') != target_sha256: raise VerificationError('Growth original actor source build differs')
    rows = evidence.get('guards', [])
    expected = {'PlayerEnclave':'0x3e4090','RosterCopy':'0x27bfb0','ControllerPawn':'0x1e29460','CharacterComponent':'0x1d4ba0',
        'PawnCharacter':'0x38dce0','ComponentCharacter':'0x1d4ec0','OwnerConsumer':'0x469750','CharacterClass':'0xa33310',
        'HumanClass':'0xa20010','ComponentClass':'0xa333a0','DeadFlag':'0x1d99c0','GamePlayMode':'0xabaa60','LocalId':'0x1d6770','RecordCopy':'0x1c40d0',
        'PawnRegistration':'0xa6ab20','PawnClassGetter':'0x898a40','PawnBaseClass':'0xa1fcf0'}
    actual = re.findall(r'HookSpec\s+(\w+)\s*=\s*\{(0x[0-9a-f]+),\s*\{([^}]*)\}\}', header)
    parsed = {name: (rva, ''.join(re.findall(r'0x([0-9a-f]{2})', guard))) for name,rva,guard in actual}
    if len(rows)!=17 or len(actual)!=17 or set(parsed)!=set(expected): raise VerificationError('Growth original actor source guard set differs')
    for row in rows:
        if row['rva']!=expected.get(row['symbol']) or parsed.get(row['symbol'])!=(row['rva'],row['guard']) or ('&actor_source_native::'+row['symbol']) not in runtime:
            raise VerificationError('Growth original actor source proof changed or unguarded: '+row['symbol'])
    fields = {'ObjectClass':'0x10','ClassSuper':'0x30','Roster':'0x398','ControllerPawn':'0x368','CharacterComponent':'0xe30',
        'ComponentOwner':'0xb8','ComponentCharacter':'0x190','PawnComponent':'0xba0','CharacterEnclave':'0xe28','CharacterRecord':'0x368',
        'RecordLocalId':'0x0','RecordNarrativeId':'0x8','RecordEntityId':'0x10','Dead':'0x408','GamePlayMode':'0xa7a'}
    if evidence.get('fields')!=fields or any(name+'Field = '+value+';' not in header for name,value in fields.items()):
        raise VerificationError('Growth original actor source fields differ')
    if any(evidence.get('scope',{}).get(name) is not False for name in ('runtime_verified','persistent_identity_verified','campaign_world_owner_verified')):
        raise VerificationError('Growth actor source proof falsely claims persistent identity or live campaign owner')
    text=COMMENT_RE.sub('',runtime)
    for fragment in ('GetCurrentThreadId() == thread && object_runtime::OnGameThread()', 'pawnCharacter(pawn) != character',
        'array.count > static_cast<int32_t>(Capacity)', 'object_runtime::Matches(result.componentToken, component)',
        'CharacterEnclaveField) != enclave', 'ComponentCharacterField) != expectedCharacter', 'PawnComponentField) != expectedComponent',
        'if (capturing || !context) return Status::Unavailable;', 'result = candidate; return Status::Ready;',
        'candidate.actors[i].pawn == candidate.actors[previous].pawn', 'characters[i] == characters[previous]', 'sod2_native::PinnedImageCached(module, stat_native::ImageSha256)',
        '&world_native::ResolveController', '&world_native::ControllerClass', 'controllerPawn(controller)', 'IsA(controller, controllerClass)',
        'candidate.controlledActor == NoControlledActor', 'PointerMatches(controller, actor_source_native::ControllerPawnField, possessed)',
        'if (!StillMatches(candidate.actors[i], enclave))', 'finalCount != candidate.count || finalCharacters != characters',
        'observed.candidate.entityId != actor.candidate.entityId', 'object_runtime::Matches(actor.componentToken, actor.component)', 'IsA(pawn, gameCharacterClass)'):
        if fragment not in text: raise VerificationError('Growth reciprocal actor snapshot guard missing: '+fragment)
    if 'MH_CreateHook' in text or re.search(r'(?:WriteProcessMemory|WriteFile|Sleep|WaitForSingleObject)\s*\(',text) or re.search(r'memcpy\s*\(\s*(?:character|component|pawn|enclave)\b',text):
        raise VerificationError('Growth actor source mutates game state or blocks its caller')
    return len(rows),len(fields)


def check_growth_campaign_source(header, runtime, evidence, target_sha256):
    if evidence.get('schema') != 1 or evidence.get('target_sha256') != target_sha256: raise VerificationError('Growth campaign source build differs')
    expected = {'GameMode':'0x3e1290','GameModeCast':'0x1c11f0','GameInstance':'0x409f20','ModeSelection':'0x40a6d0',
        'GameInstanceClass':'0xa33870','VanillaClass':'0xa23e90','ModeEnum':'0x8cb520','EnumBuilder':'0x11b4d10'}
    rows = evidence.get('guards', [])
    actual = re.findall(r'HookSpec\s+(\w+)\s*=\s*\{(0x[0-9a-f]+),\s*\{([^}]*)\}\}', header)
    parsed = {name:(rva,''.join(re.findall(r'0x([0-9a-f]{2})',guard))) for name,rva,guard in actual}
    if len(rows)!=8 or len(actual)!=8 or set(parsed)!=set(expected): raise VerificationError('Growth campaign source proof set differs')
    for row in rows:
        if row['rva']!=expected.get(row['symbol']) or parsed.get(row['symbol'])!=(row['rva'],row['guard']) or ('&campaign_source_native::'+row['symbol']) not in runtime:
            raise VerificationError('Growth campaign source proof changed or unguarded: '+row['symbol'])
    fields={'WorldGameMode':'0x110','WorldGameInstance':'0x140','ObjectClass':'0x10','ClassSuper':'0x30'}
    modes={'Vanilla':0,'Daybreak':1,'Heartland':2,'Chariot':3,'Num':4,'EGamePlayMode_MAX':5}
    if evidence.get('fields')!=fields or any(name+'Field = '+value+';' not in header for name,value in fields.items()): raise VerificationError('Growth actual world fields differ')
    if evidence.get('mode_ordinals')!=modes or any('Mode'+name+' = '+str(value)+';' not in header for name,value in modes.items()): raise VerificationError('Growth original gameplay mode ordinals differ')
    if any(evidence.get('scope',{}).get(name) is not False for name in ('runtime_verified','loading_state_verified','single_player_verified')):
        raise VerificationError('Growth campaign source falsely claims live loading or single-player eligibility')
    text=COMMENT_RE.sub('',runtime)
    for fragment in ('GetCurrentThreadId() == thread && object_runtime::OnGameThread()', 'sod2_native::PinnedImageCached(module, stat_native::ImageSha256)',
        'struct OptionalMode { uint8_t present = 0, value = 255; }', 'mode.present != 1 || mode.value >= campaign_source_native::ModeNum',
        'originalVanillaClass && mode.value == campaign_source_native::ModeVanilla', 'selectMode(candidate.gameInstance, &mode) != &mode',
        'object_runtime::Matches(candidate.gameModeToken, candidate.gameMode)', 'object_runtime::Matches(candidate.gameInstanceToken, candidate.gameInstance)',
        'bytes + campaign_source_native::WorldGameModeField', 'bytes + campaign_source_native::WorldGameInstanceField',
        'result = candidate; return Status::Ready;', 'if (!world || capturing) return Status::Unavailable;', 'depth < 128'):
        if fragment not in text: raise VerificationError('Growth campaign optional/lifetime guard missing: '+fragment)
    after_selection = text.split('selectMode(candidate.gameInstance, &mode)',1)[1].split('const bool originalVanillaClass',1)[0]
    for role in ('worldToken, world','gameModeToken, candidate.gameMode','gameInstanceToken, candidate.gameInstance'):
        if 'object_runtime::Matches(candidate.'+role+')' not in after_selection:
            raise VerificationError('Growth campaign source reads classes before checking callback-invalidated objects')
    if 'MH_CreateHook' in text or re.search(r'(?:WriteProcessMemory|WriteFile|Sleep|WaitForSingleObject)\s*\(',text) or re.search(r'memcpy\s*\(\s*(?:world|gameMode|gameInstance)\b',text):
        raise VerificationError('Growth campaign source mutates original state or blocks its caller')
    return len(rows),len(fields)


def check_growth_startup_authentication(header, frame, coordinator, consumers):
    expected_consumers={'GrowthObjectRuntime.cpp','GrowthStatRuntime.cpp','GrowthWorldRuntime.cpp','GrowthMovementRuntime.cpp',
        'GrowthRangedRuntime.cpp','GrowthRangedBindingRuntime.cpp','GrowthKnockdownRuntime.cpp','GrowthKillRuntime.cpp','GrowthActorSource.cpp','GrowthCampaignSource.cpp','GrowthLoadingScreenSource.cpp', 'GrowthPlayReadinessRuntime.cpp', 'GrowthVitalsRuntime.cpp'}
    if set(consumers)!=expected_consumers: raise VerificationError('Growth startup authentication consumer set differs')
    text = COMMENT_RE.sub('', header)
    for fragment in ('module != GetModuleHandleW(nullptr)', 'image_cache::state.load(std::memory_order_acquire) != 2',
        'std::memcmp(expected, image_cache::hash.data(), 64) == 0',
        'image_cache::state.compare_exchange_strong(state, 1, std::memory_order_acq_rel)',
        'image_cache::state.store(3, std::memory_order_release)', 'image_cache::state.store(2, std::memory_order_release)'):
        if fragment not in text: raise VerificationError('Growth immutable startup authentication guard missing: ' + fragment)
    cached = text.split('inline bool PinnedImageCached(', 1)[1].split('inline bool PinnedImageFile(', 1)[0]
    if re.search(r'(?:ReadFile|CreateFileW|ReadPinnedImageFile|Sleep|WaitForSingleObject)\s*\(', cached):
        raise VerificationError('Growth prepared-image lookup performs file I/O or waits')
    if 'sod2_native::PinnedImageFile(module, stat_native::ImageSha256)' not in frame:
        raise VerificationError('Growth frame startup no longer authenticates image before callbacks')
    at = coordinator.find('sod2_native::PinnedImageCached(GetModuleHandleW(nullptr), stat_native::ImageSha256)')
    if at < 0 or at > coordinator.find('object_runtime::EnsureBound(actualGameThread)'):
        raise VerificationError('Growth coordinator may hash game image during a native tick')
    for name, source in consumers.items():
        before = source.find('sod2_native::PinnedImageCached(module, stat_native::ImageSha256)')
        after = source.find('sod2_native::PinnedImageFile(module, stat_native::ImageSha256)')
        if before < 0 or after < 0 or before > after: raise VerificationError('Growth game-thread component lacks prewarmed image proof: ' + name)
    return True


def check_growth_owner_wiring(policy_header, policies, coordinator, binding, ranged_header):
    policy_text = COMMENT_RE.sub('', policies)
    for fragment in ('ActorCapacity = 128, StatsCapacity = 512', 'Store(const Store&) = delete',
                     'Store& operator=(Store&&) = delete', 'std::atomic<DWORD> thread_{0}'):
        if fragment not in policy_header: raise VerificationError('Growth bounded owner store guard missing: ' + fragment)
    for fragment in ('object_runtime::Matches(actor.characterToken, actor.character)',
                     'object_runtime::Matches(binding.statsToken, binding.stats)', 'generation_',
                     'Result::Conflict', 'actor->policy = policy;', 'RemoveStats(handle); actor->pawn = pawn;',
                     'if (!owner.value) return Result::Missing;'):
        if fragment not in policy_text: raise VerificationError('Growth incarnation/ownership check missing: ' + fragment)
    callback_text = policy_text[policy_text.index('bool __cdecl Store::Character'):]
    if 'object_runtime::Capture(' in callback_text or 'object_runtime::Resolve(' in callback_text:
        raise VerificationError('Growth output callback allocates or calls original object helpers')
    text = COMMENT_RE.sub('', coordinator)
    for fragment in ('object_runtime::EnsureBound(actualGameThread)', 'campaign_source::EnsureBound(thread)', 'actor_source::EnsureBound(thread)', 'GetCurrentThreadId() != actualGameThread',
                     'store.BoundCharacter(actor, character)', 'stat.lookup = actor_policies::Store::Character',
                     'movement.lookup = actor_policies::Store::Pawn', 'ranged.lookup = actor_policies::Store::Stats',
                     'ranged_binding_runtime::Install(thread, store)', 'GET_MODULE_HANDLE_EX_FLAG_PIN',
                     'knockdown_runtime::Install(movement)',
                     '::melee::clock::RegisterExport', '::melee::clock::UnregisterExport', '::melee::clock::QueryExport',
                     'store.VisitCharacters(Refresh, nullptr)', 'old.suppressPrimarySkills != policy.suppressPrimarySkills',
                     'queryClock(pawn, category, &multiplier)', 'if (Healthy()) return true;',
                     '!campaign_source::Faults()', '!actor_source::Faults()',
                     'actor_source::Capture(context, result)', 'campaign_source::Capture(world, result)',
                     'status == campaign_source::Status::Unavailable || !result.campaign'):
        if fragment not in text: raise VerificationError('Growth consumer coordinator guard missing: ' + fragment)
    if 'MH_CreateHook' in text or 'LoadLibrary' in text:
        raise VerificationError('Growth coordinator competes with the sole melee host or silently loads a host')
    text = COMMENT_RE.sub('', binding)
    for fragment in ('using Lookup = void(__fastcall*)(void*, void*, void**)', 'originalRebuild(holder); Observe(holder);',
                     'originalLookup(holder, frame, output);', 'SameOutput(holder, output)',
                     'owner->ObserveStats(stats, pawn)', 'ranged_native::HolderStats', 'ranged_native::HolderPawn',
                     '*static_cast<const uintptr_t*>(stats) == qualifiedVtable', '*engineThreadId == boundThread',
                     'GetCurrentThreadId() == boundThread', 'owner->ClearStats()',
                     '&ranged_native::RangedStatsLookup', '&ranged_native::RangedStatsLookupLeaf'):
        if fragment not in text: raise VerificationError('Growth original ranged-owner producer guard missing: ' + fragment)
    if 'MH_ALL_HOOKS' in text or 'memcpy(output' in text or re.search(r'\*output\s*=(?!=)', text):
        raise VerificationError('Growth ranged owner producer changes other hooks or original lookup output')
    if 'HolderStats = 0x28;' not in ranged_header or 'HolderPawn = 0x60;' not in ranged_header:
        raise VerificationError('Growth original ranged holder fields differ')
    return True


def check_growth_service_reuse(sources):
    expected = {'GrowthObjectRuntime.cpp', 'GrowthActorSource.cpp', 'GrowthCampaignSource.cpp'}
    if set(sources) != expected: raise VerificationError('Growth shared service reuse set differs')
    for name, source in sources.items():
        text = COMMENT_RE.sub('', source)
        if 'DWORD EnsureBound(DWORD actualGameThread)' not in text: raise VerificationError('Growth shared service lacks checked reuse')
        reuse = text.split('DWORD EnsureBound(DWORD actualGameThread)', 1)[1].split('\n}', 1)[0]
        for fragment in ('GetCurrentThreadId() != actualGameThread', 'return ERROR_INVALID_THREAD_ID;',
            '!ready.load(std::memory_order_acquire)', 'return Bind(actualGameThread);', 'return ERROR_INVALID_STATE;',
            'return ERROR_BUSY;', 'return ERROR_SUCCESS;'):
            if fragment not in reuse: raise VerificationError('Growth service reuse guard missing: ' + fragment)
        health = ('actualGameThread != boundThread', '!OnGameThread()', 'if (resolving)') if name == 'GrowthObjectRuntime.cpp' else (
            'actualGameThread != thread', 'failed.load(std::memory_order_acquire)', '!Thread()', 'if (capturing)')
        if any(fragment not in reuse for fragment in health): raise VerificationError('Growth reuse bypasses service health or reentrancy')
        if re.search(r'(?:\.store|\.exchange|Resume|original\w*|Sleep|WaitForSingleObject|PinnedImageFile)\s*\(', reuse):
            raise VerificationError('Growth reuse mutates binding, resumes, invokes game work or waits')
    return len(sources)


def check_growth_damage_offsets(header, runtime, evidence, target_sha256):
    if evidence.get('schema') != 1 or evidence.get('target_sha256') != target_sha256 or evidence.get('abi') != 'void(void*, float, float*)':
        raise VerificationError('Growth health-adjustment build/ABI differs')
    rows = evidence.get('guards', [])
    actual = re.findall(r'HookSpec\s+(\w+)\s*=\s*\{(0x[0-9a-f]+),\s*\{([^}]*)\}\}', header)
    parsed = {name: (rva, ''.join(re.findall(r'0x([0-9a-f]{2})', guard))) for name, rva, guard in actual}
    if len(rows) != 3 or len(actual) != 3 or set(parsed) != {'HealthAdjustment', 'HealthAdjustmentWrapper', 'HealthAdjustmentOutput'}:
        raise VerificationError('Growth health-adjustment proof catalog differs')
    for row in rows:
        if parsed.get(row['symbol']) != (row['rva'], row['guard']) or ('&damage_native::' + row['symbol']) not in runtime:
            raise VerificationError('Growth health-adjustment proof is not guarded: ' + row['symbol'])
    fields = dict(re.findall(r'uintptr_t\s+(\w+)\s*=\s*(0x[0-9a-f]+);', header))
    if fields != {'ComponentCharacter': '0x190'} or evidence.get('fields') != fields or evidence.get('enum_mapping') != {'GlobalDamageMultiplier': 141}:
        raise VerificationError('Growth health-adjustment character/modifier layout differs')
    if evidence.get('hook') != 'HealthAdjustment' or any(evidence.get('scope', {}).get(name) is not False for name in (
        'runtime_verified', 'all_ordinary_damage_paths_verified', 'death_interception_verified')):
        raise VerificationError('Growth health-adjustment static proof claims full death/damage coverage')
    text = COMMENT_RE.sub('', runtime)
    specs = re.search(r'HookSpec\* specs\[\]\s*=\s*\{([^}]*)\}', text)
    if specs is None or '&damage_native::HealthAdjustment' not in specs.group(1):
        raise VerificationError('Growth health-adjustment is absent from the consumer hook list')
    for fragment in ('using HealthAdjustment = void(__fastcall*)(void*, float, float*);',
        'originalAdjustment(component, input, output);', 'if (!std::isfinite(baseline) || baseline >= 0) return false;',
        'damage_native::ComponentCharacter', 'const float adjusted = -Resolved(character, Consumer::OrdinaryDamage, -baseline);',
        'if (adjusted != baseline) WriteHealthAdjustment(output, adjusted);', 'reinterpret_cast<void**>(&originalAdjustment)'):
        if fragment not in text: raise VerificationError('Growth health-adjustment original output isolation missing: ' + fragment)
    body = re.search(r'void __fastcall AdjustHealth\([^}]+\}', text)
    if body is None or body.group(0).find('originalAdjustment(') > body.group(0).find('ReadHealthAdjustment('):
        raise VerificationError('Growth health adjustment precedes original background/community calculation')
    return len(rows), len(fields)


def check_growth_movement_offsets(header, runtime, evidence, target_sha256):
    if evidence.get('schema') != 1 or evidence.get('target_sha256') != target_sha256 or evidence.get('abi') != 'float(void*)':
        raise VerificationError('Growth movement consumer build/ABI differs')
    rows = evidence.get('guards', [])
    actual = re.findall(r'HookSpec\s+(\w+)\s*=\s*\{(0x[0-9a-f]+),\s*\{([^}]*)\}\}', header)
    parsed = {name: (rva, ''.join(re.findall(r'0x([0-9a-f]{2})', guard))) for name, rva, guard in actual}
    expected = {'MaxSpeed', 'IsCrouching', 'MovementClass', 'MovementConstructor', 'SpeedWrapper',
                'CrouchWrapper', 'PhysicsSpeedCall', 'ModifiedMaxSpeed', 'MovementEnum'}
    if len(rows) != 9 or len(actual) != 9 or set(parsed) != expected:
        raise VerificationError('Growth movement consumer proof catalog differs')
    for row in rows:
        if parsed.get(row['symbol']) != (row['rva'], row['guard']) or ('&movement_native::' + row['symbol']) not in runtime:
            raise VerificationError('Growth movement proof is not guarded: ' + row['symbol'])
    fields = {name: int(value, 16) for name, value in re.findall(r'uintptr_t\s+(\w+)\s*=\s*(0x[0-9a-f]+);', header)}
    expected_fields = {'MovementOwner': 0x190, 'MovementMode': 0x1b0, 'MovementVtable': 0x34c00b8,
                       'MaxSpeedSlot': 0x368, 'ModifiedMaxSpeedSlot': 0x380, 'IsCrouchingSlot': 0x4c0}
    slots = {'MaxSpeed': {'slot': '0x368', 'target': '0x1c1fc70'}, 'ModifiedMaxSpeed': {'slot': '0x380', 'target': '0x1c4f8f0'},
             'IsCrouching': {'slot': '0x4c0', 'target': '0x1c21a30'}}
    if fields != expected_fields or evidence.get('fields') != {'MovementOwner': '0x190', 'MovementMode': '0x1b0'} or evidence.get('vtable') != '0x34c00b8' or evidence.get('vtable_slots') != slots:
        raise VerificationError('Growth movement owner/mode/vtable layout differs')
    enum = {'MOVE_None': 0, 'MOVE_Walking': 1, 'MOVE_NavWalking': 2, 'MOVE_Falling': 3, 'MOVE_Swimming': 4,
            'MOVE_Flying': 5, 'MOVE_Custom': 6, 'MOVE_MAX': 7}
    if evidence.get('hook') != 'MaxSpeed' or evidence.get('ground_modes') != [1, 2] or evidence.get('enum_mapping') != enum:
        raise VerificationError('Growth movement ground modes or single final consumer changed')
    for name in ('MOVE_Walking', 'MOVE_NavWalking'):
        if ('uint8_t ' + name + ' = ' + str(enum[name]) + ';') not in header:
            raise VerificationError('Growth movement enum header disagrees with native mapping')
    if evidence.get('jump_table') != ['0x1c1fc94'] * 3 + ['0x1c1fc9d', '0x1c1fca6', '0x1c1fcaf']:
        raise VerificationError('Growth movement speed mode jump table differs')
    if any(evidence.get('scope', {}).get(name) is not False for name in ('runtime_verified', 'all_movement_paths_verified')):
        raise VerificationError('Growth movement static proof falsely claims complete live locomotion')
    text = COMMENT_RE.sub('', runtime)
    positions = [text.find(fragment) for fragment in ('sod2_native::PinnedImageFile(module, stat_native::ImageSha256)',
        'std::memcmp(image + proof->rva, proof->guard, sizeof(proof->guard))',
        'if (!ThreadAllowed()) return ERROR_INVALID_THREAD_ID;', 'MH_CreateHook(')]
    if any(p < 0 for p in positions) or positions != sorted(positions):
        raise VerificationError('Growth movement installs before pinned consumer/thread validation')
    for fragment in ('*engineThreadId == boundThread', 'GetCurrentThreadId() == boundThread',
        '*reinterpret_cast<const uintptr_t*>(bytes) != qualifiedVtable',
        'mode != movement_native::MOVE_Walking && mode != movement_native::MOVE_NavWalking',
        'const float baseline = originalSpeed(component);', 'const bool crouching = originalCrouching(component);',
        'crouching ? Consumer::SneakSpeed : Consumer::GroundSpeed, baseline, result',
        '!ThreadAllowed() || resolving', 'owner.lookup(owner.context, pawn, &policy)',
        'if (ready.load(std::memory_order_acquire) && !failed.load(std::memory_order_acquire))'):
        if fragment not in text: raise VerificationError('Growth movement actor/single-composition guard missing: ' + fragment)
    if 'MH_ALL_HOOKS' in text or len(re.findall(r'\bMH_CreateHook\(', text)) != 1:
        raise VerificationError('Growth movement duplicates consumers or changes unrelated hook ownership')
    return len(rows), len(evidence['fields'])


def check_shared_melee_clock(header, runtime, growth_layer):
    if 'Version = 1;' not in header or 'Capacity = 8;' not in header:
        raise VerificationError('Shared melee clock ABI/version or bounded owner capacity changed')
    if 'sizeof(Contribution) == 16 && sizeof(Registration) == 40 && offsetof(Registration, lookup) == 24' not in header:
        raise VerificationError('Shared melee clock x64 ABI has no fixed layout check')
    for name in ('SoD2MeleeRegisterClockV1', 'SoD2MeleeUnregisterClockV1', 'SoD2MeleeQueryClockV1'):
        if name not in EXPORT_RE.findall(COMMENT_RE.sub('', runtime)):
            raise VerificationError('Shared melee clock native export missing: ' + name)
    for constant, name in (('RegisterExport', 'SoD2MeleeRegisterClockV1'), ('UnregisterExport', 'SoD2MeleeUnregisterClockV1'), ('QueryExport', 'SoD2MeleeQueryClockV1')):
        if 'char ' + constant + '[] = "' + name + '";' not in header:
            raise VerificationError('Shared melee export name differs from its host: ' + constant)
    text = COMMENT_RE.sub('', runtime)
    if 'MH_ALL_HOOKS' in text or 'MH_ERROR_ALREADY_INITIALIZED' not in text:
        raise VerificationError('Shared melee host interferes with another hook owner')
    for fragment in ('ClockThreadAllowed()', '*engineThreadId == boundThread', 'GetCurrentThreadId() == boundThread',
                     'sod2_native::PinnedImageFile(GetModuleHandleW(nullptr), growth::stat_native::ImageSha256)',
                     '&growth::thread_native::AssertThread3', 'clockLayers.Add(*registration, *handle)',
                     'clockLayers.Remove(handle)', 'clockLayers.Resolve(', 'if (!attemptedEnable) MH_RemoveHook(target);'):
        if fragment not in text: raise VerificationError('Shared melee consumer ownership check missing: ' + fragment)
    for fragment in ('registration.ownerLow', 'ERROR_ALREADY_EXISTS', 'ERROR_INVALID_HANDLE',
                     'logarithm += std::log(contribution.multiplier)', 'ceiling = std::fmin(ceiling, contribution.ceiling)',
                     'if (!applied) return true;', 'if (resolving) return ERROR_BUSY;'):
        if fragment not in COMMENT_RE.sub('', header): raise VerificationError('Shared melee composition/registration guard missing: ' + fragment)
    if 'policy.attackCeiling' not in growth_layer or '* policy.bloodAttack' not in growth_layer or 'Resolve(policy, Consumer::MeleeClock' in COMMENT_RE.sub('', growth_layer):
        raise VerificationError('Growth melee contribution is capped before shared composition')
    return 3, 8


def check_native_entry_points(base, native_root):
    exports = set()
    for path in sorted(native_files(native_root, '*.cpp')):
        exports.update(EXPORT_RE.findall(COMMENT_RE.sub('', path.read_text(encoding='utf-8'))))
    if not exports:
        raise VerificationError('原生组件没有导出入口点')
    requested = set()
    # A release keeps the plugin sources under source/ and only ships built
    # DLLs in Plugins/, so both layouts have to be searched.
    sources = sorted(base.glob('Plugins/*/*.cs')) + sorted(base.glob('source/Plugins/*/*.cs')) + sorted(base.glob('Core/**/*.cs')) + sorted(base.glob('source/Core/**/*.cs'))
    for path in sources:
        if path.parent.name != 'Core':
            for entry in MANAGED_ENTRY_RE.findall(path.read_text(encoding='utf-8')):
                requested.add((path.name, entry))
        for entry in MANAGED_DIRECT_ENTRY_RE.findall(path.read_text(encoding='utf-8')):
            requested.add((path.name, entry))
    if not requested:
        raise VerificationError('没有找到 C# 侧的原生模块入口点调用')
    for name, entry in sorted(requested):
        if entry not in exports:
            raise VerificationError('%s 请求原生入口点 %s，但原生组件没有导出它' % (name, entry))
    return len(requested), len(exports)


def check_mcm_record(base, structs):
    header = locate(base, 'Native/src/Mcm/McmProtocol.h').read_text(encoding='utf-8')
    fields = {name: int(value) for name, value in MCM_FIELD_RE.findall(header)}
    size_match = MCM_SIZE_RE.search(header)
    if not fields or size_match is None:
        raise VerificationError('McmProtocol.h 缺少 State 布局 static_assert')
    records = [structure for structure in structs.get('structures', [])
               if str(structure.get('id', '')).startswith('mcm-ipc-state')]
    if len(records) != 1:
        raise VerificationError('逆向资料库必须只有一条 MCM 状态记录')
    record = records[0]
    if int(record.get('size')) != int(size_match.group(1)):
        raise VerificationError(
            '资料库的 %s 大小为 %s，与 McmProtocol.h 的 sizeof(State)=%s 不一致'
            % (record['id'], record.get('size'), size_match.group(1)))
    checked = 0
    for field in record.get('fields', []):
        name = str(field.get('name', ''))
        token = str(field.get('offset', ''))
        if name not in fields or not re.fullmatch(r'0x[0-9A-Fa-f]+', token):
            continue
        if int(token, 16) != fields[name]:
            raise VerificationError(
                '资料库 %s 的 %s 偏移 %s 与 McmProtocol.h 的 %s 不一致'
                % (record['id'], name, token, fields[name]))
        checked += 1
    if checked == 0:
        raise VerificationError('资料库的 MCM 状态记录没有可核对的字段名')
    return record['id'], checked


def main():
    base = Path(__file__).resolve().parents[2]
    native_root = locate_native(base)
    header_name = 'MeleeOffsets.h'
    header_path = locate(base, 'GameApi/native/' + header_name)
    if not header_path.is_file():
        raise VerificationError('找不到 Native/' + header_name)
    build, structs, functions = load_database(base)

    native_settings_reports = sorted((base / 'Research').glob('*/*/native-settings-mcm-bridge.json'))
    if base.joinpath('source', 'Research').is_dir():
        native_settings_reports += sorted((base / 'source' / 'Research').glob('*/*/native-settings-mcm-bridge.json'))
    if len(native_settings_reports) != 1:
        raise VerificationError('必须有且只有一份固定版本的 Iggy RVA 证据')
    iggy_evidence = json.loads(native_settings_reports[0].read_text(encoding='utf-8'))
    iggy_header = native_root / 'src/Mcm/NativeSettingsIggy.h'
    if not iggy_header.is_file():
        raise VerificationError('找不到 Native/src/Mcm/NativeSettingsIggy.h')
    guarded_iggy_rvas = check_guarded_iggy_rvas_text(
        iggy_header.read_text(encoding='utf-8'), iggy_evidence)

    header_text = header_path.read_text(encoding='utf-8')
    declared, offsets = check_offset_constants(header_text, build, structs, functions)
    check_no_raw_offsets(native_root, header_name, guarded_iggy_rvas)
    check_constants_are_used(declared, native_root, header_name)
    entry_points, exports = check_native_entry_points(base, native_root)
    record, mcm_fields = check_mcm_record(base, structs)

    growth_evidence = json.loads(locate(base, 'Research/StateOfDecay2/' + build + '/growth-stat-consumers.json').read_text(encoding='utf-8'))
    growth_hooks, growth_stats = check_growth_stat_offsets(
        locate(base, 'GameApi/native/GrowthStatOffsets.h').read_text(encoding='utf-8'),
        locate(base, 'Native/src/Growth/GrowthStatRuntime.cpp').read_text(encoding='utf-8'), growth_evidence)
    skill_evidence = json.loads(locate(base, 'Research/StateOfDecay2/' + build + '/growth-skill-consumers.json').read_text(encoding='utf-8'))
    skill_guards, skill_fields, primary_definitions = check_growth_skill_offsets(
        locate(base, 'GameApi/native/GrowthSkillOffsets.h').read_text(encoding='utf-8'),
        locate(base, 'Native/src/Growth/GrowthStatRuntime.cpp').read_text(encoding='utf-8'), skill_evidence, growth_evidence['target_sha256'])
    fatigue_evidence = json.loads(locate(base, 'Research/StateOfDecay2/' + build + '/growth-fatigue-consumers.json').read_text(encoding='utf-8'))
    fatigue_guards, fatigue_fields = check_growth_fatigue_offsets(
        locate(base, 'GameApi/native/GrowthFatigueOffsets.h').read_text(encoding='utf-8'),
        locate(base, 'Native/src/Growth/GrowthStatRuntime.cpp').read_text(encoding='utf-8'), fatigue_evidence, growth_evidence['target_sha256'])
    cache_evidence = json.loads(locate(base, 'Research/StateOfDecay2/' + build + '/growth-skill-cache.json').read_text(encoding='utf-8'))
    cache_guards, cache_fields = check_growth_skill_cache_offsets(
        locate(base, 'GameApi/native/GrowthSkillCacheOffsets.h').read_text(encoding='utf-8'),
        locate(base, 'Native/src/Growth/GrowthStatRuntime.cpp').read_text(encoding='utf-8'), cache_evidence, growth_evidence['target_sha256'])
    thread_evidence = json.loads(locate(base, 'Research/StateOfDecay2/' + build + '/growth-game-thread.json').read_text(encoding='utf-8'))
    thread_guards, thread_globals = check_growth_thread_offsets(
        locate(base, 'GameApi/native/GrowthThreadOffsets.h').read_text(encoding='utf-8'),
        locate(base, 'Native/src/Growth/GrowthStatRuntime.cpp').read_text(encoding='utf-8'), thread_evidence, growth_evidence['target_sha256'])
    world_evidence = json.loads(locate(base, 'Research/StateOfDecay2/' + build + '/growth-world-runtime.json').read_text(encoding='utf-8'))
    world_guards, world_fields = check_growth_world_offsets(
        locate(base, 'GameApi/native/GrowthWorldOffsets.h').read_text(encoding='utf-8'),
        locate(base, 'Native/src/Growth/GrowthWorldRuntime.cpp').read_text(encoding='utf-8'), world_evidence, growth_evidence['target_sha256'])
    frame_evidence = json.loads(locate(base, 'Research/StateOfDecay2/' + build + '/growth-frame-source.json').read_text(encoding='utf-8'))
    frame_guards, frame_callers = check_growth_frame_offsets(
        locate(base, 'GameApi/native/GrowthFrameOffsets.h').read_text(encoding='utf-8'),
        locate(base, 'Native/src/Growth/GrowthFrameRuntime.cpp').read_text(encoding='utf-8'), frame_evidence, growth_evidence['target_sha256'])
    infection_evidence = json.loads(locate(base, 'Research/StateOfDecay2/' + build + '/growth-infection-consumers.json').read_text(encoding='utf-8'))
    infection_guards, infection_hooks = check_growth_infection_offsets(
        locate(base, 'GameApi/native/GrowthInfectionOffsets.h').read_text(encoding='utf-8'),
        locate(base, 'Native/src/Growth/GrowthStatRuntime.cpp').read_text(encoding='utf-8'), infection_evidence, growth_evidence['target_sha256'])
    clock_exports, clock_capacity = check_shared_melee_clock(
        locate(base, 'Native/src/Shared/SharedMeleeClock.h').read_text(encoding='utf-8'),
        locate(base, 'Native/src/Melee/MeleeNative.cpp').read_text(encoding='utf-8'),
        locate(base, 'Native/src/Growth/GrowthMeleeClockLayer.h').read_text(encoding='utf-8'))
    movement_evidence = json.loads(locate(base, 'Research/StateOfDecay2/' + build + '/growth-movement-consumers.json').read_text(encoding='utf-8'))
    movement_guards, movement_fields = check_growth_movement_offsets(
        locate(base, 'GameApi/native/GrowthMovementOffsets.h').read_text(encoding='utf-8'),
        locate(base, 'Native/src/Growth/GrowthMovementRuntime.cpp').read_text(encoding='utf-8'), movement_evidence, growth_evidence['target_sha256'])
    damage_evidence = json.loads(locate(base, 'Research/StateOfDecay2/' + build + '/growth-damage-consumer.json').read_text(encoding='utf-8'))
    damage_guards, damage_fields = check_growth_damage_offsets(
        locate(base, 'GameApi/native/GrowthDamageOffsets.h').read_text(encoding='utf-8'),
        locate(base, 'Native/src/Growth/GrowthStatRuntime.cpp').read_text(encoding='utf-8'), damage_evidence, growth_evidence['target_sha256'])
    ranged_evidence = json.loads(locate(base, 'Research/StateOfDecay2/' + build + '/growth-ranged-consumers.json').read_text(encoding='utf-8'))
    ranged_guards, ranged_hooks = check_growth_ranged_offsets(
        locate(base, 'GameApi/native/GrowthRangedOffsets.h').read_text(encoding='utf-8'),
        locate(base, 'Native/src/Growth/GrowthRangedRuntime.cpp').read_text(encoding='utf-8'), ranged_evidence, growth_evidence['target_sha256'])
    object_evidence = json.loads(locate(base, 'Research/StateOfDecay2/' + build + '/growth-object-lifetime.json').read_text(encoding='utf-8'))
    object_guards, object_fields = check_growth_object_offsets(
        locate(base, 'GameApi/native/GrowthObjectOffsets.h').read_text(encoding='utf-8'),
        locate(base, 'Native/src/Growth/GrowthObjectRuntime.cpp').read_text(encoding='utf-8'), object_evidence, growth_evidence['target_sha256'])
    check_growth_owner_wiring(*(locate(base, 'Native/' + name).read_text(encoding='utf-8') for name in
        ('GrowthActorPolicies.h', 'GrowthActorPolicies.cpp', 'GrowthConsumerRuntime.cpp', 'GrowthRangedBindingRuntime.cpp', 'GrowthRangedOffsets.h')))
    check_growth_service_reuse({name: locate(base, 'Native/' + name).read_text(encoding='utf-8') for name in
        ('GrowthObjectRuntime.cpp', 'GrowthActorSource.cpp', 'GrowthCampaignSource.cpp')})
    knockdown_evidence = json.loads(locate(base, 'Research/StateOfDecay2/' + build + '/growth-knockdown-consumers.json').read_text(encoding='utf-8'))
    knockdown_guards, knockdown_hooks = check_growth_knockdown_offsets(
        locate(base, 'GameApi/native/GrowthKnockdownOffsets.h').read_text(encoding='utf-8'),
        locate(base, 'Native/src/Growth/GrowthKnockdownRuntime.cpp').read_text(encoding='utf-8'), knockdown_evidence, growth_evidence['target_sha256'])
    kill_evidence = json.loads(locate(base, 'Research/StateOfDecay2/' + build + '/growth-kill-source.json').read_text(encoding='utf-8'))
    kill_guards, kill_hooks = check_growth_kill_offsets(
        locate(base, 'GameApi/native/GrowthKillOffsets.h').read_text(encoding='utf-8'),
        locate(base, 'Native/src/Growth/GrowthKillRuntime.cpp').read_text(encoding='utf-8'), kill_evidence, growth_evidence['target_sha256'])
    check_growth_startup_authentication(
        locate(base, 'Native/src/Shared/PinnedImage.h').read_text(encoding='utf-8'),
        locate(base, 'Native/src/Growth/GrowthFrameRuntime.cpp').read_text(encoding='utf-8'),
        locate(base, 'Native/src/Growth/GrowthConsumerRuntime.cpp').read_text(encoding='utf-8'),
        {name: locate(base, 'Native/' + name).read_text(encoding='utf-8') for name in
        ('GrowthObjectRuntime.cpp', 'GrowthStatRuntime.cpp', 'GrowthWorldRuntime.cpp', 'GrowthMovementRuntime.cpp',
         'GrowthRangedRuntime.cpp', 'GrowthRangedBindingRuntime.cpp', 'GrowthKnockdownRuntime.cpp', 'GrowthKillRuntime.cpp', 'GrowthActorSource.cpp', 'GrowthCampaignSource.cpp', 'GrowthLoadingScreenSource.cpp', 'GrowthPlayReadinessRuntime.cpp', 'GrowthVitalsRuntime.cpp')})
    actor_source_evidence = json.loads(locate(base, 'Research/StateOfDecay2/' + build + '/growth-actor-source.json').read_text(encoding='utf-8'))
    actor_source_guards, actor_source_fields = check_growth_actor_source(
        locate(base, 'GameApi/native/GrowthActorSourceOffsets.h').read_text(encoding='utf-8'),
        locate(base, 'Native/src/Growth/GrowthActorSource.cpp').read_text(encoding='utf-8'), actor_source_evidence, growth_evidence['target_sha256'])
    campaign_evidence = json.loads(locate(base, 'Research/StateOfDecay2/' + build + '/growth-campaign-source.json').read_text(encoding='utf-8'))
    campaign_guards, campaign_fields = check_growth_campaign_source(
        locate(base, 'GameApi/native/GrowthCampaignSourceOffsets.h').read_text(encoding='utf-8'),
        locate(base, 'Native/src/Growth/GrowthCampaignSource.cpp').read_text(encoding='utf-8'), campaign_evidence, growth_evidence['target_sha256'])
    from Research.tools.Growth.validate_growth_loading_screen_source import validate_report as validate_loading_screen
    loading_guards = validate_loading_screen(
        json.loads(locate(base, 'Research/StateOfDecay2/' + build + '/growth-loading-screen-source.json').read_text(encoding='utf-8')),
        growth_evidence['target_sha256'], locate(base, 'GameApi/native/GrowthLoadingScreenOffsets.h').read_text(encoding='utf-8'),
        locate(base, 'Native/src/Growth/GrowthLoadingScreenSource.cpp').read_text(encoding='utf-8'))
    print('PASS: %d original loading-screen lifetime guards; screen absence does not establish world readiness' % loading_guards)
    from Research.tools.Growth.validate_growth_play_readiness import validate_native as validate_play_readiness
    readiness_guards = validate_play_readiness(
        json.loads(locate(base, 'Research/StateOfDecay2/' + build + '/growth-play-readiness-flow.json').read_text(encoding='utf-8')),
        locate(base, 'GameApi/native/GrowthPlayReadinessOffsets.h').read_text(encoding='utf-8'),
        locate(base, 'Native/src/Growth/GrowthPlayReadinessRuntime.cpp').read_text(encoding='utf-8'), growth_evidence['target_sha256'])
    print('PASS: %d original play-readiness guards; observation never speculatively invokes the mutating predicate' % readiness_guards)
    from Research.tools.Growth.validate_growth_vitals_runtime import validate_report as validate_vitals_runtime
    vitals_guards = validate_vitals_runtime(
        json.loads(locate(base, 'Research/StateOfDecay2/' + build + '/growth-vitals-runtime.json').read_text(encoding='utf-8')),
        growth_evidence['target_sha256'], locate(base, 'GameApi/native/GrowthVitalsOffsets.h').read_text(encoding='utf-8'),
        locate(base, 'Native/src/Growth/GrowthVitalsRuntime.cpp').read_text(encoding='utf-8'), actor_source_evidence)
    print('PASS: %d original vitals recovery guards; death/cache ordering remains gated' % vitals_guards)
    target = json.loads(locate(base, 'Research/StateOfDecay2/' + build + '/target.json').read_text(encoding='utf-8'))
    if target['sha256'] != growth_evidence['target_sha256']:
        raise VerificationError('Growth stat derivation differs from the repository target')

    print('PASS: build %s records %d native offsets (%d constants), %d module entry points '
          'across %d exports, and the %s record matches the ABI header (%d fields)'
          % (build, offsets, len(declared), entry_points, exports, record, mcm_fields))
    print('PASS: %d growth consumer guards and %d stat enum values match pinned derivation; live gates remain closed' % (growth_hooks, growth_stats))
    print('PASS: %d skill hook/helper guards and %d fields match evidence for %d primary definitions; fifth skills excluded' % (skill_guards, skill_fields, primary_definitions))
    print('PASS: %d fatigue hook/helper guards and %d field match pinned derivation; complete-clear gate remains closed' % (fatigue_guards, fatigue_fields))
    print('PASS: %d skill cache guards and %d fields match pinned derivation; shared provider types remain isolated' % (cache_guards, cache_fields))
    print('PASS: %d engine thread proof guards and %d globals match original initialization/assertions; bootstrap still gated' % (thread_guards, thread_globals))
    print('PASS: %d world clock/pause guards and %d controller fields match original consumers; live frame/UI gates remain closed' % (world_guards, world_fields))
    print('PASS: %d LevelTick producer/caller guards and %d native callers match evidence; world ownership remains gated' % (frame_guards, frame_callers))
    print('PASS: %d infection/countdown proof guards and %d incoming-amount hook match evidence; disease countdown remains original' % (infection_guards, infection_hooks))
    print('PASS: %d shared melee clock exports and %d bounded owner slots; growth combines before the final ceiling' % (clock_exports, clock_capacity))
    print('PASS: %d movement consumer guards and %d owner/mode fields; actor speed uses one final multiplier' % (movement_guards, movement_fields))
    print('PASS: %d health-adjustment guards and %d character field; only original final negative health output is reduced' % (damage_guards, damage_fields))
    print('PASS: %d ranged type/owner/output guards and %d reflected getters; direct native paths and live ownership remain gated' % (ranged_guards, ranged_hooks))
    print('PASS: %d original weak object guards and %d fields; incarnation tokens are not persistent survivor identities' % (object_guards, object_fields))
    print('PASS: %d melee-item knockdown guards and %d output hooks; target immunity and close-combat paths remain gated' % (knockdown_guards, knockdown_hooks))
    print('PASS: %d original kill guards and %d notification hook; complete source coverage and persistent identity remain gated' % (kill_guards, kill_hooks))
    print('PASS: %d original community actor guards and %d fields; reciprocal live roles are separate from persistent identity' % (actor_source_guards, actor_source_fields))
    print('PASS: %d original campaign guards and %d world fields; optional mode is required and loading remains gated' % (campaign_guards, campaign_fields))


if __name__ == '__main__':
    try:
        main()
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError, VerificationError) as error:
        raise SystemExit('FAIL: ' + str(error))
