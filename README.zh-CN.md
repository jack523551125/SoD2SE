# SoD2SE 0.6.0-preview：双语游戏内 MCM、模块界面框架、社区招募、无限随从与幸存者成长插件

开发维护入口：[目录与资料导航](Docs/INDEX.zh-CN.md)、[研究状态与未完成项](Docs/RESEARCH-STATUS.zh-CN.md)、[原版设置菜单接入研究](Docs/NATIVE-SETTINGS-UI.zh-CN.md)、[维护与验证](Docs/MAINTENANCE.zh-CN.md)。


本包包含 `UnlimitedCommunity.dll`、`UnlimitedFollowers.dll`、`MeleeSpeed.dll`、`Mcm.dll` 和 `Roguelite.dll` 开发原型。幸存者成长具备纯逻辑的经验、升级候选和强化展示模型，但击杀归属、跨社区身份、原生属性入口、单人暂停以及原版 Character/Community UI 均未完成验证，插件会保持玩法停用。**它不是可玩的成长 Mod 发布包；当前 UI 仅是开发覆盖层，不能当作原版角色界面。**

这是《腐烂国度 2》的最小外置原生插件框架。加载器可以放在游戏根目录，直接读取并创建游戏 EXE；启动阶段不调用 Steam，也不检查发行渠道。插件本身仍只兼容清单中记录的目标版本。

文件组成：

- `SoD2SE.Loader.exe`：从自身目录及父目录寻找游戏根目录，直接创建游戏启动程序或主程序，等待实际游戏进程后加载插件。它是 Windows GUI bootstrap，正常启动不会弹出命令行窗口，独立启动时前台进程会立即返回，隐藏的后台 worker 继续等待游戏并加载插件。MO2 启动时保留原始 GUI 进程直到游戏结束，以便 MO2 跟踪运行状态。
- `SoD2SE.Core.dll`：提供版本校验、进程会话、暂停/恢复、内存补丁、上下文校验和失败回滚。
- `Plugins\UnlimitedFollowers.dll`：具体的无限随从插件，只声明两处补丁。
- `Plugins\UnlimitedCommunity.dll`：玩家社区招募插件，包含 11 处补丁描述；保留 NPC 人数门槛和真实社区人数。
- `Plugins\MeleeSpeed.dll` 与 `Plugins\MeleeSpeed\SoD2SE.MeleeSpeed.Native.dll`：四类近战攻速插件及原生动作/动画钩子。
- `Plugins\Mcm.dll` 和 `Plugins\Mcm\SoD2SE.Mcm.Native.dll`：独立的游戏内配置菜单插件及 DX11 渲染组件，同时作为所有 Mod 界面（含升级提示）的宿主。
- `Plugins\Roguelite.dll`：幸存者成长核心；数据保存在 `%LOCALAPPDATA%\StateOfDecay2\SoD2SE\Roguelite\progress.dat`，需要已验证的游戏事件能力才会在游戏内接收击杀。

发布目录中的 `SoD2SE-CommunityMods-v0.6.0-preview.zip` 是包含源码和验证资料的开发归档；给 MO2 安装的五个独立 Mod ZIP 只放运行文件和 `meta.ini`，不包含 `Docs`。框架 ZIP 只放根目录 Loader/Core/GameApi，也不包含 `meta.ini`。

托管插件 DLL 由加载器加载，并通过框架 API 修改游戏进程内存。MCM 另将自己的原生渲染组件加载进游戏进程，在游戏画面中绘制菜单。框架不会修改磁盘上的 EXE、PAK 或存档。

## MO2 启动、DLL 管理及游戏内 MCM（0.6.0-preview）

搭配 **SoD2 Support Suite 0.1.7** 使用。更新 MO2 的游戏支持插件和游戏根目录的 Loader/Core/GameApi 后，原有的 `SoD2SE.Loader` 启动项即可使用，不需要填写参数。也可选择自动提供的 `SoD2SE (MO2)`。

