# 游戏内 Mod Configuration Menu 1.4（包版本 0.6.3-preview；ABI 0.6.0） / In-game Mod Configuration Menu 1.4

MCM `0.6.3-preview` 已移除旧的 F1 设置覆盖层。设置入口现在是游戏原版“设置 → Mod 设置”；同时启用“原版 Mod 设置入口 - Native Mod Settings Entry”与 MCM。该页面接入仍在预览阶段，尚未完成本次变更的实机验收；F1 不再打开旧 MCM 菜单。运行记录位于 `%LOCALAPPDATA%\StateOfDecay2\SoD2SE\Mcm-native-<PID>.log`。

MCM `0.6.3-preview` retires the old F1 settings overlay. Open configuration through the game's own Settings → Mod Settings page, with both the Native Mod Settings Entry asset mod and MCM enabled. This bridge is still a preview and this revision has not been accepted in-game; F1 no longer opens the old MCM menu. Runtime diagnostics are written to `%LOCALAPPDATA%\StateOfDecay2\SoD2SE\Mcm-native-<PID>.log`.

空白页诊断日志会明确区分：Iggy 回调槽为空、Hook 安装失败、Hook 已安装但 Mod 设置 RPC 尚未到达、RPC 参数不匹配、MCM 通道拒绝快照、桥接拒绝请求，以及 Iggy 结果路径或结果写入失败。此前日志没有这些字段，不能用于判断本次剩余故障。

MCM 不提供语言选择。每次启动时，Core 依次检查游戏配置中的 language/locale/culture、Steam 游戏清单 `MountedConfig.language` 与 `UserConfig.language`、Steam 游戏专属注册表值、Steam 客户端语言，最后回退到 Windows UI 语言。只映射中文和 English；旧版本写入的 `mcm.language` 与 `mcm.language-source` 会被忽略并清理，因此语言始终跟随当前游戏安装。原版 Mod 设置入口和所有 MCM 文案使用同一份检测结果。Mod 可以通过 `McmRegistry.Language` 读取语言，或继续只提供一种回退文本。

MCM has no language selector. Core checks game language/locale/culture settings, the Steam game's `MountedConfig.language` and `UserConfig.language`, the per-game Steam registry value, the Steam client language, and finally the Windows UI language on every launch. It maps Chinese and English, ignores and removes legacy `mcm.language` values, and follows the current game installation. The native Mod Settings page and MCM strings use this detected language. Mods can read it through `McmRegistry.Language` or provide a single fallback string.

无限随从、社区招募无上限和近战攻速各有自己的设置。标记“下次启动生效”的设置需要退出并重新启动游戏；近战攻速的倍率和作用范围可实时修改。MO2 左栏勾选管理整个 DLL，MCM 开关管理安装后是否初始化其效果；二者都启用才生效。取消 MO2 的 MCM 勾选会移除菜单，已经保存的 Mod 开关仍由框架读取。

## 原版设置菜单入口（0.2.4-preview）

启用“原版 Mod 设置入口 - Native Mod Settings Entry”资源包与 MCM 后，可从游戏原版“设置 → Mod 设置”进入 MCM 已注册的设置页。MCM 包版本为 `0.6.3-preview`，`Mcm.dll` 的程序集 ABI 仍为 `0.6.0`。原版页的菜单语言每次启动时自动跟随游戏语言，不提供手动切换控件。旧 F1 设置覆盖层已从原生渲染和快捷键路径移除；原版页内容仍待实机验证，空白问题尚未确认解决。

## 模块界面（0.6.0-preview 新增）

MCM 现在兼任界面宿主：插件不再把玩法数据塞进配置页，而是注册自己的游戏内界面。宿主统一负责绘制、排版、输入拦截、快捷键和窗口外壳，风格沿用原版菜单的深色半透明面板、灰白文字和琥珀色高亮。

- 最多 6 个界面，每个界面最多 24 行，全局合计 96 行；行类型有分区标题、正文、键值、进度条、列表项、按钮、提示和分隔线。
- 默认快捷键为 F2–F7；玩法界面是独立的一层，`Esc` 关闭，同时只显示一个界面。
- 三选一提示是内置模态。它由升级提示键（默认 F2）唤出，并按 `SetChoiceOwner` 声明的归属界面打开对应进度页。

这不是游戏原生 UMG/Coherent 控件树，而是 D3D11 绘制、模仿原版观感的外置界面层；不能插入原版菜单导航、不支持手柄菜单、打开时不暂停世界。开发接口、行类型、线程约定和测试命令见 `UI.zh-CN.md`。

