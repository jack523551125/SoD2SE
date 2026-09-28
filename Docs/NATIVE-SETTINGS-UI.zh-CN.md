# 原版设置菜单接入：离线研究与实现门槛

当前方向是将现有 MCM 设置注册表接入原版设置菜单并移除 F1 设置覆盖层。`0.2.0-preview` 已实现离线桥接并安装；用户确认原版入口可打开，但设置页内容仍为空白。MCM `0.6.1-preview` 已移除旧 F1 菜单，并增加 Iggy 回调/RPC 诊断；尚未确认空白页的剩余故障点。没有启动、注入或读取运行中的游戏。当前版本、ABI 和自动化证据以 `Research/StateOfDecay2/16535856/native-settings-mcm-bridge.json` 为准。下文早期研究门槛是历史记录，不代表当前实现状态。

## 已闭合的资源关系

固定版本 16535856 的离线导出与 PAK 原件显示：`PauseUI_BP.SettingsMovie` 指向 `SettingsUI_BP_C`，暂停页有 `DisplaySettings`、`HideSettings` 和 `GetSettingsUI`；`SettingsUI_BP_C` 的默认 `Player` 指向 `/game/art/ui/settings`。该资源是 `IggyPlayer`，带 159 行 `TextTable`、65 个 `ApiFunctions`；`SettingsUI_BP` 导出中有 18 个输入绑定函数名。`VanillaPlayerController_BP.CreateCharacterUI` 将 `CharacterUI_BP_C` 作为参数交给 `UIManagerComponent.CreateMoviePlayer`，证明工厂调用点会传入播放器类，但还不能证明它接受未烹制的 Mod 类或任意外部 SWF。具体资源散列、字段和函数名见 `Research/StateOfDecay2/16535856/native-settings-resource-chain.json`。

此前用 PAK 中的原始 `settings.uasset` 做过等长文字字节替换；那只能证明解析器能读回，不能重建资源。2026-09-25 新增 UAssetAPI 写回实验后，已证明这个固定版本的整个 Unreal 资产可以无改动逐字节往返，也能重写变长 FText 和扩展 TextTable。工具及复现方式见 `Research/tools/native_settings_asset_writer/README.zh-CN.md`。工具只写入调用方提供的新输出路径，输入散列必须精确匹配构建 16535856；输出资源只用于本机离线研究。

无改动写回为 7,618,264 字节，输入与输出逐字节相同，UAssetAPI 的 `VerifyBinaryEquality()` 通过。把 `ID_ACCESSIBILITY_AIM_ASSIST` 的源字符串替换为更长的 `Mod Settings for State of Decay 2` 后，文件增加 23 字节；新增 `ID_MOD_SETTINGS_FINAL` 后，TextTable 从 159 项增至 160 项。两个产物都由 UAssetAPI 重读，并由独立的 CUE4Parse UE4.13 读取为 `IggyPlayer`，原有 65 个 ApiFunctions 保持不变。这证明了**Unreal 包写回、变长 FText 和文字表扩展**，没有证明游戏会加载修改后的文件，也没有创建任何可见控件。

