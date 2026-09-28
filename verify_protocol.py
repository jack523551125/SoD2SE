"""Cross-check the MCM ABI in Native/McmProtocol.h against every consumer.

The header is the single source of truth.  The C# bridge, the native host and
the test harnesses all have to agree with it byte for byte, so this script
recomputes the packed layout from the struct declarations and then compares:

* the header's own ``static_assert`` block,
* every named constant in Plugins/Mcm/Mcm.cs,
* the offsets named in Tests/McmIntegrationSmoke.cs and Tests/GrowthScreenPreview.cs,
* the command ids the native host writes,

It also rejects raw numbers at wire sites, because a bare offset in a call such
as ``view.Write(60, 1)`` is exactly how a layout change goes unnoticed.
"""
import re
import sys
from pathlib import Path


class VerificationError(Exception):
    pass


# ---------------------------------------------------------------- header model

CONST_RE = re.compile(r'constexpr\s+(?:uint32_t|int32_t|int)\s+([^;]+);')
ENUM_RE = re.compile(r'enum\s+(\w+)\s*:\s*int32_t\s*\{(.*?)\}', re.S)
STRUCT_RE = re.compile(r'struct\s+(\w+)\s*\{(.*?)\}\s*;', re.S)
ASSERT_RE = re.compile(r'static_assert\s*\((.*?)\)\s*;', re.S)
COMMENT_RE = re.compile(r'//[^\n]*')

INT_TYPES = {'int32_t': 4, 'uint32_t': 4, 'int': 4, 'int64_t': 8, 'uint64_t': 8}
CHAR_TYPES = {'char': 1}


def strip_comments(text):
    return COMMENT_RE.sub('', text)


def split_declaration(statement, constants):
    """Expands one C declaration into (type, name, count) triples."""
    statement = re.sub(r'^volatile\s+', '', statement.strip())
    parts = [part.strip() for part in statement.split(',') if part.strip()]
    head = re.match(r'^(\w+)\s+(\w+)(\[([^\]]+)\])?$', parts[0])
    if head is None:
        raise VerificationError('无法解析字段声明：' + statement)
    type_name = head.group(1)
    members = [(type_name, head.group(2), head.group(4))]
    for part in parts[1:]:
        item = re.match(r'^(\w+)(\[([^\]]+)\])?$', part)
        if item is None:
            raise VerificationError('无法解析字段声明：' + statement)
        members.append((type_name, item.group(1), item.group(3)))
    return [(member_type, name, resolve_count(count, constants))
            for member_type, name, count in members]


def resolve_count(token, constants):
    if token is None:
        return None
    if token.isdigit():
        return int(token)
    if token not in constants:
        raise VerificationError('未知的数组长度：' + token)
    return constants[token]


