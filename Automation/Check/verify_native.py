"""Keep the native components tied to the research database and to C#.

Game-version offsets live in exactly one place, ``Native/MeleeOffsets.h``, and
every entry names the record it was read from.  This script proves the record
and the value still agree and that nobody reintroduced an anonymous number:

* ``rva::NAME = 0x…;  // <function id>`` must match that record's ``rva``,
* ``field::NAME = 0x…;  // <structure id>`` must be one of its field offsets,
* no other native source may spell a module RVA or a structure offset,
* every constant declared in the header must be referenced by native code,
* every native module entry point the managed side asks for must be exported,
* the MCM state record must match ``Native/McmProtocol.h``'s static_assert block.
"""
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
EXPORT_RE = re.compile(r'__declspec\s*\(\s*dllexport\s*\)[^;{]*?\b(\w+)\s*\(')
MCM_FIELD_RE = re.compile(
    r'offsetof\(\s*State\s*,\s*(\w+)\s*\)\s*==\s*(\d+)')
MCM_SIZE_RE = re.compile(r'sizeof\(\s*State\s*\)\s*==\s*(\d+)')


def locate(base, relative):
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
    return allowed


def check_no_raw_offsets(native_root, header_name, guarded_iggy_rvas=()):
    """Reject an anonymous offset anywhere but the offsets header."""
    for path in sorted(native_root.glob('*.cpp')) + sorted(native_root.glob('*.h')):
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
        for path in sorted(native_root.glob('*.cpp')) + sorted(native_root.glob('*.h'))
        if path.name != header_name)
    for name in header_names:
        if not re.search(r'\b' + name + r'\b', text):
            raise VerificationError('MeleeOffsets.h 的 %s 没有被原生代码引用' % name)


def check_native_entry_points(base, native_root):
    exports = set()
    for path in sorted(native_root.glob('*.cpp')):
        exports.update(EXPORT_RE.findall(COMMENT_RE.sub('', path.read_text(encoding='utf-8'))))
    if not exports:
        raise VerificationError('原生组件没有导出入口点')
    requested = set()
    # A release keeps the plugin sources under source/ and only ships built
    # DLLs in Plugins/, so both layouts have to be searched.
    sources = sorted(base.glob('Plugins/*/*.cs')) + sorted(base.glob('source/Plugins/*/*.cs'))
    for path in sources:
        for entry in MANAGED_ENTRY_RE.findall(path.read_text(encoding='utf-8')):
            requested.add((path.name, entry))
    if not requested:
        raise VerificationError('没有找到 C# 侧的原生模块入口点调用')
    for name, entry in sorted(requested):
        if entry not in exports:
            raise VerificationError('%s 请求原生入口点 %s，但原生组件没有导出它' % (name, entry))
    return len(requested), len(exports)


def check_mcm_record(base, structs):
    header = locate(base, 'Native/McmProtocol.h').read_text(encoding='utf-8')
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
    base = Path(__file__).resolve().parent
    native_root = locate_native(base)
    header_name = 'MeleeOffsets.h'
    header_path = native_root / header_name
    if not header_path.is_file():
        raise VerificationError('找不到 Native/' + header_name)
    build, structs, functions = load_database(base)

    native_settings_reports = sorted((base / 'Research').glob('*/*/native-settings-mcm-bridge.json'))
    if base.joinpath('source', 'Research').is_dir():
        native_settings_reports += sorted((base / 'source' / 'Research').glob('*/*/native-settings-mcm-bridge.json'))
    if len(native_settings_reports) != 1:
        raise VerificationError('必须有且只有一份固定版本的 Iggy RVA 证据')
    iggy_evidence = json.loads(native_settings_reports[0].read_text(encoding='utf-8'))
    iggy_header = native_root / 'NativeSettingsIggy.h'
    if not iggy_header.is_file():
        raise VerificationError('找不到 Native/NativeSettingsIggy.h')
    guarded_iggy_rvas = check_guarded_iggy_rvas_text(
        iggy_header.read_text(encoding='utf-8'), iggy_evidence)

    header_text = header_path.read_text(encoding='utf-8')
    declared, offsets = check_offset_constants(header_text, build, structs, functions)
    check_no_raw_offsets(native_root, header_name, guarded_iggy_rvas)
    check_constants_are_used(declared, native_root, header_name)
    entry_points, exports = check_native_entry_points(base, native_root)
    record, mcm_fields = check_mcm_record(base, structs)

    print('PASS: build %s records %d native offsets (%d constants), %d module entry points '
          'across %d exports, and the %s record matches the ABI header (%d fields)'
          % (build, offsets, len(declared), entry_points, exports, record, mcm_fields))


if __name__ == '__main__':
    try:
        main()
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError, VerificationError) as error:
        raise SystemExit('FAIL: ' + str(error))
