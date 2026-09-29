"""Verify that the built-in C# patch table matches patch-manifest.json."""
import json
import re
import sys
from pathlib import Path


class VerificationError(Exception):
    pass


PATCH_RE = re.compile(
    r'new\s+PatchSpec\s*\(\s*'
    r'"([^"]+)"\s*,\s*'
    r'(0x[0-9A-Fa-f]+|[0-9]+)\s*,\s*'
    r'Hex\("([0-9A-Fa-f\s]+)"\)\s*,\s*'
    r'Hex\("([0-9A-Fa-f\s]+)"\)\s*,\s*'
    r'(0x[0-9A-Fa-f]+|[0-9]+)\s*,\s*'
    r'Hex\("([0-9A-Fa-f\s]+)"\)\s*\)',
    re.MULTILINE,
)


def compact_hex(value):
    compact = "".join(value.split()).lower()
    if not compact or len(compact) % 2:
        raise VerificationError("无效十六进制长度")
    try:
        return bytes.fromhex(compact).hex()
    except ValueError as error:
        raise VerificationError("无效十六进制：%s" % error)


def locate_source(base, relative='GameApi/StateOfDecay2GameApi.cs'):
    candidates = [
        base / relative,
        base / "source" / relative,
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise VerificationError("找不到游戏版本 API 源码：" + relative)


def locate_plugin(base, relative='Plugins/UnlimitedFollowers/UnlimitedFollowers.cs'):
    candidates = [
        base / relative,
        base / "source" / relative,
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise VerificationError("找不到插件源码：" + relative)


def locate_core(base):
    candidates = [
        base / "Core" / "SoD2SE.Core.cs",
        base / "source" / "Core" / "SoD2SE.Core.cs",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise VerificationError("找不到 SoD2SE.Core.cs")


def verify_manifest(base, manifest_path):
    core_path = locate_core(base)
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        api_path = locate_source(base)
        source = api_path.read_text(encoding="utf-8")
        plugin_relative = manifest.get('plugin_source', 'Plugins/UnlimitedFollowers/UnlimitedFollowers.cs')
        # The manifest's source now names the centralized Game API; use a
        # plugin source only for the separate API-version contract check.
        if str(plugin_relative).replace('\\', '/').startswith('GameApi/'):
            plugin_relative = 'Plugins/UnlimitedFollowers/UnlimitedFollowers.cs'
        plugin_path = locate_plugin(base, plugin_relative)
        plugin_source = plugin_path.read_text(encoding="utf-8")
        core_source = core_path.read_text(encoding="utf-8")
    except (OSError, ValueError) as error:
        raise VerificationError(str(error))

    expected = []
    seen_names = set()
    for patch in manifest.get("patches", []):
        if patch.get("name") in seen_names:
            raise VerificationError("清单中存在重复补丁名称")
        seen_names.add(patch.get("name"))
        expected.append({
            "name": patch["name"],
            "rva": int(patch["rva"]),
            "original": compact_hex(patch["original"]),
            "replacement": compact_hex(patch["replacement"]),
            "guard_rva": int(patch["guard_rva"]),
            "guard_original": compact_hex(patch["guard_original"]),
        })
    if not expected:
        raise VerificationError("清单没有补丁描述")

    for patch in expected:
        if len(patch["original"]) != len(patch["replacement"]) or patch["rva"] < 0 or patch["guard_rva"] < 0:
            raise VerificationError("补丁清单范围或字节长度无效：" + patch["name"])
        if patch["guard_rva"] > patch["rva"] or patch["guard_rva"] + len(bytes.fromhex(patch["guard_original"])) < patch["rva"] + len(bytes.fromhex(patch["original"])):
            raise VerificationError("补丁上下文没有覆盖写入范围：" + patch["name"])

    manifest_sha = manifest.get("sha256")
    sha_match = re.search(r'TargetSha256\s*=\s*"([0-9A-Fa-f]{64})"', core_source)
    if not isinstance(manifest_sha, str) or sha_match is None or sha_match.group(1).upper() != manifest_sha.upper():
        raise VerificationError("Core 中的 TargetSha256 与 patch-manifest.json 不一致")
    manifest_app_id = str(manifest.get("steam_app_id", ""))
    app_match = re.search(r'SteamAppId\s*=\s*"([0-9]+)"', core_source)
    if app_match is None or app_match.group(1) != manifest_app_id:
        raise VerificationError("Core 中的 SteamAppId 与 patch-manifest.json 不一致")
    api_match = re.search(r'PluginApiVersion\s*=\s*(\d+)', core_source)
    plugin_api_match = re.search(r'ApiVersion\s*\{\s*get\s*\{\s*return\s+FrameworkInfo\.PluginApiVersion\s*;\s*\}\s*\}', plugin_source)
    if api_match is None or plugin_api_match is None:
        raise VerificationError("插件 API 版本契约缺失")

    actual_all = []
    for match in PATCH_RE.finditer(source):
        actual_all.append({
            "name": match.group(1),
            "rva": int(match.group(2), 0),
            "original": compact_hex(match.group(3)),
            "replacement": compact_hex(match.group(4)),
            "guard_rva": int(match.group(5), 0),
            "guard_original": compact_hex(match.group(6)),
        })

    expected_names = {patch["name"] for patch in expected}
    actual = [patch for patch in actual_all if patch["name"] in expected_names]

    if actual != expected:
        raise VerificationError("Game API 补丁表与 patch-manifest.json 不一致")
    print("PASS: Game API patch table matches " + manifest_path.name)


def verify_plugin_tables_are_migrated(base):
    for relative in (
        'Plugins/UnlimitedFollowers/UnlimitedFollowers.cs',
        'Plugins/UnlimitedCommunity/UnlimitedCommunity.cs',
    ):
        candidates = [base / relative, base / 'source' / relative]
        path = next((candidate for candidate in candidates if candidate.is_file()), None)
        if path is None:
            raise VerificationError("找不到已迁移插件源码：" + relative)
        source = path.read_text(encoding='utf-8')
        if PATCH_RE.search(source):
            raise VerificationError("插件仍然持有版本专用补丁表：" + relative)
    print("PASS: gameplay plugins consume the centralized Game API patch inventory")


VERSION_RE = re.compile(r'public\s+const\s+string\s+Version\s*=\s*"([^"]+)"')
VERSION_ATTRIBUTE_RE = re.compile(
    r'Assembly(?:Version|FileVersion|InformationalVersion)\s*\(\s*"([^"]+)"\s*\)')
SCRIPT_VERSION_RE = re.compile(r"\$version\s*=\s*'([^']+)'")
GAME_PROCESS_RE = re.compile(r'public\s+const\s+string\s+GameProcessName\s*=\s*"([^"]+)"')
GAME_RELATIVE_RE = re.compile(r"return\s+'(StateOfDecay2[^']+\.exe)'")
CSHARP_CONST_INT_RE = re.compile(r'const\s+int\s+([^;]+);')
CSHARP_IDENTIFIER_RE = re.compile(r'^[\s\w+\-*()]+$')
SHORTCUT_DEFAULT_RE = re.compile(
    r'(?:values\["(?:mcm\.(?:choice-)?shortcut-key)"\]\s*=\s*"(\d+)"'
    r'|ReadNumber\(\s*"mcm\.(?:choice-)?shortcut-(?:key|modifiers)"\s*,\s*(\d+))')
OVERLAY_LITERAL_RE = re.compile(r'(?:GetAsyncKeyState\s*\(\s*|const\s+int\s+VkF1\s*=\s*)0x70')
ROGUELITE_DEFAULT_RE = re.compile(
    r'(?:AddXp|AddInt)\(page, "[^"]+", "[^"]+", "[^"]+", \d+')
MODULE_DLL_RE = re.compile(r'SoD2SE\.(\w+)\.Native(?:\.dll)?')
MODULE_PATH_RE = re.compile(
    r'Path\.Combine\(\s*Path\.GetDirectoryName\(Assembly\.GetExecutingAssembly\(\)\.Location\),\s*"([^"]+)",\s*"([^"]+\.dll)"\)')


def parse_csharp_int_constants(text):
    """Reads ``const int`` declarations, expanding references to earlier names."""
    values = {}
    for block in CSHARP_CONST_INT_RE.findall(strip_comments(text)):
        for item in block.split(','):
            name, _, expression = (piece.strip() for piece in item.partition('='))
            if not expression:
                raise VerificationError('常量 %s 缺少取值' % name)
            if not CSHARP_IDENTIFIER_RE.match(expression):
                raise VerificationError('不支持的常量表达式 %s' % expression)
            try:
                values[name] = int(eval(expression, {'__builtins__': {}}, values))  # noqa: S307
            except (NameError, SyntaxError, TypeError) as error:
                raise VerificationError('无法求值 %s（%s）' % (name, error))
    return values


def strip_comments(text):
    return re.sub(r'//[^\n]*', '', text)


def verify_game_path_single_source(base):
    """The shipping executable is named once, in FrameworkInfo.

    Environment.ps1 locates the game for the verification, packaging and
    install scripts; it may describe the folder layout but must not spell the
    executable a second time, because renaming it in Core alone would leave
    every script hunting for a stale file.
    """
    core_source = locate_core(base).read_text(encoding="utf-8")
    match = GAME_PROCESS_RE.search(core_source)
    if match is None:
        raise VerificationError("Core/SoD2SE.Core.cs 没有 FrameworkInfo.GameProcessName")
    if 'GameExecutableName = GameProcessName + ".exe"' not in core_source:
        raise VerificationError("GameExecutableName 没有从 GameProcessName 派生")

    environment = next((candidate for candidate in
                        (base / "Environment.ps1", base / "source" / "Environment.ps1")
                        if candidate.is_file()), None)
    if environment is None:
        raise VerificationError("找不到 Environment.ps1")
    relative = GAME_RELATIVE_RE.search(environment.read_text(encoding="utf-8"))
    if relative is None:
        raise VerificationError("Environment.ps1 没有给出游戏主程序的相对路径")
    executable = relative.group(1).replace('/', '\\').split('\\')[-1]
    if executable != match.group(1) + ".exe":
        raise VerificationError(
            "Environment.ps1 使用的主程序 %s 与 FrameworkInfo.GameProcessName（%s.exe）不一致"
            % (executable, match.group(1)))

    # The Game API targets the same file: naming the module or its hash again
    # there would let a rebuilt executable pass one check and fail the other.
    api_source = read_source_file(base, 'GameApi/StateOfDecay2GameApi.cs')
    if 'ShippingModule = FrameworkInfo.GameExecutableName' not in api_source:
        raise VerificationError('Game API 的 ShippingModule 没有引用 FrameworkInfo.GameExecutableName')
    if 'TargetSha256 = FrameworkInfo.TargetSha256' not in api_source:
        raise VerificationError('Game API 的 TargetSha256 没有引用 FrameworkInfo.TargetSha256')
    if '.exe"' in strip_comments(api_source):
        raise VerificationError('Game API 仍然写死可执行文件名；请引用 FrameworkInfo')
    print("PASS: game executable " + executable + " is named once in FrameworkInfo")
    return executable


def verify_shortcut_defaults_single_source(base):
    """Core/McmKeys.cs owns the shortcut defaults and the accepted key table.

    Core/Mcm.cs and the loader overlay both used to spell F1 as a bare 112 or
    0x70, so changing the default menu key meant editing three files and hoping
    they stayed in step.  The C# table itself is compared with the native
    windows in Native/McmProtocol.h by verify_protocol.py.
    """
    keys_source = read_source_file(base, 'Core/McmKeys.cs')
    keys = parse_csharp_int_constants(keys_source)
    for name in ('FunctionKeyFirst', 'FunctionKeyLast', 'ReservedKey', 'MenuKey',
                 'MenuModifiers', 'ChoiceKey', 'ChoiceModifiers'):
        if name not in keys:
            raise VerificationError('Core/McmKeys.cs 没有定义 ' + name)
    if not keys['FunctionKeyFirst'] <= keys['MenuKey'] <= keys['FunctionKeyLast']:
        raise VerificationError('默认菜单快捷键不在功能键范围内')
    if not (keys['FunctionKeyFirst'] <= keys['ChoiceKey'] <= keys['FunctionKeyLast'] and
            keys['ChoiceKey'] != keys['MenuKey']):
        raise VerificationError('默认升级快捷键必须是与菜单键不同的功能键')

    mcm_source = read_source_file(base, 'Core/Mcm.cs')
    for name in ('ReadNumber("mcm.shortcut-key", McmKeys.MenuKey)',
                 'ReadNumber("mcm.shortcut-modifiers", McmKeys.MenuModifiers)',
                 'ReadNumber("mcm.choice-shortcut-key", McmKeys.ChoiceKey)',
                 'ReadNumber("mcm.choice-shortcut-modifiers", McmKeys.ChoiceModifiers)',
                 'values["mcm.shortcut-key"] = McmKeys.MenuKey',
                 'values["mcm.choice-shortcut-key"] = McmKeys.ChoiceKey'):
        if name not in mcm_source:
            raise VerificationError('Core/Mcm.cs 没有读取 ' + name)
    bare = SHORTCUT_DEFAULT_RE.search(strip_comments(mcm_source))
    if bare:
        token = bare.group(1) or bare.group(2)
        raise VerificationError(
            'Core/Mcm.cs 写死了快捷键默认值 %s=%s；请改用 McmKeys'
            % (bare.group(0).strip(), token))

    overlay_source = read_source_file(base, 'Loader/McmOverlay.cs')
    if 'McmKeys.MenuKey' not in overlay_source:
        raise VerificationError('Loader/McmOverlay.cs 没有读取 McmKeys.MenuKey')
    literal = OVERLAY_LITERAL_RE.search(strip_comments(overlay_source))
    if literal:
        raise VerificationError(
            'Loader/McmOverlay.cs 写死了快捷键 0x70；请改用 McmKeys.MenuKey')
    print("PASS: the MCM shortcut defaults and key table live once in Core/McmKeys.cs")


def read_source_file(base, relative):
    for candidate in (base / relative, base / 'source' / relative):
        if candidate.is_file():
            return candidate.read_text(encoding='utf-8')
    raise VerificationError('找不到源码：' + relative)


def verify_native_module_names(base):
    """The native DLL name of each plugin is written once per build input.

    CMake names the output file, build_native.ps1 lists a fallback build and the
    managed plugin loads the file at runtime.  A rename in one place would ship
    a plugin whose native hook silently never loads, so all three agree here.
    """
    templates = {
        'Mcm': {
            'cmake': 'Native/CMakeLists.txt',
            'fallback': 'Native/build_native.ps1',
            'managed': 'Plugins/Mcm/Mcm.cs',
        },
        'MeleeSpeed': {
            'cmake': 'Native/CMakeLists.txt',
            'fallback': 'Native/build_native.ps1',
            'managed': 'Plugins/MeleeSpeed/MeleeSpeed.cs',
        },
    }
    shared = set(templates)
    for module, files in sorted(templates.items()):
        expected = 'SoD2SE.' + module + '.Native'
        for kind, relative in sorted(files.items()):
            source = strip_comments(read_source_file(base, relative))
            names = set(MODULE_DLL_RE.findall(source))
            # The CMake project and the fallback build describe every module;
            # a plugin loader names only its own.
            wanted = shared if kind != 'managed' else {module}
            if names != wanted:
                raise VerificationError(
                    '%s 中的原生模块名 %s 应为 %s'
                    % (relative, ', '.join(sorted(names)) or '（无）', ', '.join(sorted(wanted))))
            if kind == 'managed':
                match = MODULE_PATH_RE.search(source)
                if match is None:
                    raise VerificationError('%s 没有按插件子目录加载原生模块' % relative)
                if match.group(1) != module:
                    raise VerificationError(
                        '%s 从子目录 %s 加载 %s，目录名应为 %s'
                        % (relative, match.group(1), match.group(2), module))
    print("PASS: native module names agree across CMake, the fallback build and the managed loaders")


def verify_game_data_folder_single_source(base):
    """The game's own folder name is stated once, in FrameworkInfo."""
    core = read_source_file(base, 'Core/SoD2SE.Core.cs')
    match = re.search(r'GameDataFolderName\s*=\s*"([^"]+)"', core)
    if match is None:
        raise VerificationError('FrameworkInfo 没有 GameDataFolderName')
    folder = match.group(1)
    offenders = []
    for root in (base, base / 'source'):
        for relative in ('Core', 'GameApi', 'Loader', 'Plugins'):
            directory = root / relative
            if not directory.is_dir():
                continue
            for path in sorted(directory.rglob('*.cs')):
                if path.name == 'SoD2SE.Core.cs':
                    continue
                if '"' + folder + '"' in strip_comments(path.read_text(encoding='utf-8')):
                    offenders.append(str(path.relative_to(base)))
    if offenders:
        raise VerificationError(
            '这些文件写死了游戏数据目录名 %s；请改用 FrameworkInfo.GameDataFolderName：%s'
            % (folder, ', '.join(sorted(set(offenders)))))
    print("PASS: game data folder " + folder + " is named once in FrameworkInfo")


def verify_roguelite_defaults_single_source(base):
    """The growth MCM page reads its defaults from RogueliteSettings."""
    relative = 'Plugins/Roguelite/Roguelite.cs'
    source = strip_comments(read_source_file(base, relative))
    if 'static readonly RogueliteSettings DefaultSettings' not in source:
        raise VerificationError('%s 没有共用默认设置实例' % relative)
    literal = ROGUELITE_DEFAULT_RE.search(source)
    if literal:
        raise VerificationError(
            '%s 在 MCM 注册处写死默认值：%s；请改用 DefaultSettings'
            % (relative, literal.group(0)))
    print("PASS: the growth MCM page reads its defaults from RogueliteSettings")


def verify_growth_ui_routing_and_load_status(base):
    native = (base / 'Native' / 'McmNative.cpp').read_text(encoding='utf-8')
    native_code = strip_comments(native)
    visible = re.search(r'bool\s+ChoiceModalVisible\s*\(\s*\)\s*\{\s*return\s+([^;]+);', native_code)
    if visible is None or 'choiceOpen' not in visible.group(1):
        raise VerificationError('已保存的升级候选必须与玩家主动打开的选择界面分开')
    if 'choiceDismissedNonce' in native_code:
        raise VerificationError('选择界面仍使用候选 nonce 推断可见状态')
    if not re.search(r'key\s*==\s*snapshot\.choiceKey[\s\S]{0,700}ChoiceModalVisible\(\)[\s\S]{0,180}ShowGrowthOverview\(\)[\s\S]{0,180}OpenChoiceOverlay\(\)', native_code):
        raise VerificationError('F2 必须在成长总览与待选升级之间切换')
    if re.search(r'key\s*==\s*snapshot\.shortcutKey', native_code):
        raise VerificationError('旧版 F1 MCM 设置覆盖层快捷键仍处于活动状态')
    if not re.search(r'surfaceIndex\s*>=\s*0\s*&&\s*!ChoiceModalVisible\(\)[\s\S]{0,180}ApplyVisibility\(false,\s*openSurface\s*==\s*surfaceIndex\s*\?\s*-1\s*:\s*surfaceIndex\)', native_code):
        raise VerificationError('已注册的玩法界面快捷键未连接到界面宿主')

    loader = (base / 'Loader' / 'Program.cs').read_text(encoding='utf-8')
    if 'mcm.MarkLoaded(plugin.Id, true)' not in loader:
        raise VerificationError('MCM 的插件加载状态必须表示 Initialize 成功，而不是玩法能力已激活')
    if 'mcm.MarkLoaded(plugin.Id, active)' in loader:
        raise VerificationError('Loader 仍把玩法停用误报为 DLL 未加载')
    settings_model = (base / 'Native' / 'NativeSettingsModel.h').read_text(encoding='utf-8')
    if 'return Reply::Number(pages[index].loaded);' not in settings_model:
        raise VerificationError('原版 MCM 设置页必须读取插件初始化状态')

    roguelite = (base / 'Plugins' / 'Roguelite' / 'Roguelite.cs').read_text(encoding='utf-8')
    for token in ('StateOfDecay2Capabilities.NativeProgressionUi', 'StateOfDecay2Capabilities.RogueliteKillEvents',
                  'StateOfDecay2Capabilities.SurvivorIdentity', 'StateOfDecay2Capabilities.SurvivorAttributes',
                  'StateOfDecay2Capabilities.SinglePlayerPause'):
        if token not in roguelite:
            raise VerificationError('成长 Mod 没有检查必需能力：' + token)

    database = base / 'Research' / 'StateOfDecay2' / '16535856'
    capability_data = json.loads((database / 'roguelite-capabilities.json').read_text(encoding='utf-8'))
    ui_capability = capability_data.get('runtime_capabilities', {}).get('sod2.ui.native-progression', {})
    functions = json.loads((database / 'functions.json').read_text(encoding='utf-8')).get('functions', [])
    by_id = {item.get('id'): item for item in functions}
    candidate_ids = ui_capability.get('native_function_candidates', [])
    if ui_capability.get('status') != 'static-evidence-expanded' or not candidate_ids:
        raise VerificationError('原版 UI 研究状态或静态候选清单缺失')
    for candidate_id in candidate_ids:
        candidate = by_id.get(candidate_id)
        if candidate is None or 'sod2.ui.native-progression' not in candidate.get('capabilities', []):
            raise VerificationError('原版 UI 候选没有对应的唯一研究记录：' + str(candidate_id))
        if not str(candidate.get('confidence', '')).startswith('static-registration'):
            raise VerificationError('原版 UI 候选不应在证据不足时标记为运行时可用：' + str(candidate_id))
    game_api = (base / 'GameApi' / 'StateOfDecay2GameApi.cs').read_text(encoding='utf-8')
    if not re.search(r'capabilities\.Declare\(StateOfDecay2Capabilities\.NativeProgressionUi,\s*false,', game_api):
        raise VerificationError('原版 UI 能力未确认时必须保持关闭')
    print('PASS: F1/F2 routing is exclusive, MCM status is truthful, and native UI candidates remain gated')


def verify_version_single_source(base):
    """Framework and each plugin have one declared version source."""
    core_path = locate_core(base)
    match = VERSION_RE.search(core_path.read_text(encoding="utf-8"))
    if match is None:
        raise VerificationError("Core/SoD2SE.Core.cs 没有 FrameworkInfo.Version")
    version = match.group(1)

    # No source file may carry version attributes: build.ps1 generates them
    # from Core for framework binaries and each plugin's mod.json for plugins.
    roots = []
    for root in (base, base / "source"):
        if not (root / "Core" / "SoD2SE.Core.cs").is_file():
            continue
        roots.append(root)
    if not roots:
        raise VerificationError("找不到源码目录")
    identity_files = 0
    for root in roots:
        for path in sorted(root.glob("*/AssemblyInfo.cs")) + sorted(root.glob("Plugins/*/AssemblyInfo.cs")):
            identity_files += 1
            stray = VERSION_ATTRIBUTE_RE.findall(path.read_text(encoding="utf-8"))
            if stray:
                raise VerificationError(
                    "%s 仍然硬编码版本属性 %s；版本由 build.ps1 生成"
                    % (path.relative_to(base), ", ".join(stray)))
        for path in sorted(root.glob("Plugins/*/*.cs")) + sorted(root.glob("*/*.cs")):
            stray = VERSION_ATTRIBUTE_RE.findall(path.read_text(encoding="utf-8"))
            if stray:
                raise VerificationError(
                    "%s 硬编码版本属性 %s；版本由 build.ps1 生成"
                    % (path.relative_to(base), ", ".join(stray)))
    if identity_files < 8:
        raise VerificationError("收集到的 AssemblyInfo.cs 少于 8 个，目录结构可能已变化")

    # The generator itself has to keep reading the one version literal.
    build_script = next((candidate for candidate in (base / "build.ps1", base / "source" / "build.ps1")
                         if candidate.is_file()), None)
    if build_script is None:
        raise VerificationError("找不到 build.ps1")
    build_text = build_script.read_text(encoding="utf-8")
    for token in ("Get-SoD2SEVersion", "Get-SoD2SEAssemblyVersion", "AssemblyInformationalVersion"):
        if token not in build_text:
            raise VerificationError("build.ps1 没有通过 %s 生成版本属性" % token)
    if "mod.json" not in build_text or "pluginVersionSource" not in build_text:
        raise VerificationError("build.ps1 没有按插件声明生成程序集版本")
    plugin_versions = {}
    for root in roots:
        for plugin in sorted((root / "Plugins").iterdir()):
            if not plugin.is_dir() or not list(plugin.glob("*.cs")):
                continue
            manifest_path = plugin / "mod.json"
            if not manifest_path.is_file():
                raise VerificationError("%s 缺少 mod.json" % plugin.relative_to(base))
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest.get("id") != plugin.name or not re.fullmatch(
                    r"\d+\.\d+\.\d+(?:-[A-Za-z0-9.-]+)?", str(manifest.get("version", ""))):
                raise VerificationError("%s 的 ID 或版本无效" % manifest_path.relative_to(base))
            plugin_versions[plugin.name] = manifest["version"]

    for name in ("package.ps1", "package_mo2.ps1", "install_mo2_preview.ps1"):
        path = next((candidate for candidate in (base / name, base / "source" / name)
                     if candidate.is_file()), None)
        if path is None:
            continue
        literals = SCRIPT_VERSION_RE.findall(path.read_text(encoding="utf-8"))
        if literals:
            raise VerificationError(
                "%s 仍然硬编码版本 %s；请改用 Environment.ps1 的 Get-SoD2SEVersion"
                % (path.relative_to(base), ", ".join(literals)))

    # The research target records the mod version it documents.  The root
    # patch manifests name the game build instead, so they are checked against
    # the research database by verify_research.py rather than here.
    targets = sorted((base / "Research").glob("*/*/target.json"))
    if base.joinpath("source", "Research").is_dir():
        targets += sorted((base / "source" / "Research").glob("*/*/target.json"))
    if not targets:
        raise VerificationError("找不到 Research/*/*/target.json")
    for path in targets:
        framework = json.loads(path.read_text(encoding="utf-8")).get("framework", "")
        if version not in framework:
            raise VerificationError(
                "%s 的 framework 字段为 %s，没有包含 %s" % (path, framework, version))

    print("PASS: framework version " + version + " and " + str(len(plugin_versions)) +
          " plugin manifest versions are stamped from their own sources")
    return version


def main():
    base = Path(__file__).resolve().parent
    manifests = sorted(base.glob('*patch-manifest.json'))
    if not manifests:
        raise VerificationError('No patch manifests found')
    for manifest_path in manifests:
        verify_manifest(base, manifest_path)
    verify_plugin_tables_are_migrated(base)
    verify_version_single_source(base)
    verify_game_path_single_source(base)
    verify_shortcut_defaults_single_source(base)
    verify_native_module_names(base)
    verify_game_data_folder_single_source(base)
    verify_roguelite_defaults_single_source(base)
    verify_growth_ui_routing_and_load_status(base)


if __name__ == "__main__":
    try:
        main()
    except (KeyError, TypeError, ValueError, VerificationError) as error:
        raise SystemExit("FAIL: " + str(error))