class Header:
    def __init__(self, path):
        text = strip_comments(path.read_text(encoding='utf-8'))
        self.path = path
        self.constants = {}
        for block in CONST_RE.findall(text):
            for item in block.split(','):
                name, _, value = (piece.strip() for piece in item.partition('='))
                if not value:
                    raise VerificationError('常量缺少取值：' + name)
                self.constants[name] = int(value, 0)
        # Header enums are named contracts: CommandId drives State::command and
        # OptionType drives Option::type.  An unnamed enum would be a value
        # neither side is checking, so it is rejected instead of ignored.
        self.commands = {}
        self.option_types = {}
        targets = {'CommandId': self.commands, 'OptionType': self.option_types}
        for enum_name, body in ENUM_RE.findall(text):
            if enum_name not in targets:
                raise VerificationError('McmProtocol.h 出现未登记的枚举：' + enum_name)
            target = targets[enum_name]
            for item in body.split(','):
                item = item.strip()
                if not item:
                    continue
                name, _, value = (piece.strip() for piece in item.partition('='))
                target[name] = int(value, 0)
        self.members = {}
        for name, body in STRUCT_RE.findall(text):
            fields = []
            for statement in body.split(';'):
                if statement.strip():
                    fields.extend(split_declaration(statement.strip(), self.constants))
            self.members[name] = fields
        self.offsets, self.sizes, self.field_sizes = {}, {}, {}
        for name in self.members:
            self._layout(name)
        self.asserts = ASSERT_RE.findall(text)

    def _align(self, offset, alignment):
        alignment = min(alignment, 4)  # the header compiles with pack(4)
        return (offset + alignment - 1) // alignment * alignment

    def _size_of(self, type_name):
        if type_name in INT_TYPES:
            return INT_TYPES[type_name], 4
        if type_name in CHAR_TYPES:
            return CHAR_TYPES[type_name], 1
        if type_name in self.sizes:
            return self.sizes[type_name], 4
        raise VerificationError('未知字段类型：' + type_name)

    def _layout(self, name):
        if name in self.sizes:
            return self.sizes[name]
        if name not in self.members:
            raise VerificationError('未知结构体：' + name)
        offset = 0
        largest = 1
        for type_name, field, count in self.members[name]:
            element, alignment = self._size_of(type_name)
            offset = self._align(offset, alignment)
            total = element * (count if count else 1)
            self.offsets[(name, field)] = offset
            self.field_sizes[(name, field)] = total
            largest = max(largest, alignment)
            offset += total
        size = self._align(offset, largest)
        self.sizes[name] = size
        return size

    def offset_of(self, struct, field):
        return self.offsets[(struct, field)]

    def size_of(self, struct):
        return self.sizes[struct]

    def size_of_field(self, struct, field):
        return self.field_sizes[(struct, field)]

    def check_asserts(self):
        """The header's own static_assert block must match the recomputation."""
        pattern = re.compile(
            r'(?:sizeof|offsetof)\s*\(\s*(\w+)\s*(?:,\s*(\w+))?\s*\)\s*==\s*(\d+)')
        seen = 0
        for block in self.asserts:
            for struct, field, expected in pattern.findall(block):
                seen += 1
                if field:
                    actual = self.offset_of(struct, field)
                    label = 'offsetof(%s, %s)' % (struct, field)
                else:
                    actual = self.size_of(struct)
                    label = 'sizeof(%s)' % struct
                if actual != int(expected):
                    raise VerificationError(
                        '%s 的 static_assert 为 %s，按字段重算为 %s'
                        % (label, expected, actual))
        if seen == 0:
            raise VerificationError('McmProtocol.h 没有可校验的 static_assert')
        return seen


# ------------------------------------------------------------------ C# parsing

CSHARP_CONST_RE = re.compile(r'const\s+int\s+([^;]+);')
EXPR_RE = re.compile(r'^[\s\w+\-*()]+$')


def parse_csharp_constants(path):
    text = strip_comments(path.read_text(encoding='utf-8'))
    values = {}
    for block in CSHARP_CONST_RE.findall(text):
        for item in block.split(','):
            name, _, expression = (piece.strip() for piece in item.partition('='))
            if not expression:
                raise VerificationError('%s：常量 %s 缺少取值' % (path.name, name))
            if not EXPR_RE.match(expression):
                raise VerificationError('%s：不支持的常量表达式 %s' % (path.name, expression))
            try:
                values[name] = int(eval(expression, {'__builtins__': {}}, values))  # noqa: S307
            except (NameError, SyntaxError, TypeError) as error:
                raise VerificationError('%s：无法求值 %s（%s）' % (path.name, name, error))
    if not values:
        raise VerificationError('%s：没有找到任何常量' % path.name)
    return values


def pascal(name):
    return name[:1].upper() + name[1:]


CSHARP_ENUM_RE = re.compile(r'enum\s+(\w+)\s*\{(.*?)\}', re.S)


def parse_csharp_enum(path, name):
    """Reads one C# enum into {member: value}; empty entries inherit +1."""
    text = strip_comments(path.read_text(encoding='utf-8'))
    for enum_name, body in CSHARP_ENUM_RE.findall(text):
        if enum_name != name:
            continue
        values = {}
        next_value = 0
        for item in body.split(','):
            item = item.strip()
            if not item:
                continue
            member, _, expression = (piece.strip() for piece in item.partition('='))
            if not expression:
                value = next_value
            elif EXPR_RE.match(expression):
                try:
                    value = int(eval(expression, {'__builtins__': {}}, values))  # noqa: S307
                except (NameError, SyntaxError, TypeError) as error:
                    raise VerificationError('%s：无法求值 %s（%s）' % (path.name, member, error))
            else:
                raise VerificationError('%s：不支持的枚举取值 %s' % (path.name, expression))
            values[member] = value
            next_value = value + 1
        return values
    raise VerificationError('%s 没有定义枚举 %s' % (path.name, name))