设置默认保存在 `%LOCALAPPDATA%\StateOfDecay2\SoD2SE\mcm.ini`，不同 MO2 配置档共用。环境变量 `SOD2SE_MCM_CONFIG` 可指定其他文件。写入采用同目录临时文件及替换，失败显示错误并回滚本次值。快捷键立即生效；两个原生补丁不会在运行时切换。

## 已知边界

- 当前是 DX11/x64 实现，只在 Windows 上测试。没有 DX12/Vulkan 后端；设备丢失或游戏完全替换交换链后的恢复尚未实现，普通 ResizeBuffers 已测试。
- 菜单不暂停世界。主要操作方式为键鼠；没有实现手柄菜单导航。仅挂接初始化时找到的第一个 XInput 库，不能保证拦截所有第三方输入链路。
- 尚未全面测试独占全屏、多显示器高 DPI、HDR、ReShade、RTSS、其他覆盖层组合。
- 中文字体使用系统微软雅黑；缺失时使用默认字体，中文显示可能不完整。英文界面使用同一字体的 Latin 字形。
- 目前两项 Mod 设置只有启用开关，没有虚构的人数上限滑块。超员存档、多人模式、特殊剧情等原有 Mod 限制仍然存在。
- 菜单最多 32 个 Mod 页面、总计 128 项设置。页面名称最多 127 UTF-8 字节，描述最多 511 字节，过长显示文本截断。配置文件路径显示上限 1023 字节，实际保存路径不受显示长度影响。协议 ABI 6 保留 v2–v5 的标量设置、三选一卡片和快捷键字段，把 v5 的固定“成长”块换成通用界面块（6 个界面、每界面 24 行、全局 96 行）；旧版原生组件会被拒绝加载，Loader/Core/GameApi 与插件包必须同版本更新。
- 原生 DLL 与钩子在进程结束前保持驻留。框架正常停止或退出后菜单停用，不支持游戏运行中卸载/重新加载 MCM DLL。
- 配置菜单只显示已发现的 SoD2SE 插件配置；不能自动编辑任意 PAK/Cooked Mod。
- 不同 MO2 配置档默认共用设置文件；切换 MO2 配置档不会自动复制或隔离 MCM 设置。

## Mod 作者接口

托管插件引用同版本 `SoD2SE.Core.dll`，在 `ISoD2Plugin` 之外实现 `IMcmConfigurable.RegisterMcm(McmRegistry)`。用 `RegisterPlugin` 注册页面，再用 `AddBool`/`AddInt`/`AddIntInput` 声明选项；近战倍率使用 `AddIntInput`，因此菜单显示可直接输入的数字框。多语言插件可以使用 `McmLocalizedText(中文, English)`，也可以使用 `new McmLocalizedText("默认文本")` 只提供一个文本。`McmRegistry.Language` 返回启动时检测到的游戏语言，Mod 可按需使用；MCM 不强制 Mod 提供翻译。`LanguageChanged` 保留为旧 API 兼容事件，游戏语言在一次运行期间不提供手动切换。必须保持页面和选项 ID 稳定且唯一。`enabled` 是框架识别的初始化开关。通过 `Snapshot` 读取普通选项的值，Mod 必须自行实现其效果；声明设置不会自动改变游戏函数。不存在引擎线程回调或自动热更新补丁能力。

需要在游戏里显示玩法数据的插件改用界面框架：`UiRegistry.Current.RegisterSurface(id, 标题, 副标题, 构建回调)` 注册一个界面，`UiSurface.LastError` 报告构建失败，`Shutdown` 时用 `UnregisterSurface` 注销。配置项留在 MCM，玩法显示放在界面里。

注册在目标游戏创建前进行，不能依赖游戏进程。当前两个插件均使用重启生效模式。MCM 自身是普通托管插件加一个原生伴随库；Core 提供配置持久化，菜单插件负责 IPC 与绘制。单独复制 `Mcm.dll` 不够，必须保留其 `Mcm` 子目录。

## 第三方组件

- Dear ImGui v1.91.9b，提交 `f5befd2d29e66809cd1110a152e375a7f1981f06`，MIT：https://github.com/ocornut/imgui
- MinHook v1.3.4，提交 `c3fcafdc10146beb5919319d0683e44e3c30d537`，许可证随完整源码包提供：https://github.com/TsudaKageyu/minhook

完整源码包保留两者原始许可证；独立 MO2 成品包只包含运行所需文件。
