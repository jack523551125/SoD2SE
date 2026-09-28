# 游戏内界面框架（SoD2SE 0.6.0-preview）

这个框架让插件在游戏画面里拥有自己的界面，而不是把玩法数据塞进 MCM 配置页。插件只描述「这一页有哪些行」，绘制、排版、输入拦截、快捷键和窗口外壳由框架统一负责，所以所有 Mod 的界面看起来是同一套东西。

## 它是什么，不是什么

已实现：

- 插件注册最多 6 个界面，每个界面最多 24 行、全局合计 96 行。
- 行类型有分区标题、正文、键值、进度条、列表项、按钮、提示和分隔线；文字有 6 种语义色调。
- 每个界面可绑定单键或 Ctrl/Alt/Shift 组合键，默认从 F2 起自动分配，避开已经占用的按键。旧 MCM 设置覆盖层已移除，因此设置界面中的快捷键录制暂未迁移。
- 界面可以在插件里主动打开/关闭，也可以由玩家用快捷键打开、用 Esc 关闭；两种来源互相不打架。
- 按钮会回调到发布该行的插件，并带修订号校验。
- 界面文字跟随 MCM 的语言设置，插件可用 `McmLocalizedText` 提供中英两套文本，也可以只提供一种。

尚未实现，不要在说明里含糊：

- 没有接入游戏原生的 Iggy 电影播放器 UI。界面由 MCM 的原生伴随库用 D3D11 在游戏画面上绘制，风格和排版模仿原版菜单（深色半透明面板、灰白文字、琥珀色高亮），但它不是原版菜单本身，也不能插入原版菜单的导航层级。
- 不是 DX12/Vulkan 渲染，没有手柄菜单导航，界面打开时不暂停世界。
- 不提供任意尺寸、任意控件、图片、动画或自定义布局。需要这些能力必须先补协议，不能靠插件端绕过。

因此，幸存者成长页目前只是覆盖层开发原型，未达到用户要求的原版角色/社区 UI 标准，不作为可玩成品交付。离线资产中虽然能看到 `CharacterUI_BP` 与 `ShowSkills` 等名称，但还没有经过验证的资产构建、运行时接入或原版输入路径。

成长系统快捷键默认 F2；旧 F1 MCM 设置覆盖层已移除，设置入口计划使用游戏原版“设置 → Mod 设置”（该页内容仍有空白故障，尚未验收）。有待领取升级时，F2 打开三选一，再按 F2 回到成长总览；没有待领取升级时，F2 开关成长总览。三选一不会因为经验升级或候选已保存就自动弹出。Esc 关闭当前页面，待领取候选仍保留。

MCM 插件页中的“本次运行”只报告插件是否成功初始化。幸存者成长因原版 UI、击杀归属、稳定幸存者身份、属性和暂停能力未验证，目前玩法保持停用；勾选设置不会绕过这些门控。

## 最小示例

插件在 `Initialize` 里注册，在 `Shutdown` 里注销。构建回调会在框架每次发布前重新执行，所以里面的数值永远是当前的，不需要额外的刷新机制。

```csharp
using System;
using SoD2SE;

sealed class SamplePlugin : ISoD2Plugin
{
    UiSurface screen;
    int kills;

    public void Initialize(IGameSession session)
    {
        var ui = UiRegistry.Current;
        if (ui == null) return;
        screen = ui.RegisterSurface("sample.progress",
            new McmLocalizedText("样本进度", "Sample Progress"),
            new McmLocalizedText("击杀与统计。", "Kills and statistics."),
            Build);
        screen.ActionRequested += OnAction;
    }

    void Build(UiSurface surface)
    {
        surface.Section("统计");
        surface.KeyValue("击杀", kills.ToString(), null, UiTone.Accent);
        surface.Progress("下一级", 40, 100, "40 / 100");
        surface.Row("近战攻速", "x1.15", "已选 3 次", UiTone.Positive);
        surface.Button("重置统计", "reset");
        surface.Note("按 Esc 返回游戏。");
    }

    void OnAction(string action)
    {
        if (action == "reset") kills = 0;
    }

    public void Shutdown()
    {
        if (screen == null) return;
        screen.ActionRequested -= OnAction;
        UiRegistry.Current?.UnregisterSurface(screen.Id);
        screen = null;
    }
}
```

## 行类型

| 方法 | 用途 | 说明 |
|---|---|---|
| `Section(label)` | 分区标题 | 琥珀色标题加分隔线 |
| `Text(text, tone)` | 正文 | 单行普通文字 |
| `KeyValue(label, value, description, tone)` | 键值 | 左侧标签，右侧数值 |
| `Progress(label, current, maximum, value, description)` | 进度条 | 整数，`maximum <= 0` 时显示空条 |
| `Row(label, value, description, tone)` | 列表项 | 用于「已获得的强化」这类清单 |
| `Button(label, action, description)` | 按钮 | 动作标识不能为空，玩家点击后回到 `ActionRequested` |
| `Note(text, tone)` | 提示 | 换行显示的说明文字 |
| `Separator()` | 分隔线 | 空行 |

色调：`Normal`、`Positive`、`Warning`、`Danger`、`Muted`、`Accent`。`Section` 和 `Button` 固定使用强调色，避免每个插件各写一套配色。