def expected_constants(header):
    """Every ABI constant the C# side is allowed to name, with its value."""
    expected = {
        'ProtocolMagic': header.constants['Magic'],
        'ProtocolVersion': header.constants['Version'],
        'ReadyPending': header.constants['ReadyPending'],
        'Ready': header.constants['Ready'],
        'Failed': header.constants['Failed'],
        'MaxPages': header.constants['MaxPages'],
        'MaxOptions': header.constants['MaxOptions'],
        'MaxChoiceCards': header.constants['MaxChoiceCards'],
        'UiMaxSurfaces': header.constants['MaxSurfaces'],
        'UiMaxNodes': header.constants['MaxNodes'],
        'Size': header.size_of('State'),
    }
    for name in header.commands:
        expected['Command' + name[len('Cmd'):]] = header.commands[name]
    # State: a bare field becomes <Pascal>Offset.
    for _, field, _ in header.members['State']:
        expected[pascal(field) + 'Offset'] = header.offset_of('State', field)
    # Two header fields describe the handshake, and the bridge names them by
    # whose pid they carry rather than by the header's short field name.
    del expected['OwnerOffset'], expected['GameOffset']
    expected['HostPidOffset'] = header.offset_of('State', 'owner')
    expected['GamePidOffset'] = header.offset_of('State', 'game')
    # choiceVisible starts the choice block, and the C# bridge names it
    # ChoiceOffset; the fields inside it are relative to that base.
    expected['ChoiceVisibleOffset'] = 0
    expected['ChoiceOffset'] = header.offset_of('State', 'choiceVisible')
    for _, field, _ in header.members['State']:
        offset = header.offset_of('State', field)
        base = header.offset_of('State', 'choiceVisible')
        if (offset > base and field.startswith('choice') and field != 'choiceCards'
                and header.size_of_field('State', field) == 4):
            expected[pascal(field) + 'Offset'] = offset - base
    expected['ChoiceCardsOffset'] = header.offset_of('State', 'choiceCards') - base
    expected['ChoiceTextOffset'] = header.offset_of('State', 'choiceCharacter')
    expected['ChoiceCharacterSize'] = header.size_of_field('State', 'choiceCharacter')
    expected['ChoiceExperienceSize'] = header.size_of_field('State', 'choiceExperience')
    expected['ChoiceNextExperienceOffset'] = (
        header.offset_of('State', 'choiceNextExperience')
        - header.offset_of('State', 'choiceCharacter'))
    expected['MessageSize'] = header.size_of_field('State', 'message')
    expected['ConfigPathSize'] = header.size_of_field('State', 'configPath')
    # Plain records: <Record>Size plus <Record><Field>Offset/Size.
    for record in ('Page', 'Option', 'ChoiceCard'):
        expected[record + 'Size'] = header.size_of(record)
        for _, field, _ in header.members[record]:
            expected[record + pascal(field) + 'Offset'] = header.offset_of(record, field)
            if header.size_of_field(record, field) > 4:
                expected[record + pascal(field) + 'Size'] = header.size_of_field(record, field)
    # The choice cards expose "current" and "next" without repeating "Value".
    del expected['ChoiceCardCurrentValueOffset'], expected['ChoiceCardNextValueOffset']
    expected['ChoiceCardCurrentOffset'] = header.offset_of('ChoiceCard', 'currentValue')
    expected['ChoiceCardNextOffset'] = header.offset_of('ChoiceCard', 'nextValue')
    # Screens and rows drop the "Offset" suffix on purpose: they read as
    # SurfaceOpen / NodeLabel at the call site.
    expected['UiSurfaceSize'] = header.size_of('UiSurface')
    for _, field, _ in header.members['UiSurface']:
        expected['Surface' + pascal(field)] = header.offset_of('UiSurface', field)
        if header.size_of_field('UiSurface', field) > 4:
            expected['Surface' + pascal(field) + 'Size'] = header.size_of_field('UiSurface', field)
    expected['UiNodeSize'] = header.size_of('UiNode')
    for _, field, _ in header.members['UiNode']:
        expected['Node' + pascal(field)] = header.offset_of('UiNode', field)
        if header.size_of_field('UiNode', field) > 4:
            expected['Node' + pascal(field) + 'Size'] = header.size_of_field('UiNode', field)
    return expected


def compare_constants(label, actual, expected):
    unknown = sorted(set(actual) - set(expected))
    if unknown:
        raise VerificationError('%s 定义了协议之外的常量：%s' % (label, ', '.join(unknown)))
    mismatched = [
        '%s=%s（应为 %s）' % (name, actual[name], expected[name])
        for name in sorted(actual) if actual[name] != expected[name]]
    if mismatched:
        raise VerificationError('%s 与 McmProtocol.h 不一致：%s' % (label, '；'.join(mismatched)))
    return len(actual)