RAD 官方对 Iggy 的介绍说明，它以 Flash/SWF 兼容工具创作 UI，再由 Iggy 执行；这使“作者制作一个新 SWF”成为理论可行的内容路线。但本机没有 Iggy SDK、针对目标版本的 Unreal 4.13.2 编辑器/烹制器，也没有证明 SoD2 允许从 Mod 目录加载自定义 Iggy 资源。官方对 Iggy 的概述见 [RAD Iggy Game UI](https://www.radgametools.com/iggy.htm)。因此 SWF 作者工具并不能单独完成游戏资源接入。

## 实施前的阻塞清单（作为历史研究记录）

- `settings.uasset` 的 Unreal 包和文字表已可写回。Iggy 载荷现在也能从 20 字节封装中提取，并解析出版本、子流目录、对象指针表、6 号文字对象和 type-0 索引命令。新核对已证明三个样本中的每个对象起点都与索引累计边界恰好对应一次；但 1、3、4 号对象的字段和对象引用仍未解释，因此还不能重建 MovieClip、按钮和事件绑定。
- 65 个已声明 API 主要用于现有设置数据和页面操作，没有经证实能创建任意“Mod 设置”页或焦点控件的 API。不能从函数名推断没有隐藏机制，也不能把已有 `ApiAddKeybinding` 当作通用按钮创建器。
- `SettingsUI_BP` 的输入事件名称提供键鼠和手柄路径线索，但未确定新控件的焦点、确认、返回及关闭契约。
- 没有完成修改 Iggy 页面并绑定 Blueprint 的离线复建；也没有证明能向运行中的播放器插入组件。当前缺少把 `McmRegistry` 连接到原版页面的可信传输端。
- 游戏安装目录包含 `StateOfDecay2/Plugins/IggyPlugin/Binaries/Win64/iggy_w64.dll`。静态枚举得到 204 个导出，包含 `IggyPlayerCallFunctionRS`、`IggyPlayerCallMethodRS`、`IggyPlayerSetFocusRS` 与 `IggyValueRef*`；名单与 DLL 散列见 `iggy-dll-exports.json`。这些名字指出下一条研究路线，但仍缺少与当前播放器的对象、调用参数及组件创建契约。DLL 的存在本身不解除上述门槛。

以上是桥接实现前的历史结论。2026-09-25 后续工作已加入原版入口、回调桥接和 Mod 设置资源；当前用户已确认入口可打开，但页面内容仍空白。F1 设置覆盖层已从新 MCM 原生 DLL 移除；`UiSurface` 仍由宿主用于玩法界面。

这是桥接实现前的历史研究建议。当前需要用新 DLL 生成的 Iggy hook/RPC 日志定位用户报告的空白页面，再修复并由用户实机确认原版设置页内容、输入和保存行为。

## 2026-09-25：静态路线核查结果

本轮把暂停菜单的 Blueprint 打开/清理链也加入自动提取和回归测试：`PauseUI_BP.DisplaySettings` 从图入口 `1075` 跳到 `713`，依次取得玩家控制器、查找 `UIManagerComponent`，再以固定的 `/game/ui/settingsui_bp` 调用 `PushMoviePlayer`，返回播放器保存到 `SettingsMovie`。该播放器的 `Closed` 委托绑定到 `OnSettingsClosed`；`HideSettings` 从入口 `906` 跳到 `657`，将 `SettingsMovie` 清空。最后这一步只是清理引用，不能解释为通用播放器关闭、返回键或焦点处理契约。角色页的另一个原版调用点把固定的 `/game/ui/characterui_bp` 交给 `CreateMoviePlayer`。这些调用点都使用游戏内既有类；没有找到可据此证明任意 Mod 类能够加载的证据。

本机工具盘点覆盖 `PATH`、Epic Games 安装目录、`C:\UE`、`E:\UE`、Downloads 和 Local Programs；未发现目标版本 UE4.13.2 编辑器、烹制器或 Iggy 创作 SDK。新的 UAssetAPI 实验补上了 Unreal 包写回和 CUE4Parse 独立重读，但不能据此声称 Iggy 控件图可编辑或游戏可加载新增页面。游戏目录里的 `iggy_w64.dll` 导出仍缺少参数与控件创建契约；固定 EXE 原生包装的直接调用、参数读取辅助例程和未命名内部目标仍不能解释外部资源路径规则与 Mod 播放器生命周期。

本轮还用 Capstone 对固定 EXE 做了只读指令核对（SHA256 `EBF0A73E164BAA701F74655585F262F8E38A32B1F6DC5057303489BA5B333ECE`）：`CreateMoviePlayer` (`0xA9D3A0`) 调用两个参数读取辅助例程和 `0x7CB060`；后者调用 `0x7CC2E0`、`0xA2F090`，并按对象字段 `+0x10`、`+0x88`、`+0x90` 做元数据比较后返回指针或空值。一个 `PushMoviePlayer` 包装 (`0xAFC220`) 调用 `0x7DFB80`，该例程复用 `0x7CC2E0` 并再次检查对象元数据。`GetMovieSourcePathInfo` (`0xAC1870`) 转入 `0x74CB20` 等无符号辅助函数；`PassInputToIggy` (`0xAF1D10`) 转入 `0x759C60`。逐函数范围和调用边保存在 `Research/StateOfDecay2/16535856/native-ui-runtime-candidates.json`，可由 `Research/tools/analyze_native_ui_runtime.py` 复核。这闭合了机器码调用边，但辅助例程名称、完整参数/返回契约、被检查的具体类、路径拼接来源和输入焦点语义仍未解析，不能据此推断 Mod 页面可被实例化。

截至 2026-09-25，Iggy 载荷不再是完全未知的黑盒：`NormalExport.Extras` 有 7,557,310 字节，其中 20 字节是 Unreal/Iggy 封装；解出的流为 7,557,290 字节，Iggy 版本 `0x900`、平台字节 `[1,64,1,3]`。设置电影有三个子流：一个 7,535,744 字节的电影流，以及两个类型 0 的索引子流（其类型标签依据 JPEXS `IggySubFileEntry`）。对象指针表有 508 项，类型分布为 `1:49`、`3:353`、`4:33`、`6:73`；头部相对指针目标已按固定版本读取并校验边界。可选的附加对象表指针在三个样本中均为哨兵值 `1`，所以未发现附加表。只解读了 73 个 6 号文字对象的索引、范围、长度与摘要，未把原文写入报告。索引流解析器按 JPEXS 的命令语法读取每条流的表和长度命令：设置电影两条索引流分别含 14,084 / 3,807 条命令，累计偏移终点为 4,369,624 / 7,535,744 字节；角色电影两条索引流终点为 1,925,812 / 2,460,464，暂停电影索引流终点为 1,012,616。新核对发现设置/角色电影的两条索引流使用完全相同的索引表定义，对象起点按地址分成互不重叠、先后递增的两组；设置电影第二条流首个命令到达第一条流终点，角色电影则晚 4 字节。暂停电影单条索引流覆盖全部对象。由此确认索引流与地址区段的关系，但分流的运行时用途仍未知。

本轮继续把索引表连到对象记录：不只是每个对象起点都恰好是一个累计边界，紧随该起点的索引命令也为每个对象唯一选中一个带字段元数据的表项。固定样本中类型 1/3/4/6 的候选记录长度分别是 80/72/88/104 字节，三部电影内的每种类型都保持同一字段偏移/类型码布局。三个样本的对象目录目标均按文件顺序排列；508、541、156 个候选记录都能匹配已知布局且互不重叠。104 字节的类型 6 表项与 JPEXS `IggyText` 布局精确一致，包括偏移 `0x60` 的相对字符串指针；三个样本全部 189 个类型 6 对象的指针都准确落在对象起点后 104 字节处，解析到有效的 UTF-16 文本。这同时验证了类型 6 记录末端与字符串数据起点的关系。类型 1、3、4 目前只有按字节记录的候选布局，尚未解释其字段含义，不能据此重建显示关系。

对索引元数据类型码 2 的字段，解析器另外按 `字段偏移 + 64 位字段值` 分类目标位置。三部电影中的类型 1、4 字段 `0x48` 和类型 6 字段 `0x60` 均落在候选记录末端；类型 6 的 `0x38` 字段则落在记录之后的间隔区。类型 3 的 `0x40` 字段在设置、角色、暂停电影中分别有 346/353、381/386、107/110 个目标落入记录间隔区，其余目标落在记录末端。该现象为后续解释间隔数据提供了可重复的字节级线索，**仍不证明这些字段是显示对象、按钮或事件引用**。详细映射和边界条件已进入 `Research/StateOfDecay2/16535856/native-settings-iggy-compatibility.json`，校验器会核对三部电影的固定计数，可由 `Research/tools/inspect_iggy_movie.py` 重算。JPEXS 对索引元数据采用 `(local offset, type code)` 对，写入器为 Text 定义了 104 字节布局，见 [IggyIndexParser.java](https://github.com/jindrapetrik/jpexs-decompiler/blob/version26.3.0/libsrc/ffdec_lib/src/com/jpexs/decompiler/flash/iggy/streams/IggyIndexParser.java)、[IggyIndexBuilder.java](https://github.com/jindrapetrik/jpexs-decompiler/blob/version26.3.0/libsrc/ffdec_lib/src/com/jpexs/decompiler/flash/iggy/streams/IggyIndexBuilder.java) 和 [IggyText.java](https://github.com/jindrapetrik/jpexs-decompiler/blob/version26.3.0/libsrc/ffdec_lib/src/com/jpexs/decompiler/flash/iggy/IggyText.java)。

继续检查类型 3 的 `0x40` 目标后发现，三个样本的 849 个目标开头都能读成两个小端 64 位数 `(1, 1)`；其中 846 个目标距下一个对象起点正好 16 字节。每部电影各有一个例外，目标后到下一个对象起点的距离分别为 196,672、260,632 和 120,512 字节。报告只保存这两项数值模式和距离计数，不保存原始区块；目前只能确认重复的字节布局，不能命名其用途，也不能把它当作 UI 引用结构。

现在把类型 3 的 `0x38` 与 `0x40` 一起按对象配对：`0x38` 目标在设置电影 353/353、角色 384/386、暂停 110/110 个对象中落到候选记录末尾，其余两个角色对象落在记录间隔；`0x40` 目标则分别有 7/353、5/386、3/110 个落在记录末尾，其余落在间隔。所有 849 个 `0x40` 目标都以 `(1,1)` 两个小端 `u64` 开始；其中 846 个目标离下一个目录起点 16 字节，三个长间隔例外与上文数值一致。由 `0x38` 目标到 `0x40` 目标的候选区间在 849 个对象上都满足起点和长度按 8 字节对齐；15 个区间为空，其余 834 个非空区间每个电影内的散列分别有 303、329、106 个不同值。这个双指针关系支持“两个候选数据边界”的结构假设，但还没有独立证据证明它们构成数组、图元、子对象表或显示关系。解析器记录位置、长度分布、包络分类和散列，不保存原始区间字节；合成双对象测试验证了边界测量不会把标记数据误收进候选区间。

类型 4 的 `0x48` 目标也做了有界载荷识别：设置、角色、暂停电影中的 61 个目标都以完整 zlib 流结束，另外 9 个目标包含长度前缀及有效 JPEG 起止标记。解析器只记录包络类别和数量，不保留或导出图像数据。这确认类型 4 记录后有压缩/图像数据，但尚不能据此给 Iggy 对象本身命名或还原其显示关系。

新增了类型 1 字段 `0x48` 的候选尾随区统计：49 个设置对象、37 个角色对象、11 个暂停对象的相对目标都落在 80 字节候选记录末尾；从该目标到下一个对象目录起点的区域长度分别为 216–816、288–3,360、288–696 字节。97 个区域起点和长度都按 8 字节对齐，且每个区域的 SHA-256 都不同。现有解析器只能把这些区间归为非零不透明数据；“下一个对象起点”只是有界扫描终点，尚未证明该区间属于类型 1 对象，更未解出子结构。测试覆盖了合成类型 1 记录和不泄漏尾随原始字节的摘要；固定版本计数由 `validate_research.py` 校验。

对照 JPEXS FFDec 26.3.0 后发现，它虽声明支持 64 位 Iggy，但对应版本源码中的顶层对象解析器只处理类型 6（TEXT）和 22（FONT），遇到其他类型会抛出 `Unknown item kind`。目标游戏电影实际大量使用 1、3、4 号类型，因此这个通用工具不能重建本游戏的显示对象树。它的 Iggy→SWF 转换仅生成字体、EditText 和 ABC 项，帧数固定为 1 并标记为待修；反向写入要求字体和文字数量与原件相同，而写回器会重建电影流和索引，不保留未识别的游戏对象。故即使改好一段文字，也不能用该工具安全往返整部电影，更无法靠它新增按钮。JPEXS 官方也列出“有些 Iggy 变体无法处理”的限制，见 [官方功能列表](https://github.com/jindrapetrik/jpexs-decompiler/wiki/Features)、[已知问题](https://github.com/jindrapetrik/jpexs-decompiler/wiki/Known-problems)、[26.3.0 对象解析源码](https://github.com/jindrapetrik/jpexs-decompiler/blob/version26.3.0/libsrc/ffdec_lib/src/com/jpexs/decompiler/flash/iggy/IggySwf.java)、[转换源码](https://github.com/jindrapetrik/jpexs-decompiler/blob/version26.3.0/libsrc/ffdec_lib/src/com/jpexs/decompiler/flash/iggy/conversion/IggyToSwfConvertor.java) 与 [写回源码](https://github.com/jindrapetrik/jpexs-decompiler/blob/version26.3.0/libsrc/ffdec_lib/src/com/jpexs/decompiler/flash/iggy/IggyFile.java)。

继续核对 `IggyFile` 与 `IggyIndexBuilder` 后发现：JPEXS 的 `parseEntries()` 里读取 type-0 索引的调用被注释掉；写回时则移除原有全部索引子流，再依据其序列化的 SWF 数据生成单条索引流。独立解析器如今能把索引命令选中的记录布局与对象类型交叉核对；JPEXS 本身仍没有解码这些 SoD2 自定义对象或显示关系，目标设置电影的两条原始索引流也没有被它证明能够无损保留或重建。因此 JPEXS 仍不能作为 SoD2 原始 Iggy 电影的无损往返器。来源见 [IggyFile.java](https://github.com/jindrapetrik/jpexs-decompiler/blob/version26.3.0/libsrc/ffdec_lib/src/com/jpexs/decompiler/flash/iggy/IggyFile.java) 和 [IggyIndexBuilder.java](https://github.com/jindrapetrik/jpexs-decompiler/blob/version26.3.0/libsrc/ffdec_lib/src/com/jpexs/decompiler/flash/iggy/streams/IggyIndexBuilder.java)。

这段记录的是早期 Iggy 研究状态。后续已完成固定版本设置资源的可复现修改、原版分类入口、`McmRegistry` 桥接和离线解析验证；页面内容仍存在用户可复现的空白问题，运行时显示与设置持久化尚未通过验收。

新增了固定散列保护的 `patch_iggy_text.py`，并在设置电影索引 82 上完成一次 17 个 UTF-16 代码单元的等长替换。独立解析器成功重读输出；载荷仍为 7,557,290 字节，只有字符串区间的 17 个字节值发生变化，所有已报告的对象、索引和布局字段保持一致。实验只证明已解码文本可被定长原位修改并保持结构可解析；它没有新增或改动显示对象、按钮、回调、焦点或导航，也没有验证游戏是否加载该输出。原文和替换文本均不写入研究报告，散列与偏移记录在 `native-settings-iggy-compatibility.json`。

## 复现与验证

从项目根目录运行 `Research/tools/analyze_native_settings_chain.py` 和 `Research/tools/probe_native_settings_asset.py`。前者输入本机 PAK、`u4pak.py` 和最终完整 JSON 导出；后者另外需要临时构建的 Ue4Export/CUE4Parse 程序。两者都要求调用方提供本地文件，不分发原版资产。再运行 `python -m unittest discover -s Research/tools -p 'test_*.py'`、`python Research/validate_research.py`、`python verify_research.py` 和 `python verify_sources.py`。


固定版本 Iggy 逐对象目录（2026-09-25）：新增 `Research/StateOfDecay2/16535856/native-settings-iggy-object-catalog.json`，包含 `settings`、`character`、`pause` 三个电影的 1,205 个对象偏移、候选记录长度、索引表映射及 type-code-2 相对字段目标。`Research/tools/export_iggy_object_catalog.py` 使用三份固定载荷 SHA-256 重新生成该目录；导出不包含文本、图像或对象原始字节。目录提供下一步结构对照的稳定对象编号，但类型 1/3/4 仍未被语义解码，也没有建立 UI 父子关系、按钮回调或输入焦点图。


Iggy 候选对象链接（2026-09-25）：新增 `native-settings-iggy-object-links.json` 与 `Research/tools/analyze_iggy_object_links.py`，在 kind-1 记录尾区和 kind-3 双指针候选区间中按有界 4 字节步长扫描有符号相对值，只保留同时满足字段、位移、目标 8 字节对齐且精确落在同电影对象起点的候选链接。三个样本找到 1,455 条：kind-1 区 86 条全部指向 type-4 对象；kind-3 区 1,369 条指向 type-1/3/6 对象，其中 +0x30 槽位出现 592 次。除设置电影的一条 kind-3 前向候选外，其余 1,454 条均向后链接。kind-1 范围终点和 kind-3 边界虽可复现，字段语义仍未确认。未按父子、贴图或形状关系解释这些链接。

固定版 Iggy 运行时接口分析（2026-09-25）：`native-settings-iggy-runtime-api.json` 绑定到已安装 DLL 的散列，离线追踪 11 个导出接口及其可达控制流。焦点枚举函数遍历现有对象并写出焦点记录，未发现明确命名的显示树插入导出；通用脚本调用接口仍可能提供另一条路径，但内部调用目标尚未解码为可用的页面修改契约。因此此结果缩小了接口范围，没有证明能创建按钮、追加设置入口或替换原版 UI。候选对象链接是否由运行时解析器消费也尚未确认。


## 2026-09-25：原版设置页桥接预览

现有 MCM 注册页已经通过保留原始 ABC 绑定的定点字节码修改，映射到固定版本原版菜单，并通过 Iggy callback ABI 连接原生 MCM 注册表。新 MCM 包已移除 F1 设置覆盖层。用户确认入口可打开，但设置页仍空白；当前新日志会区分回调未挂钩、RPC 未到达、参数异常和结果路径失败。运行时布局、焦点、输入和配置持久化仍待修复与验收。