游戏支持插件会在每次启动前准备当前配置档的 Mod，并为加载器提供 `--mo2 --direct-main --game-exe <MO2 管理的主程序> --game-args=<游戏参数>`。Steam 版自动包含 `-steamlaunch`；它是游戏参数，用于避免游戏交给 Steam 重启。加载器直接创建 Win64 Shipping 主程序，不调用 Steam 启动接口。

MO2 模式下，加载器保留原进程及其环境，并检查实际创建的游戏 PID 是否加载 USVFS。不能附加已有游戏，也不会在子进程退出后搜索另一个脱离 MO2 的游戏进程并误报成功。日志应出现 `MO2 USVFS 环境：True` 和 `直接主程序已确认…USVFS：True`，然后是两个插件的初始化成功记录。仍需具体 Mod 本身兼容游戏；USVFS 正常不代表每个资源 Mod 都没有冲突。

自定义游戏参数可用 `--game-args="-ResX=1920 -ResY=1080"`，或环境变量 `SOD2_GAME_ARGS`；显式空值 `--game-args=` 可清除环境默认值。MO2 启动回调保留已有参数，并按 Windows 规则处理路径空格和引号。Epic/Xbox PC 变体不自动追加 Steam 参数，尚未进行实机验证。正版 Steam 版仍需要客户端已就绪；客户端未运行时，游戏自身可能退出并拉起客户端，这时应等客户端就绪后重新通过 MO2 启动。

通过 MO2 管理两个 DLL 时，只把 Loader 和 Core 放在游戏根目录，将独立 DLL Mod 压缩包安装到 MO2。在左栏分别启停，退出游戏后重启生效。若已经手动把 DLL 放进游戏 Plugins 目录，先用支持插件面板的“接管 SoD2SE 插件”迁移；保留实体副本会绕过 MO2 勾选控制。两个插件全部取消勾选后，0.3.3 允许正常启动且不应用内存补丁。同名 DLL 由 MO2 左栏优先级决定使用哪个文件；不同插件的初始化顺序仍按 DLL 文件名。

MCM `0.6.3-preview` 已移除旧的 `F1` 设置覆盖层，也不再提供手动语言选择。启用独立 MCM 包和“原版 Mod 设置入口 - Native Mod Settings Entry 0.2.4-preview”后，从游戏“设置 → Mod 设置”进入配置页。Core 每次启动检测游戏配置或 Steam 中此游戏的语言，并让入口和 MCM 自身文案跟随切换。该页仍未完成实机验收；最新运行诊断写入 `%LOCALAPPDATA%\StateOfDecay2\SoD2SE\Mcm-native-<PID>.log`。本次只更新 Core、MCM 和原版入口包，不重建或替换其他 Mod 包。

五个由 MO2 管理的 Mod 压缩包根目录包含标准 `meta.ini`；MCM 当前包版本为 `0.6.3-preview`、原版入口包为 `0.2.4-preview`，其他独立包保持原版本。框架压缩包用于游戏根目录，不包含 `meta.ini`，也不应作为 MO2 Mod 安装。如果 MO2 仍显示日期版本，请用含正确元数据的新压缩包覆盖并刷新 Mod 信息；仅修改 ZIP 文件名不会更新 MO2 版本字段。

无限随从和社区招募插件各提供启用开关、说明与本次加载状态，设置自动保存，失败会显示错误并保留旧值。两个开关均在下次启动生效；没有增加未实现的随从人数或社区人数滑块。配置保存在 `%LOCALAPPDATA%\StateOfDecay2\SoD2SE\mcm.ini`；也可通过环境变量 `SOD2SE_MCM_CONFIG` 指定文件。默认不同 MO2 配置档共用该文件。MCM 取消勾选后不加载菜单，但框架仍读取已经保存的两个插件启停设置。