def expected_melee_constants(header):
    """Every channel constant Plugins/MeleeSpeed/MeleeSpeed.cs may name."""
    channel = 'Channel'
    expected = {
        'ChannelMagic': header.constants['ChannelMagic'],
        'ChannelVersion': header.constants['ChannelVersion'],
        'ChannelSize': header.size_of(channel),
        'RateCount': header.constants['MaxCategories'],
        'ScopeCount': header.constants['MaxScopes'],
        'RateMinimum': header.constants['RateMinimum'],
        'RateMaximum': header.constants['RateMaximum'],
        'RateNormal': header.constants['RateNormal'],
    }
    # The channel fields are integers, so <Pascal>Offset is unambiguous.
    aliases = {
        'magic': 'MagicOffset', 'version': 'VersionOffset', 'owner': 'OwnerOffset',
        'active': 'ActiveOffset', 'rates': 'RatesOffset', 'scopes': 'ScopesOffset',
        'shutdown': 'ShutdownOffset', 'heartbeat': 'HeartbeatOffset',
        'actionTicks': 'ActionTicksOffset', 'animationTicks': 'AnimationTicksOffset',
        'faults': 'FaultsOffset',
    }
    for _, field, _ in header.members[channel]:
        if field in aliases:
            expected[aliases[field]] = header.offset_of(channel, field)
    return expected


# ------------------------------------------------------- bare-literal detection

WIRE_RE = re.compile(
    r'\b(?:view|accessor)\s*\.\s*(?:ReadInt32|Write|ReadInt64|WriteInt32|ReadArray|WriteArray)'
    r'\s*\(\s*(?:0x[0-9A-Fa-f]+|\d+)\b|'
    r'\b(?:WriteText|ReadText)\s*\(\s*(?:0x[0-9A-Fa-f]+|\d+)\b')


def check_no_bare_offsets(path, relative):
    text = strip_comments(path.read_text(encoding='utf-8'))
    lines = text.split('\n')
    hits = []
    offset = 0
    for line in lines:
        for match in WIRE_RE.finditer(line):
            hits.append('%s:%d' % (relative, offset + 1))
        offset += 1
    if hits:
        raise VerificationError('这些位置直接写裸偏移，应改为具名常量：' + ', '.join(hits))


def locate(base, relative):
    for candidate in (base / relative, base / 'source' / relative):
        if candidate.is_file():
            return candidate
    raise VerificationError('找不到文件：' + relative)