每个界面最多 24 行，再超出的行由 `UiSurface` 直接丢弃，不会写入协议，所以请把最重要的信息放在前面。

窗口尺寸由宿主决定：玩法界面为 960×960，设置面板为 1080×820，两者都会按实际显示分辨率收缩。内容超过可视区域时出现滚动条，插件不需要自己排版。

## 打开、关闭与握手

`Open()` 和 `Close()` 是电平请求：调用一次表示「希望打开」，之后靠 `IsOpen` 读真实状态。宿主每处理一次请求就回写 `seenRevision`，因此玩家用快捷键或 Esc 关掉界面后，插件不会被自己的旧请求重新打开。

游戏窗口没有焦点时（例如玩家切到桌面），宿主不会消费请求，而是把它留在待处理状态：切回游戏后界面才出现。这样一次「打开」不会丢在后台。

- `IsOpenRequested`：插件当前的意愿。
- `IsOpen`：宿主真实状态。
- `SetModal(true)`：界面打开时不被设置面板或其他界面替换。升级三选一这类必须让玩家看到的内容应设为模态。
- `SetPriority(value)`：为后续的多界面排序预留，当前宿主只保证「同时只显示一个界面」。

## 快捷键

`SetShortcut(key, modifiers)` 使用 Windows 虚拟键码。可选值与 MCM 相同：F1–F12、字母、数字、Tab、PageUp/PageDown、Home/End、Insert/Delete，可加 Ctrl、Alt、Shift。`Alt+F4` 与 `Esc` 保留。

`SetShortcut(0, 0)` 表示「这个界面没有自己的按键」，用于由其他功能带入的界面，例如幸存者成长页。重复的按键会被拒绝并抛出异常，注册表里的按键不会改变。

玩家可以在 MCM 的「界面快捷键」区重新录制任意界面的按键，设置写入 `%LOCALAPPDATA%\StateOfDecay2\SoD2SE\ui.ini`。环境变量 `SOD2SE_UI_CONFIG` 可指定其他文件。

默认分配顺序是 F2、F3、F4、F5、F6、F7，会跳过 MCM 已占用的按键。

## 按钮与动作

按钮的 `action` 是插件自定义的字符串。玩家按下后，宿主把动作连同该界面的修订号回传；`UiRegistry.TryInvokeAction` 会校验修订号，如果点击到达时插件已经重建过界面，这次点击被丢弃，不会作用到新的行上。

回调在框架发布线程执行。回调里要改自己的状态就先加锁，不要在回调里做耗时操作，热路径不要调用 `Snapshot()`。

## 升级提示与归属界面

三选一提示是唯一的宿主内置模态。`UiRegistry.SetChoiceOwner(surfaceId)` 声明哪个界面拥有这个提示，玩家按升级提示键时，宿主会打开该界面并重新显示被关掉的提示；`RequestChoicePrompt()` 可以让插件的按钮把提示重新调出来。

提示的内容来自 MCM 的卡片协议（等级、经验、三张卡片），界面框架只负责显示和输入。

## 语言

`UiRegistry.Language` 返回 MCM 当前语言；`LanguageChanged` 可以监听运行中的切换。界面标题和副标题用 `McmLocalizedText` 提供两种文本，行的文字由插件在构建回调里自行选择。框架不强制插件提供翻译，缺少翻译时插件应回退到一种默认文本。

## 线程与性能

构建回调在框架发布时执行，MCM 插件的后台线程每 50 毫秒发布一次，也就是每秒约 20 次。回调要保持短小：只做取值和拼字符串，不要在回调里读存档、遍历大集合或加长锁。

不要长期保存游戏对象原始指针。界面只显示插件已经计算好的值。

## 打包与版本

- 界面依赖 MCM 插件及其原生伴随库；没有 MCM 时 `UiRegistry.Current` 为 null，插件应静默退化为无界面。
- 当前协议为 MCM ABI 6。`Native/McmProtocol.h` 里的 `static_assert` 和 `Plugins/Mcm/Mcm.cs` 的偏移常量必须同步修改，任何一侧单独升级都会被拒绝。
- 框架（Loader/Core/GameApi）与插件包必须同版本更新。MO2 面板显示的版本来自压缩包里的 `meta.ini`。
- `SoD2SE-Framework-MO2-*.zip` 放在游戏根目录，不作为 MO2 Mod 安装，也不包含 `meta.ini`。插件包安装到 MO2，包内是 `Root\Plugins\...`。

## 测试

```powershell
.\build.ps1 -OutputDirectory .\compiled
.\Tests\run_ui_smoke.ps1 -BuildDirectory .\compiled
.\Tests\run_mcm_integration_smoke.ps1 -BuildDirectory .\compiled -NativeRenderTest .\Native\build\Release\McmRenderTest.exe
```

第一个测试覆盖注册、快捷键分配与持久化、行上限、构建回调、动作派发和宿主可见性握手，不启动游戏。第二个测试会创建真实 D3D11 窗口并短暂抢占键盘焦点约 20 秒，验证宿主能打开插件界面、绘制内容并把按钮动作回传给插件；它不使用游戏进程。

自动化测试只能证明协议和绘制路径按设计工作，不能代替实机验收。界面在真实游戏里的可读性、缩放和输入冲突仍需人工确认。