MO2 独立包结构为 `Root\Plugins\Mcm.dll` 与 `Root\Plugins\Mcm\SoD2SE.Mcm.Native.dll`；支持插件需要能够把 `Root` 虚拟到游戏根目录。Loader/Core/GameApi ABI 仍为 0.6.0；本次 MCM 更新还需要替换兼容的 `SoD2SE.Core.dll`，不更新其他 Mod 包。使用 MO2 时不要同时把 MO2 管理的插件 DLL 复制到实体 `Plugins` 目录。MCM 不再提供语言选项，每次启动会跟随游戏配置或 Steam 中该游戏的实际语言，并自动选择中文或 English。详细能力、限制和开发接口见 `MCM.zh-CN.md`。

近战攻速插件四类倍率上限为 1000%（10 倍），动画速度和攻击动作使用同一倍率；配置范围和持久化行为见 `MELEE.zh-CN.md`。

幸存者成长原型的数据模型包括当前角色、等级、经验、待领取升级和八种强化；它现在由 ImGui 覆盖层绘制，尚未接入游戏原版的 Iggy/电影播放器 UI。`F2` 管成长预览和升级候选；`F1` 不再打开 MCM 设置菜单。击杀归属、稳定角色身份、属性、单人暂停和原版 UI 五项门控仍关闭，勾选 MCM 设置不会让玩法生效。**在原版角色/社区 UI 接通并完成验收前，请不要把此原型当作可玩成长 Mod 安装。**

## 模块界面框架（0.6.0-preview）

插件可以在游戏画面里拥有自己的玩法界面。插件声明内容，MCM 原生伴随库负责绘制和排版。每个插件最多注册 6 个界面，每个界面最多 24 行，全局合计 96 行；行类型有分区标题、正文、键值、进度条、列表项、按钮、提示和分隔线。默认快捷键 F2–F7；旧 MCM 菜单里的按键录制随 F1 设置覆盖层移除，尚未迁移到游戏原版设置页。

这里需要说清楚边界：这不是游戏原生界面控件，也没有接入原版 Iggy 电影播放器的导航和输入流；它是 D3D11 绘制、模仿原版观感的覆盖层。协议升级为 MCM ABI 6，v5 的固定“成长”块换成通用界面块，因此旧版 `Mcm.dll` 会被拒绝加载，框架和插件包必须同版本更新。开发接口、线程约定和测试命令见 `UI.zh-CN.md`。

## 固定版本逆向资料库

当前随从、社区、近战和 MCM 的 RVA、补丁字节、函数命名、对象字段、原生钩子和 IPC 布局集中在 `Research\StateOfDecay2\16535856`。目录只包含派生元数据和最小上下文，不包含游戏 EXE、内存转储、PAK 或原始资产。

修改补丁研究资料时，编辑 `Research\StateOfDecay2\16535856\patches.json`，然后运行：

```powershell
python .\Research\sync_research.py
python .\Research\validate_research.py
```

`sync_research.py` 会把统一补丁表导出为根目录的 `patch-manifest.json` 和 `community-patch-manifest.json`；`verify_research.py` 还会检查目标 SHA256、13 条补丁、210 个函数记录和 14 组结构体/IPC 字段是否一致。新游戏版本应新建独立的 Build 目录，不能覆盖 `16535856`。

## Core 与 Game API

`SoD2SE.Core.dll` 的运行时服务不承载版本专用 RVA、guard 或对象偏移：它提供统一 Hook Broker、标准事件总线、属性修改器堆栈、能力检测/降级、带所有权的暂停租约、事务式补丁和生命周期管理。`SoD2SE.GameApi.dll` 是 Update 38.2 的版本专用层，登记本版本 RVA、guard、补丁表和原生 Hook 元数据。加载器仍保留 SoD2 的进程名和根目录启动路径兼容逻辑；这部分属于启动壳，未混入 Core 的游戏内存服务。三个 gameplay Mod 通过能力 ID 和 Broker 请求服务，不再各自复制逆向地址；事件和配置只使用值类型与稳定 token，不长期保存 UObject 原始指针。近战策略在管理线程合成后以原子快照交给原生热路径。暂停能力未验证时，成长插件不会挂起线程或伪造暂停，会保留待领取升级并报告原因。