def main():
    base = Path(__file__).resolve().parent
    header_path = locate(base, 'Native/McmProtocol.h')
    header = Header(header_path)
    if not header.commands:
        raise VerificationError('McmProtocol.h 没有定义命令编号')
    asserts = header.check_asserts()
    expected = expected_constants(header)

    checked = 0
    for relative in ('Plugins/Mcm/Mcm.cs',
                     'Tests/McmIntegrationSmoke.cs',
                     'Tests/GrowthScreenPreview.cs'):
        path = locate(base, relative)
        checked += compare_constants(relative, parse_csharp_constants(path), expected)
        check_no_bare_offsets(path, relative)

    native = locate(base, 'Native/McmNative.cpp')
    native_text = strip_comments(native.read_text(encoding='utf-8'))
    for match in re.finditer(r'\bCommand\s*\(\s*(\d+)', native_text):
        raise VerificationError('Native/McmNative.cpp 使用裸命令编号：' + match.group(1))
    native_contract_sources = [native_text]
    for relative in ('Native/NativeSettingsModel.h', 'Native/NativeSettingsIggyTest.cpp'):
        path = locate(base, relative)
        native_contract_sources.append(strip_comments(path.read_text(encoding='utf-8')))
    used_commands = set()
    for source in native_contract_sources:
        used_commands.update(re.findall(r'\bmcm::(Cmd[A-Za-z0-9_]+)', source))
    unknown_commands = used_commands.difference(header.commands)
    if unknown_commands:
        raise VerificationError('C++ 使用了未声明的命令：' + ', '.join(sorted(unknown_commands)))
    used_option_types = set()
    for source in native_contract_sources:
        used_option_types.update(re.findall(r'\bmcm::(Option[A-Za-z0-9_]+)', source))
    unknown_option_types = used_option_types.difference(header.option_types)
    if unknown_option_types:
        raise VerificationError('C++ 使用了未声明的选项类型：' + ', '.join(sorted(unknown_option_types)))
    # Option widgets are chosen by the enum above; a bare digit here is how the
    # two sides drift apart while both still compile.
    for match in re.finditer(r'option\s*\.\s*type\s*[!=]=\s*\d', native_text):
        raise VerificationError('Native/McmNative.cpp 用裸数字判断选项类型：' + match.group(0))

    core_source = locate(base, 'Core/Mcm.cs')
    option_types = parse_csharp_enum(core_source, 'McmOptionType')
    if not header.option_types:
        raise VerificationError('McmProtocol.h 没有定义 OptionType 枚举')
    if len(header.option_types) != len(option_types):
        raise VerificationError('McmProtocol.h 与 Core/Mcm.cs 的选项类型数量不一致')
    for member, value in option_types.items():
        name = 'Option' + member
        if header.option_types.get(name) != value:
            raise VerificationError(
                'McmProtocol.h 的 %s=%s 与 Core/Mcm.cs 的 McmOptionType.%s=%s 不一致'
                % (name, header.option_types.get(name), member, value))

    # Shortcut capture: native and managed layers share one numeric table.
    # The current native host no longer records the retired F1 settings-menu
    # shortcut, so it may use only a subset of the shared key constants.
    shortcut_names = {
        'ShortcutFunctionFirst': 'FunctionKeyFirst',
        'ShortcutFunctionLast': 'FunctionKeyLast',
        'ShortcutLetterFirst': 'LetterKeyFirst',
        'ShortcutLetterLast': 'LetterKeyLast',
        'ShortcutDigitFirst': 'DigitKeyFirst',
        'ShortcutDigitLast': 'DigitKeyLast',
        'ShortcutNavigationFirst': 'NavigationKeyFirst',
        'ShortcutNavigationLast': 'NavigationKeyLast',
        'ShortcutInsert': 'InsertKey',
        'ShortcutDelete': 'DeleteKey',
        'ShortcutTab': 'TabKey',
        'ShortcutReservedKey': 'ReservedKey',
        'ShortcutControlModifier': 'ControlModifier',
        'ShortcutAltModifier': 'AltModifier',
        'ShortcutShiftModifier': 'ShiftModifier',
        'ShortcutMaxModifiers': 'MaxModifiers',
    }
    managed_keys = parse_csharp_constants(locate(base, 'Core/McmKeys.cs'))
    for header_name, managed_name in sorted(shortcut_names.items()):
        if header_name not in header.constants:
            raise VerificationError('McmProtocol.h 没有定义 ' + header_name)
        if managed_name not in managed_keys:
            raise VerificationError('Core/McmKeys.cs 没有定义 ' + managed_name)
        if header.constants[header_name] != managed_keys[managed_name]:
            raise VerificationError(
                'McmProtocol.h 的 %s=%s 与 Core/McmKeys.cs 的 %s=%s 不一致'
                % (header_name, header.constants[header_name],
                   managed_name, managed_keys[managed_name]))
    used_shortcuts = set(re.findall(r'\bmcm::(Shortcut[A-Za-z0-9_]+)', native_text))
    unknown_shortcuts = used_shortcuts.difference(header.constants)
    if unknown_shortcuts:
        raise VerificationError('Native/McmNative.cpp 使用了未声明的快捷键常量：' + ', '.join(sorted(unknown_shortcuts)))

    # Melee speed channel: same rule, one header and one managed bridge.
    melee_path = locate(base, 'Native/MeleeProtocol.h')
    melee = Header(melee_path)
    melee_asserts = melee.check_asserts()
    melee_relative = 'Plugins/MeleeSpeed/MeleeSpeed.cs'
    melee_source = locate(base, melee_relative)
    melee_checked = compare_constants(melee_relative, parse_csharp_constants(melee_source),
                                      expected_melee_constants(melee))
    check_no_bare_offsets(melee_source, melee_relative)
    melee_native = strip_comments(locate(base, 'Native/MeleeNative.cpp').read_text(encoding='utf-8'))
    for token in ('melee::ChannelMagic', 'melee::ChannelVersion'):
        if token not in melee_native:
            raise VerificationError('Native/MeleeNative.cpp 没有引用 ' + token)
    if re.search(r'0x314c454d', melee_native):
        raise VerificationError('Native/MeleeNative.cpp 仍然硬编码通道魔数')

    print('PASS: MCM ABI v%s matches %d static_asserts, %d named constants and %d option types; '
          'melee channel v%s matches %d static_asserts and %d named constants'
          % (header.constants['Version'], asserts, checked, len(option_types),
             melee.constants['ChannelVersion'], melee_asserts, melee_checked))


if __name__ == '__main__':
    try:
        main()
    except (OSError, VerificationError) as error:
        raise SystemExit('FAIL: ' + str(error))