同一事实只在一个文件里定义：进程名、可执行名、启动器和游戏数据目录名在 `FrameworkInfo`，MCM 快捷键默认值与接受范围在 `Core\McmKeys.cs`，原生录制范围在 `Native\McmProtocol.h` 的 `Shortcut*`，近战倍率语义（25–1000、100 为原速）在 `Native\MeleeProtocol.h`，游戏版本 RVA、guard 和对象偏移只在 `Research\StateOfDecay2\16535856`。`verify_sources.py`、`verify_protocol.py`、`verify_native.py` 会拒绝这些值被第二处写死或与镜像分叉，因此改默认值只需改一处并重跑 `verify_all.ps1`。

## 使用

1. 备份存档。
2. 将压缩包内的 `SoD2SE.Loader.exe`、`SoD2SE.Core.dll`、`SoD2SE.GameApi.dll` 和 `Plugins` 文件夹放到游戏根目录。标准目录应同时包含 `StateOfDecay2.exe` 和 `StateOfDecay2\Binaries\Win64\StateOfDecay2-Win64-Shipping.exe`。
3. 双击 `SoD2SE.Loader.exe`。加载器默认直接创建根目录的 `StateOfDecay2.exe`，并等待它交接给实际游戏进程；如果完整等待窗口内仍没有游戏进程，才会尝试直接创建 `StateOfDecay2-Win64-Shipping.exe`。整个启动过程不由加载器调用 Steam，也不依赖 Steam AppID。
4. 确认日志出现 `插件已初始化：unlimited-community；状态：已启用。`。进入单人社区后使用原版招募入口；无限随从由另一个插件提供。
5. 游戏退出后内存修改自动消失。正常 GUI 启动没有控制台；需要手动中断时可用 `--console` 启动并按 `Ctrl+C`。直接结束进程时无法保证清理回调执行。

启动过程和失败原因会写入加载器同目录的 `SoD2SE-launch.log`。如果目录不可写，会改写到系统临时目录。GUI 启动失败时会弹出错误窗口并显示日志位置。

两个插件可以独立安装。只需要解除社区招募上限时，保留 `Plugins\UnlimitedCommunity.dll`；同时需要无限随从时保留两者。更换或删除 DLL 请先退出游戏与加载器。不要在已有超员社区上直接停用后继续覆盖存档；该情况尚未验证，测试时使用可恢复的存档备份。

如果游戏已经启动，可以只附加到正在运行的进程：

```powershell
.\SoD2SE.Loader.exe --attach
```

如果加载器不在游戏根目录，或自动搜索不到游戏路径，可以显式指定 EXE 或游戏根目录：

```powershell
.\SoD2SE.Loader.exe --game-exe "E:\SteamLibrary\steamapps\common\StateOfDecay2\StateOfDecay2\Binaries\Win64\StateOfDecay2-Win64-Shipping.exe"
```

`--game-exe` 始终使用直接启动模式；传入目录时会自动寻找标准目录结构。加载器不会因为版本号、发行渠道或文件来源不同而在启动阶段拒绝进程，但后续插件会对游戏主模块做 SHA256 和代码上下文检查，不匹配时只启动游戏而不写入内存。

也可以设置 `SOD2_GAME_EXE` 环境变量，或在加载器同目录创建 `SoD2SE.GamePath.txt`，第一行写入 EXE 路径或游戏根目录。需要特殊启动参数时，可以设置 `SOD2_GAME_ARGS`；默认参数为空。

调试启动时可以显式创建控制台：

```powershell
.\SoD2SE.Loader.exe --console --diagnose-launch
```

当前两个插件只支持下面这份游戏主 EXE：

```text
EBF0A73E164BAA701F74655585F262F8E38A32B1F6DC5057303489BA5B333ECE
```

游戏以管理员身份运行时，加载器也需要以相同权限运行。

加载器本身可以启动其他版本的游戏；如果版本不匹配，框架会拒绝补丁并在日志中说明原因，不会修改游戏进程。

同一个 Windows 用户会话中同时只允许一个加载器实例，避免两个加载器互相还原对方的补丁。

## 插件接口

插件只需要引用 `SoD2SE.Core.dll` 并实现 `ISoD2Plugin`：

```csharp
public sealed class MyPlugin : ISoD2Plugin
{
    public int ApiVersion { get { return FrameworkInfo.PluginApiVersion; } }
    public string Id { get { return "my-plugin"; } }
    public string Name { get { return "My Plugin"; } }
    public string Description { get { return "..."; } }
    public void Initialize(IGameSession session) { /* session.Apply(...) */ }
    public void Shutdown() { /* session.Restore(...) */ }
}
```

插件作者负责逆向并声明自己需要的 RVA、原始字节、替换字节和周围代码；框架负责 API/版本校验、安全加载、进程暂停、内存保护、写后回读和回滚。插件 ID 必须以字母或数字开头，只能包含字母、数字、`-`、`_`、`.`，最长 64 个字符。

写入补丁必须位于目标模块范围内，并且不能跨越 4 KiB 内存页；这样可以保证临时修改代码页保护后能够准确恢复原保护状态。

框架会复制并保护补丁描述，拒绝同一插件内的地址重叠、拒绝重复插件 ID，并阻止跨插件写入区与另一插件上下文校验区发生冲突。插件初始化失败时会清理此前已加载的插件，属于整体失败行为；关闭加载器时按逆序还原已加载插件。

0.3.0 在暂停目标进程后检查各线程的指令地址及活动栈中的潜在返回地址，避免线程从旧指令流返回到重写后的半段代码。若代码正在被使用，会恢复进程并短暂重试；线程状态无法检查或持续繁忙时拒绝写入。这个保守检查可能因为栈中同值指针而拒绝附加，此时回到主菜单重试。插件 API 仍为 v1。

## 构建

在本目录执行：

```powershell
.\build.ps1
```

默认输出到 `compiled`。需要 Windows .NET Framework 4.x C# 编译器、CMake 3.20+、Visual Studio 2022 C++ 工具链及 Windows SDK，固定生成 x64 文件。ImGui 和 MinHook 源码及许可证随包提供，构建不需要下载依赖。

压缩包中的源码位于 `source` 子目录，独立重编译时运行 `.\source\build.ps1`；一键验证脚本位于压缩包根目录。

运行框架自测：

```powershell
.\compiled\SoD2SE.Loader.exe --console --self-test
```

自测只加载插件元数据和测试框架契约，不连接游戏。

如果需要检查源码中的补丁表没有和清单漂移，可以运行：

```powershell
python .\verify_sources.py
```

检查发布目录是否严格匹配文件哈希清单：

```powershell
python .\verify_release.py
```

开发环境可以运行一键全量回归（会重新编译、打包、解包并检查源码、游戏 EXE、发布清单和包内自测）：

```powershell
.\verify_all.ps1
```

脚本默认使用开发机上的目标 EXE；如果游戏安装在其他位置，可传入 `-GameExePath`。这只是验证脚本读取文件，不会启动 Steam 或修改游戏文件。

如果从 MO2 启动仍没有进入游戏，先运行下面的诊断命令；它只显示路径和启动参数，不会启动游戏：

```powershell
.\SoD2SE.Loader.exe --diagnose-launch
```

诊断结果也会写入 `SoD2SE-launch.log`。如果游戏以管理员身份运行，加载器也需要以相同权限运行；启动器不会等待 Steam。

## 限制

这是固定补丁版本、单机优先的最小框架。启动器的路径解析和进程创建不绑定游戏版本，但插件的 RVA、原始字节和上下文只针对 Update 38.2 / Build 16535856。尚未实测多人模式、所有任务、车辆、角色切换和存档重载行为。无限随从只解除数量判断，仍保留重复角色、任务占用、关系和其他原版条件。社区招募插件不等于任意人数都能稳定运行，且没有改写建造者遗产等资产中的独立人数剧情条件。
