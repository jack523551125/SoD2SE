# State of Decay 2 Update 38.2 逆向资料库

这是 SoD2SE 当前随从、社区、近战和 MCM Mod 使用的固定版本研究资料整合目录。这里的 JSON 是唯一可编辑逆向资料源；Game API、原生 companion 和兼容性清单都只能消费这里确认过的地址、guard、函数和布局。运行时 C# 表和原生常量是受校验的镜像，不能作为第二套资料库维护。

目标程序：

- Update 38.2 / Steam Build 16535856
- Unreal Engine 4.13.2（来自安装目录 `Engine/Build/Build.version`）
- x64 `StateOfDecay2-Win64-Shipping.exe`
- SHA256：`EBF0A73E164BAA701F74655585F262F8E38A32B1F6DC5057303489BA5B333ECE`

目录内容：

- `native-mod-settings-entry.json`：0.1.1-preview 原版入口与返回按钮的离线编译证据；该入口导航曾由用户实机确认。
- `native-settings-mcm-bridge.json`：0.2.0-preview 原版设置页到 MCM 注册表的离线桥接、Iggy ABI、资源重建、测试与安装证据；新增设置页未实机验收。复现见 `Docs/NativeModSettingsEntry.zh-CN.md`。
- `native-ui-screen-adapters.json`：固定角色、社区、HUD 和地图四个原版 Iggy 页面的 ActionScript API、可复用展示入口、角色页单字节 Iggy/UAsset 往返验证、地图分块 ABC 格式与各自能力边界；不代表任意控件注册或实机运行时调用已验证。
- `native-character-trait-pool-probe.json`：角色页特质池的单字节改写静态实验；已回写固定版 UAsset 并经 CUE4Parse 解析，没有制作 Mod 或实机验证。
- `target.json`：目标程序身份和研究范围。
- `patches.json`：无限随从、无限社区招募的统一补丁登记表；每条记录有稳定 ID、所有者、RVA、原始/替换字节和 guard 上下文。
- `functions.json`：社区招募门槛、随从数量门槛、近战动作/动画钩子、FName 全局和 AI 态度函数。
- `structs.json`：只记录已使用的对象字段、IPC 布局和位含义，不声称是完整 Unreal 结构体定义。
- `roguelite-capabilities.json`：记录幸存者成长 Mod 所需击杀归属、持久身份、属性和暂停能力的证据状态；其中未验证项不会进入运行时 Hook。
- `GameApi/StateOfDecay2GameApi.cs`：由上述资料实现并由 `verify_sources.py` 对照的版本专用 API；Core 不包含这些 RVA 和对象偏移。

资料消费者和验证入口：

- `GameApi/StateOfDecay2GameApi.cs`
- `Plugins/UnlimitedFollowers/UnlimitedFollowers.cs`、`Plugins/UnlimitedCommunity/UnlimitedCommunity.cs`、`Plugins/MeleeSpeed/MeleeSpeed.cs`、`Plugins/Mcm/Mcm.cs`、`Plugins/Roguelite/Roguelite.cs`
- `Native/MeleeNative.cpp`、`Native/MeleePolicy.h`、`Native/McmProtocol.h`
- `patch-manifest.json`、`community-patch-manifest.json`
- `Tests/PluginMemorySmoke.cs`、`Native/MeleeTest.cpp`、`verify_recruitment.py`

根目录中的两个 patch manifest 是兼容性导出文件，方便旧校验脚本和 Mod 包使用。修改补丁资料时，应先修改本目录的 `patches.json`，再运行：

```powershell
python .\Research\sync_research.py
python .\Research\validate_research.py
```

验证脚本会检查目标 SHA256、补丁字节、RVA、插件归属、函数引用和结构体偏移，并确认根目录导出清单没有漂移。`verify_sources.py` 检查版本专用 Game API 中实际编译的补丁表；三个 gameplay Mod 只通过 Hook Broker 请求能力。

Core 提供统一 Hook Broker、标准化事件总线、属性修改器堆栈和能力降级状态。事件只传递稳定对象 token 与值，不把 UObject 原始指针交给 Mod；近战原生热路径只读取原子策略快照，配置合成在管理线程完成。

本目录只保存派生的逆向元数据、最小代码上下文和测试说明。没有保存游戏 EXE、内存转储、PAK、原始资产或完整反编译数据库。

版本边界：RVA、全局地址、对象偏移、函数前导字节和结构体字段只对上述 SHA256 有效。新游戏版本应创建新的目标目录，例如 `Research/StateOfDecay2/<new-build>/`，不要覆盖本目录。

## 幸存者成长事件与函数清单（静态提取）

`functions.json` 在原有记录基础上加入了从固定版本可执行文件静态提取的 UFunction 原生实现，覆盖死亡与击杀、伤害归属、敌人分类、幸存者身份、角色属性、成长与等级、暂停与会话；本轮也登记了 Character/Community UI 和 Iggy 电影播放器管理路径的静态候选符号。

提取方法不启动、不注入、也不读取运行中的游戏进程：

1. `tools/extract_native_pairs.py` 扫描调用者提供的 UE4 `FNameNativePtrPair` 表（`{const char* NameUTF8; FNativeFuncPtr Pointer}`），输出名称到函数 RVA 的派生 JSON。本机目标文件得到 8692 条映射。
2. `tools/analyze_selected.py` 从该 JSON 筛选已知候选，使用 `.pdata` 记录函数入口与前导 guard，并对 E8/E9 相对引用做原始字节初筛。本机结果包括 152 个名字、166 个注册项；相对引用数量只是筛查结果，不能当成已解码的调用图。
3. 可复用 PE 解析器 `tools/pe_static.py` 和两个命令行脚本只依赖 Python 标准库，不内置目标程序、不连接进程。工具结构与资产字符串扫描测试为 `python -m unittest discover Research/tools -p 'test_*.py' -v`。

例如在 PowerShell 中可把派生文件写入临时目录：

```powershell
$gameExe = "E:\SteamLibrary\steamapps\common\StateOfDecay2\StateOfDecay2\Binaries\Win64\StateOfDecay2-Win64-Shipping.exe"
$analysis = Join-Path $env:TEMP "sod2-static-research"
python .\Research\tools\extract_native_pairs.py $gameExe --output (Join-Path $analysis "pairs.json")
python .\Research\tools\analyze_selected.py $gameExe --pairs (Join-Path $analysis "pairs.json") --output (Join-Path $analysis "selected.json")
```

这些函数以 UE4 反射注册表映射为依据。`analyze_selected.py` 对 E8/E9 做的是原始字节候选筛查，不能代替指令解码，也不能据此断言完整调用关系。名称到 RVA 的映射是静态确认；运行时语义、责任方传播、对象生命周期和暂停所有权仍未验证，所以 `roguelite-capabilities.json` 中对应能力保持停用，不会安装任何运行时 Hook。

## 扩展系统的逆向候选队列（静态提取）

`research-domains.json` 把现有资料尚未覆盖、但值得继续研究的功能按主题归档：丧尸生成与围攻、载具状态与修理、库存与耐久、设施/前哨/资源、任务/据点关系与社区事件。每个主题包含固定版本原生注册名候选、当前离线资产树中找到的相关资源路径、可读字符串观察、待回答问题和提升证据等级的条件。它是研究待办，不是运行时 API 清单；全部主题都保持 `candidate-only`。

这批跨系统候选最初来自 8692 条名称到函数 RVA 的静态注册映射。2026-09-24 对本地 35 个 PAK 的 105,357 个 `.uasset` 载荷全部做了离线可读字符串扫描，解压检查 8,169,066,939 字节，3,798 个文件命中通用检索词且没有解压错误。随后以 `ReadScriptData=true` 的临时 Ue4Export/CUE4Parse 构建完成全部 105,357 个包的 JSON 导出和解码，得到 494,268 个对象、16,579 个带字节码函数和 209,339 个顶层表达式，最终运行零警告。为兼容空 `UEnum.Names` 和未初始化的导入元数据，仅在外部临时分析副本加了两个空值保护；没有把 parser 修改带入 Mod。全包 Blueprint 调用清单分别记录招募/社区筛选的 654 条引用、167 个目标，以及击杀/经验/事件/身份/属性筛选的 148 条引用、23 个目标。报告见 `community-full-uasset-cooked-audit.json`、`community-full-uasset-blueprint-call-analysis.json` 和 `community-full-uasset-roguelite-call-analysis.json`。这些筛选只覆盖序列化字节码调用表达式，不代表动态分发或运行时可达性。

`tools/analyze_native_bodies.py` 是新增的可选指令级静态分析器。它从唯一函数目录和候选队列匹配精确目标 EXE，再使用 Capstone 按 x64 指令边界解码有 `.pdata` 范围的已登记原生函数体，记录函数体中的直接/间接调用，并对击杀、伤害、感染分类入口，以及明确列出的经验与角色身份入口生成经指令解码确认的直接调用交叉引用。派生结果保存在 `native-body-analysis.json`，逐条保留注册名、函数 RVA、`.pdata` 范围、解码状态、直接调用位置和候选主题。没有 `.pdata` 范围但落在可执行节的注册地址会标成 `executable-rva-without-unwind-range` 并跳过解码；这表示工具缺少可靠函数边界，不代表该地址无效。安装可选的 Capstone 5.0.7 后可重新生成：

当前固定版报告匹配到 282 个登记项，其中 243 个按 `.pdata` 边界完成解码，39 个缺少可用的 unwind 范围而跳过；没有目录函数或主题候选无法匹配，也没有注册地址落在已知函数中段。对幸存者成长最相关的例子是：`OnZombieKilled`（RVA `0xAEFD50`）直接调用内部 RVA `0x253ED0`；`GetCharacterWhoHitMost`（`0xAB30C0`）调用 `0x3BE4E0`；`GetHealthMax`（`0xABB3B0`）调用 `0x1D6620`；两份 `AwardExperience` 实现（`0xA8C600`、`0xA8C680`）分别调用 `0x19EF80`、`0x1CF910`；`GetSurvivorByID`（`0xACC930`）调用 `0x27EEF0`；`GetLegacyCharacterRecordFromId`（`0xABEA60`）还调用 `0x74AA40`、`0x5424A0` 和 `0x1C4FC0`。这些是反汇编确认的直接调用目标，但内部 RVA 尚未命名或解出参数语义，不能据此断定事件责任方、角色稳定 ID 或属性结算规则。函数体报告由 `roguelite-capabilities.json` 引用；所有相关运行时能力继续保持停用。

### 击杀归属、经验发放与角色身份：当前能证实的静态证据

共享定向分析以 93 个击杀、伤害、感染分类、经验发放、角色身份、任务事件和社区招募登记项为起点，扩展到 160 个目标。早期 `native-body-analysis.json` 的有界调用者子分析解码 836 个调用者函数体、观察 3686 条直接调用边，并对 7 个高扇出目标限流。为补齐这项缺口，新增 `native-full-pdata-direct-xrefs.json`，用 Capstone 解码全部 259,728 个可执行 `.pdata` 函数范围，覆盖 11,816,829 条指令，并完整枚举到所选 160 个 RVA 的 109,914 条直接 CALL 和 1,012 条尾跳。独立 E8/E9 字节扫描与指令结果逐目标核验：109,914 个 E8 候选全部匹配已解码 CALL，未匹配数为 0；E9 有 424 个未匹配字节候选，且没有落在部分解码函数体内。随后又对 8 个与击杀/经验链有关的匿名函数或链式分段候选地址单独执行全量 `.pdata` 跟进和原始 E8/E9 核验，报告在 `roguelite-native-followup-direct-xrefs.json` 及其 `-audit.json`。这仍不是全程序调用图；间接/虚调用、ProcessEvent、委托、未纳入目标集的调用和语义仍未解析。

对上述 8 个匿名候选 RVA 还扫描了全部可执行 `.pdata` 指令中的非分支立即数/RIP 相对地址，并在排除 `.pdata` unwind 表后检查非可执行节中的原始 VA-qword 与 RVA-dword 模式，结果见 `roguelite-native-followup-address-references.json`。没有找到非分支指令地址引用；`.rdata` 中有 4 个候选 RVA 的 RVA32 字节模式（`0x1CF9CA`、`0x1E53AB`、`0x2BBD8B`、`0x461993` 各 2 处），另有一个指向可执行代码 RVA `0x276E80` 的 VA qword 候选。后续 CHAININFO 解码确认 `0x1CF9CA` 是 `0x1CF910` 函数链中的分段起点，不是独立函数入口；原始地址模式不等于已证明的回调表或可达性证据。

目前最有用的静态链路是：

- `OnZombieKilled` 包装入口（`0xAEFD50`）调用内部目标 `0x253ED0`。对该内部目标的直接调用扫描确认两处：包装入口的 `0xAEFDC3`，以及无原生注册名的函数入口 `0x3C92E4`（调用点 `0x3C92EA`）。
- `AuthOnZombieKilled`（`0xA8B590`）调用 `0x3DBFE0`；确认的调用者是包装入口和无注册名函数 `0x3292C7`（调用点 `0x3293CF`）。
- `AddZombieKilled`（`0xA835C0`）调用 `0x1CDD10`；除包装入口外，还从无注册名函数 `0x19F558` 被调用。
- `GetCharacterWhoHitMost`（`0xAB30C0`）调用 `0x3BE4E0`；无注册名函数 `0x29A690` 也调用该内部目标。对匿名入口做全量 `.pdata` 跟进后，确认 `0x2BBD8B–0x2BC1DB` 函数体以 6 处直接调用引用 `0x29A690`；`0x2BBD8B` 本身没有直接 E8/E9 上游，但 `.rdata` 中出现两处其 RVA32 字节模式。该模式没有解析出函数表名称或执行语义。
- `AddOrUpdateAttacker`（`0xA82090`）调用 `0x3B4D80`。`GetHasBloodPlague` 的内部目标 `0x1D5210` 有 23 个已解码直接调用点，但这些调用者尚未映射到类名或具体游戏事件。
- 两个 `AwardExperience` 原生入口（`0xA8C600`、`0xA8C680`）分别调用内部目标 `0x19EF80`、`0x1CF910`。`0x19EF80` 还被 `0x1CF910` 函数链中的分段（起点 `0x1CF9CA`，调用点 `0x1CFB1F`）和匿名候选 `0x461993` 调用；`0x1CF910` 则被 `0x1E53AB`、`0x276E80` 调用。不能把 `0x1CF9CA` 计作独立函数或独立调用者。这些机器码关系证明经验实现存在多个调用路径，但没有证据表明这些路径就是丧尸击杀奖励。
- 无注册名函数 `0x276E80` 的指令顺序显示：先在调用点 `0x276F11` 通过内部查询目标 `0x27EEF0` 按 ID 取得幸存者；若结果非空，再于 `0x276FBA` 调用经验实现 `0x1CF910`。它在可执行 `.pdata` 中没有直接 E8/E9 上游，但 `.rdata` RVA `0x3244AC8` 有一个值为 `0x140276E80`、落在可执行节的 VA-qword 候选。这把 ID 查询与一种经验实现连接起来，却没有揭示该数据表的用途、调用者类型、奖励来源或该 ID 是否跨社区持久。
- `GetSurvivorByID`（`0xACC930`）调用 `0x27EEF0`，该内部目标有 65 个已确认直接调用点；传入记录和遗产记录入口分别涉及 `0x749FA0`、`0x74AA40`、`0x5424A0`、`0x1C4FC0` 等内部目标。它们证明代码中存在 ID 查找和记录转换路径，不能证明 ID 的命名空间、稳定范围或跨社区/遗产池保持不变。

为避免只看调用边，新增 `roguelite-kill-experience-disassembly.json`，逐指令解码 14 个固定入口/匿名函数体及其 26 个 CHAININFO 关联 `.pdata` 分段。除 `KilledZombie`（`0xADA660`）在 `0xADA796` 处执行 `call qword ptr [r10 + 0xb00]` 外，新纳入的 `AuthAwardExperience`（`0xA8AFD0`）、两个 `AwardExperience` UFunction（`0xA8C600`、`0xA8C680`）和辅助函数 `0x19E900`、`0x19EF80`、`0x1CF910` 共揭示了更多直接与间接调用边；匿名 `0x3292C7` 仍会读取对象偏移 `0xB88` 的字节并将其传给 `0x3DBFE0`。更新后的摘要为 128 条直接调用和 10 条间接调用。记录只保留 RVA、操作数和偏移，不给未知对象/方法补猜测名称。所检查的 `OnZombieKilled`、`AuthOnZombieKilled` 和击杀辅助函数体里仍没有发现直接调用上述经验 UFunction；这仅排除所选函数体中的直接路径，不排除虚调用、委托、ProcessEvent 或更长的跨系统链路。

`roguelite-experience-blueprint-call-contexts.json` 为全包序列化调用清单中的 37 个经验授权调用补上了参数 AST 与相关局部变量赋值，覆盖 7 个资产、13 个 Blueprint 函数。34 个 `AuthAwardExperience` 调用中，近战辅助函数的四个调用按 `Leathal` 布尔参数在 Close、Blunt、Bladed、Heavy 的 Lethal/Nonlethal 标签间选择；远程辅助函数把 `Shooting_Zombie_` 前缀与 Attack Type 字节分支（0→Nonlethal、1→Lethal）拼成名称。人类近身处决明确传入 `MyDaytonHumanCharacter` 与战斗/潜行标签；若干僵尸反应函数传入 `ReactAttacker` 与 `Explosive_Zombie_Lethal` 或 `Explosive_Zombie_Nonlethal`，`OnDelayedDeath` 调用则使用 Lethal 标签。另有一个 `CharacterSkill:AwardExperience` 消耗品调用及两个作弊菜单调用。以上表明授权函数被多个技能和动作奖励路径共用，不能直接当作“每只丧尸死亡时奖励一次成长经验”的统一事件；参数名含义、原生授权/网络语义和死亡去重仍未闭合。

新增 `roguelite-experience-reward-table.json` 对 cooked `ExperienceRewards` DataTable 的 28 行 `ExperienceReward` 记录进行解析，并把 Blueprint 参数中 16 个唯一经验标签候选全部匹配到表行。表中射击丧尸致命奖励每个射击技能定义 50 点、非致命 5 点；潜行击杀对 10 个 Wits/专长定义各给 50 点；爆炸丧尸致命标签给 Chemistry 2 点、Munitions 和两个相关专长各 3 点，非致命各 1 点。近战标签则按 Close、Blunt、Bladed、Heavy 分配 10 点到适用技能行，未适用的专长行为 0。**这些是技能经验，不是幸存者成长 Mod 规划的等级经验。**表中没有按血疫、Feral、Screamer、Bloater、Juggernaut 单独设置普通成长经验行；这只说明该表如何分配技能 XP，不证明其他原生奖励系统也没有这些分类。

关键 UE 原生包装入口自身没有发现直接 `E8` 调用者；它们可能经 `ProcessEvent`、虚调用或委托分发，所以这个结果不能解释为“函数没有被调用”。对八个匿名函数或链式分段候选地址的全量直接调用跟进确认，唯一有来边的是 `0x2BBD8B` 到 `0x29A690` 的 6 次调用；`0x3C92E4`、`0x3292C7` 及四个经验相关候选地址（其中 `0x1CF9CA` 是 `0x1CF910` 的 CHAININFO 分段起点）均无 `.pdata` 内直接 E8/E9 上游。地址模式扫描发现若干 `.rdata` RVA32/VA-qword 候选，但未识别表布局或动态分发。无注册名函数的类归属、参数含义、事件先后顺序、权威端和重复触发行为仍未确认。尤其不能把通用 `AwardExperience` 当成唯一击杀 Hook；静态扫描显示其实现有多个尚未命名的调用者。成长系统的击杀奖励能力继续保持停用。

#### 敌人类别、血疫变种与去重风险

此前的字符串扫描线索现已用全量 cooked JSON 做了结构化补查，摘要见 `roguelite-enemy-classification-static.json`。`AllZombieTypes` 的序列化 `DisplayNames` 顺序为 Generic、Screamer、Bloater、Juggernaut、Feral、All，因此 `NewEnumerator0–5` 有相应的序号映射候选；导出器的 `Names` 映射却把 5 个条目都写成 0，故该映射仍标作候选。全包只找到 6 个 `AllZombieTypes` 引用（`NewEnumerator3` 两处、`NewEnumerator5` 四处），都位于人类 AI BehaviorTree 资源中，说明它服务于目标选择线索，不能直接用作经验类别。

结构化的 `ZombieTypeDataTable` 有 17 行，并由 `ZombieTypeStruct` 的 `DaytonZombieCharacter` 类字段连接到 Blueprint 类路径。表中明确有普通 `Plague` 行，以及 `BpJuggernaut`、`BpBloater`、`BpScreamer`、`BpFeral` 四个血疫特殊感染者类路径。全包默认对象清点另发现 `Zombie_Plague_C` 和 `Zombie_PlagueAmbush_C` 都把 `IsPlagueZombie` 默认设为 `true`；6 个血疫特殊 Blueprint 构造脚本（包括 Bp 表中的四种，以及 Bloater Ambush/Walker）明确把 `DaytonZombieCharacter.bIsBloodPlagueZombie` 写为 `true`。这两个标记是不同字段，不能假设别名或互斥。

新增的 `ZombieVariants` 外观数据表共 28 行，其中 `MalePlague01`、`FemalePlague01`、`MaleFatPlague01` 三行序列化为 `EZombieVariantType::Plague`。通用丧尸 `ZombieCharacter_C:SetSpecificCharacterAppearance` 以实例字段 `ZombieVariant` 查询这张表，并比较 `ZombieVariantType` 的底层字节；字节等于 4 的分支会把 `IsPlagueZombie` 与 `bIsBloodPlagueZombie` 都设为 `true`。固定版本 EXE 的原生枚举注册链独立强静态推断 `Slow=0`、`Unique=1`、`Fast=2`、`Armored=3`、`Plague=4`，因此支持 byte 4 分支对应 Plague；由于最终 setter 是未命名虚调用，这仍是静态推断而非运行时确认，证据见 `zombie-variant-enum-native-registration.json`。全包命中两个标记的 47 个资源里，另有通用构造、复制/初始化函数和这段变体分支共 11 条蓝图赋值。以上均为静态证据，不证明死亡事件或 XP 逻辑实际读取这些字段，也不证明每种血疫变体对应的奖励。

新增的 `zombie-plague-flag-native-name-references.json` 对固定 EXE 的全部 259,728 个可执行 `.pdata` 函数范围扫描了这两个字段名：发现 `IsPlagueZombie` 5 个、`bIsBloodPlagueZombie` 3 个直接指令引用，所选 14 个击杀/经验函数及其 26 个 CHAININFO 分段内没有这两个字段的直接名称引用。四个 `IsPlagueZombie` 命中来自含 `GameTelemetry\Private\EventTypes.cpp` 源路径以及 `ZombieId`、`Killed`、`DealerId`、`CauseOfDamage*` 等字段的序列化样式函数；`bIsBloodPlagueZombie` 命中则包括与 `DeadState`、`ZombieMapInstanceId`、`DeadBodyInventory` 并列的死亡状态/属性登记样式字段簇。这些线索指向遥测和死亡状态记录，不证明它们就是 XP 的输入对象；按数值偏移的读取以及反射、虚调用或委托路径仍可能存在。

`MGR_AmbientSpawner` 默认对象另列出 9 个 `EBoonsBanesZombieType` 的 BaseDensityReductions 类别，这是 Boons/Banes 密度配置的独立分类。`AllZombieTypes`、遭遇表、`ZombieVariants`、Boons/Banes 类别与经验奖励类别没有得到静态一一映射；血疫变种的伤亡事件链与奖励分类仍未解出。

资产扫描还在 `VanillaPlayerController_BP`、`DaybreakPlayerController_BP`、`CommunityUI_BP` 和 `Map_BP` 中找到 `CharacterID`、`CharacterIdentifier`、`CharacterId`、`RequestedCharacterID`、`SetActiveCharacterID` 及待办理角色 ID 的字段/函数名；原生表另有当前幸存者 ID 设置/清除、按 ID 查询幸存者、取得传入/遗产角色记录的函数。它们是角色身份机制的静态线索，不是跨社区持久 ID 契约。

一次死亡可能同时经过 `OnZombieKilled`、`AuthOnZombieKilled`、`KilledZombie`、`MulticastZombieKilled`、`AddZombieKilled` 等不同层。离线资产中 `DaybreakGameMode_BP` 也出现 `OnZombieKilled` 字符串，但不能据此外推到普通战役。静态资料没有给出每条事件在单次死亡中的调用顺序或唯一事务 ID，因此重复计奖风险仍属阻塞项。具体资产符号、证据等级和限制记录在 `roguelite-capabilities.json` 的 `static_findings` 中；这些能力仍保持停用。

`functions.json` 已移除原先 166 个没有来源说明且全部为零的 `direct_callers` 字段，避免把未经定义的数字误读为已验证调用关系；可复核的直接调用证据统一查看此处引用的 `native-body-analysis.json`。

```powershell
python -m pip install -r .\Research\tools\requirements.txt
$gameExe = "E:\SteamLibrary\steamapps\common\StateOfDecay2\StateOfDecay2\Binaries\Win64\StateOfDecay2-Win64-Shipping.exe"
python .\Research\tools\analyze_native_bodies.py $gameExe
```

分析器检查 EXE SHA256，只读本地文件，不启动或附加游戏进程。结果只表示按明确边界解码得到的直接机器码调用边，不是完整调用图；虚调用、`ProcessEvent` 分发、所属 UObject、参数结构、对象生命周期和运行时事件顺序仍未解析。`native-body-analysis.json` 是可再生成的派生证据，不替代 `functions.json`、`research-domains.json` 或 `roguelite-capabilities.json`。缺少边界或语义证据的能力继续保持禁用。

## 原版角色/社区 UI 与 Iggy 播放器静态调查（2026-09-23）

离线 `CharacterUI_BP.uasset` 字符串扫描得到 `AttachedCharacter`、`AttachedCommunity`、`ShowCommunitySkills`、`ShowSkills`、`SetAttachedCharacter` 等名称；`CommunityUI_BP.uasset` 可见 `SetSelectedCharacter`、`ShowCharacterOverlays` 和 `UpdateCharacterOverlayAnchorPoints`。两者还引用 `/Script/IggyPlugin`、`IggyPlayer`、`IggyValue` 与 `CommonUIMoviePlayer`。固定版本原生注册表登记了 `GetCharacterUI`、`SetAttachedCharacter_Native`、`ShowSkills_Native`、`OnCommunityUIShownNative`，以及 `CreateMoviePlayer`、`GetMoviePlayerByClass`、`PushMoviePlayer`、`GetMovieSourcePathInfo`、`PassInputToIggy` 等播放器管理和输入路径候选。

`VanillaPlayerController_BP.uasset` 和 `DaybreakPlayerController_BP.uasset` 都含 `CharacterIggyPlayer`、`CommunityIggyPlayer` 与 `HUDMoviePlayer` 字段名，表明角色页与社区页由预配置的 Iggy 播放器对象承载。下一步如果继续做原版 UI，需要查清这些播放器的资产引用/替换规则，或证明能向现有电影发送新的数据与动作；单纯创建另一个播放器还没有 UI 资源可展示。

这些证据确认原版角色/社区界面接入 Iggy 播放器；它们没有证明可以在运行时给现有电影增添页面或控件。部分注册地址是经对象虚表转发的反射分发桩；`CreateMoviePlayer` 的参数处理还调用了一个内部类检查助手。名字和地址不能证明存在外部电影资源加载接口，也不能证明调用时的角色上下文、播放器对象寿命或导航焦点规则。完整的资产导入/导出结构、Iggy 电影资源、可复现的资源构建链、运行时挂接和手柄导航仍未验证，因此 `sod2.ui.native-progression` 继续关闭。

当前离线导出树仍是 1100 个 `.uasset`：其中 41 个含 `/Script/IggyPlugin`、24 个含 `CommonUIMoviePlayer`、39 个含 `IggyPlayer`、24 个含 `IggyValue`。这只描述当前拿到的导出树，不代表完整游戏资源。另一次直接读取本地 PAK 的定向扫描覆盖了 5597 个相关 cooked `.uasset` 的可读字符串，外加 1013 个路径名指向招募/社区界面的资源。早期扫描没有发现独立 `.iggy`、`.swf`、`.gfx` 或 `.umap` 资源；后续确认 Iggy 电影嵌在 `IggyPlayer` 导出的 `NormalExport.Extras` 中，详见下方 2026-09-25 更新。独立资源未找到并不代表嵌入载荷不存在，也不代表已经具备可编辑构建链。

2026-09-24 完整导出后继续核对了原版设置资源：`PauseUI_BP.SettingsMovie → SettingsUI_BP_C → Art/UI/settings`，并从 `VanillaPlayerController_BP.CreateCharacterUI` 的 Blueprint 字节码确认它将 `CharacterUI_BP_C` 传给 `UIManagerComponent.CreateMoviePlayer`。Iggy DLL 静态导出表共 204 个符号，含 `IggyPlayerCallFunctionRS`、`IggyPlayerCallMethodRS`、`IggyPlayerSetFocusRS` 和 `IggyValueRef*`。这些是新的研究入口，仍未证明能载入自定义播放器类或插入新控件。

原版 `settings.uasset` 的早期固定长度文字探针由独立 CUE4Parse 再读成功；当时尚未完成完整 uasset 重建。2026-09-25 的后续 UAssetAPI 实验已证明无改动逐字节往返、变长 FText 写回和 TextTable 扩展，并由 CUE4Parse 独立读取；这些离线实验仍未证明游戏会加载替换文件。Iggy 资源提取和对象目录解析结果见 `native-settings-iggy-compatibility.json`；当前没有被验证的控件重建或运行时替换链路。相关报告：`native-settings-resource-chain.json`、`native-settings-text-probe.json`、`native-settings-iggy-compatibility.json`、`iggy-dll-exports.json`；界面接入门槛见 `Docs/NATIVE-SETTINGS-UI.zh-CN.md`。

2026-09-25 追加设置菜单图调用链：`DisplaySettings` 图入口 `1075` 跳到 `713`，之后依次获取玩家控制器与 `UIManagerComponent`，用固定 `/game/ui/settingsui_bp` 调用 `PushMoviePlayer` 并将结果写入 `SettingsMovie`；`Closed` 委托绑定到 `OnSettingsClosed`。`HideSettings` 入口 `906` 跳至将 `SettingsMovie` 设为空的 `657`。报告的 `settings_navigation` 字段由 `analyze_native_settings_chain.py` 从固定版本完整导出提取，并在 `test_analyze_native_settings_chain.py` 中以合成输入验证结构异常会被拒绝。角色页对 `CreateMoviePlayer` 的已知调用也只传原版 `/game/ui/characterui_bp`。当前可用导出器只读，搜索的本机位置未发现兼容 UE4.13.2 内容构建器或 Iggy SDK；因此既未验证自定义电影加载，也未构造可交互按钮。所有 UI 宿主能力保持静态候选/禁用，不据此启用或迁移 MCM。

Capstone 指令核对以固定目标散列 `EBF0A73E164BAA701F74655585F262F8E38A32B1F6DC5057303489BA5B333ECE` 为准：`CreateMoviePlayer` RVA `0xA9D3A0` 到 `0x7CB060`，后者再调用 `0x7CC2E0` 与 `0xA2F090`，并在对象/类元数据表上进行比较；`PushMoviePlayer` 的一条包装路径 `0xAFC220 → 0x7DFB80` 复用 `0x7CC2E0` 并检查对象元数据。`GetMovieSourcePathInfo` RVA `0xAC1870` 调用 `0x74CB20`、`0x1B540D0` 和 `0x10AB810`；`PassInputToIggy` RVA `0xAF1D10` 调用 `0x759C60`。函数范围、寄存器基址内存位移和调用边见 `native-ui-runtime-candidates.json`，生成器为 `Research/tools/analyze_native_ui_runtime.py`。由于内部例程没有符号，且反射参数帧布局/运行时播放器对象契约未确认，只把这些作为调用边和字段访问证据，不命名为外部资源加载器或通用输入 API。

2026-09-25 Iggy 载荷与编辑器兼容性：新增 `extract-iggy`，针对散列锁定的 `Art/UI/settings.uasset` 验证 20 字节封装长度、`Ig\n\xED` 签名及 64 位标记后导出 7,557,290 字节 Iggy 流。设置、角色和暂停电影都使用版本 `0x900`、平台字节 `[1,64,1,3]`；设置电影包含一个 type-1 电影子流和两个 type-0 索引子流、508 个对象指针，其中类型 1、3、4、6 分别有 49、353、33、73 项。`inspect_iggy_movie.py` 现在把每个对象起点映射到唯一索引布局，确认三个样本中的 508/541/156 个候选记录均按文件顺序排列且不重叠。设置/角色电影的两条索引流使用相同表定义，匹配对象起点被分成地址递增且不交叉的区段；设置电影第二条流从第一条的累计终点开始，角色电影相差 4 字节；暂停电影由单条流覆盖全部对象。三个样本共 189 个类型 6 文字对象的字符串目标都在对象起点后 104 字节处，成功解析为 UTF-16；849 个类型 3 字段 `0x40` 目标的前两个 64 位值均为 `(1,1)`，其中 846 个目标与下一个对象起点相距 16 字节，每部电影各有一个落入长尾区域的例外。类型 4 字段 `0x48` 的 70 个目标中，61 个是完整 zlib 流，9 个是带有效 JPEG 起止标记的长度前缀数据。这些是字节布局观察，不是对象语义或显示关系；索引分流的运行时用途仍未知。23 项自动化测试覆盖索引解析、对象/布局对应、索引流边界、相对字段分类、类型 1 候选尾随区、类型 3 和类型 4 目标摘要、文字指针、损坏结构和边界检查；报告不保存文本原文或图像数据。

新增类型 1 字段 `0x48` 候选区域统计：设置、角色、暂停电影分别有 49、37、11 个相对目标落在 80 字节候选记录末尾；从该目标到下一个对象目录起点的范围长度分别分布在 216–816、288–3,360、288–696 字节，97 个候选区的起点与长度都按 8 字节对齐，每段数据的 SHA-256 均唯一，且都只确认是非零不透明数据。这个界限用于有界分析，不证明尾随区域属于类型 1 对象，也没有解码它们的结构。报告只保存汇总、长度与哈希，不保存区域原始字节；新增测试覆盖了合成类型 1 样本。

JPEXS FFDec 26.3.0 源码的 Iggy 顶层对象解析只处理类型 6（文本）和 22（字体），遇到其他类型会抛出 `Unknown item kind`；本游戏三个对照电影中的 1、3、4 类型都无法由该解析器重建。它的 Iggy→SWF 转换只构造字体、EditText 和 ABC，帧数固定为 1；SWF→Iggy 只更新既有字体、文字和一段 ABC，并拒绝字体/文字数量变化；写回会重建电影子流，所以不能保留未识别的游戏对象。项目报告锁定 JPEXS 源码 commit、下载包散列及目标 Iggy 对象统计。JPEXS 的官方功能列表虽列出 64 位 Iggy 支持，其已知问题也指出有些 Iggy 变体无法处理；这项“支持”不能等同于对 SoD2 显示树的完整编辑器。来源与边界记录见 `native-settings-iggy-compatibility.json`。

继续追踪 `IggyFile`/`IggyIndexBuilder` 后补充了索引行为：`IggyFile.parseEntries()` 中调用 `IggyIndexParser.parseIndex` 的代码被注释；`updateFlashEntry()` 写回时移除原有全部 type-0 索引子流，再依据重新序列化的电影生成一条索引流。JPEXS 索引构建器的命令确实表示长度、填充及类型数组并推进累计写入位置，但它没有证明目标游戏两条索引流与对象/字段的对应关系；因此它不能作为原始 SoD2 Iggy 流的无损往返器。

另新增散列锁定的 `Research/tools/patch_iggy_text.py`：它要求输入 payload 与目标文本摘要都匹配，只允许 UTF-16 长度不变的替换，并在独立解析器重读后比较对象、索引和文本元数据。固定设置电影的一次离线实验只改动文本索引 82 的 34 字节范围（其中 17 个字节值实际变化），文件总大小不变，结构报告不变；原文和替换文本都没有保存在报告中。该实验仅验证已知文本的安全原位替换，不构造按钮或回调，也不代表游戏能加载修改后的资源。测试位于 `Research/tools/test_iggy_text_patch.py`，实验散列、偏移及限制记在 `native-settings-iggy-compatibility.json`。

## 玩家社区招募数量上限：静态阶段结论（2026-09-24）

本轮完成了全部载荷扫描和全部 `.uasset` 的无警告 JSON 导出，但仍不能据此声称“全部静态语义已经解决”。完整本地 PAK 索引共含 120,780 条资源记录、105,357 个 `.uasset` 文件条目。直接扫描 35 个 PAK 中相关逻辑根目录的 5,597 个 `.uasset`，检查 125,344,430 字节；按路径筛选的 1,013 个招募、人口、玩家社区、社区 UI 候选检查 36,412,570 字节；另对全部 105,357 个 `.uasset` 载荷检查 8,169,066,939 字节，3,798 个命中通用关键词、0 个解压错误。全量扫描报告为 `community-all-assets-global-scan.json`；关键词命中解析摘要为 `community-all-string-hit-cooked-analysis.json`；全量结构化导出审计为 `community-full-uasset-cooked-audit.json`。修正导出器空值处理后，全部 105,357 个包均生成 JSON，BOM-aware 解码错误为零，导出器警告为零，退出码为 0；全量语义统计覆盖 494,268 个对象、16,579 个字节码函数和 209,339 个顶层表达式。完整调用 census 和限制见 `community-full-uasset-cooked-audit.json` 及关联报告。所有 JSON 仅为离线研究摘要，不分发或修改游戏资产。

固定 EXE 的原生登记表共扫描 8692 对名称/函数指针，本轮将招募单人/多人容量查询、真实人数查询、软上限查询和新增角色入口的六个 UFunction 原生注册项补进唯一 `functions.json`。再从已确认的入口向内追踪，并对指定 RVA 的整个可执行映像搜索候选调用点、逐个用 Capstone 按 x64 指令边界确认后，得到 9 个关键内部目标、89 个直接 CALL 和 1 个到角色记录新增函数的尾跳。目标函数都落在 `.pdata` 边界内，候选调用点没有未解析的函数边界：

| 固定版本路径 | 目标 RVA | 已确认直接 CALL | 结论 |
| --- | ---: | ---: | --- |
| 单人容量检查 `CanAddCharacter` | `0x276360` | 3 | 包含原生包装入口的调用 |
| 多人容量检查 `CanAddCharacters` | `0x2763A0` | 2 | 包含原生包装入口的调用 |
| 共享社区人数统计 | `0x27D150` | 58 | 被大量非招募代码共用，不可用伪造人数绕过招募 |
| 招募剩余名额查询 | `0x27ADC0` | 2 | 独立于单人/多人资格检查 |
| 社区软上限查询 | `0x281540` | 2 | 与硬招募门槛分开 |
| 实际新增幸存者 | `0x290630` | 2 | 包含 `TryAddCharacter` 原生包装入口 |
| 新增幸存者记录 | `0x290710` | 12 | 另确认 1 个直接尾跳 |
| 恢复被放逐角色 | `0x290F50` | 1 | 另有单独的人数门槛 |
| 转移幸存者 | `0x2919D0` | 7 | 路径里还有单独的人数门槛 |

补丁以玩家社区位 `0x08` 识别适用范围，并保留原拒绝标志 `0x02` 与其他已检查条件；真实人数查询没有被改写。资产也确认，普通对话分别有“社区已满”“正在任务中”“不能招募”状态；遗产电台将“社区已满”和“遗产池无人”分开。因而 Mod 的静态实现边界是移除查明的玩家社区人数门槛，不降低 NPC 上限、不跳过任务/关系/资格限制，也不伪造全局人口。

对 248 个任务、社区与故事资源先做了原始 FName/基础属性扫描，再用临时构建的 Ue4Export/CUE4Parse（启用 `ReadScriptData`）解析 cooked exports，得到 131 个 `MissionAsset` 包、2323 条任务记录、419 个带字节码函数和 7394 个顶层字节码表达式。另对 1013 个路径候选和 487 个额外的精确符号候选做了 JSON 导出；1500 个候选全部匹配到输出，JSON 解码错误为零。该定向候选包中解析出 305 个函数、4802 个顶层表达式；筛选后有 213 条、76 个不同的社区/招募相关 Blueprint 调用引用。后来又对全量扫描命中的 3,798 个资源做了同类结构化解析：共 67,209 个对象、5,170 个字节码函数、59,087 个顶层表达式和 497 条筛选后的调用引用（125 个目标），没有缺失、解码错误或导出器警告。该筛选调用集中有 3 条 `Enclave:TryAddCharacterRecord` 引用，分别位于 CinematicFunctionLibrary 的 `AddNPCToCommunity` 和 CheatMenu 的两个函数；没有直接容量包装函数的筛选命中。它们只是序列化 Blueprint 调用标记，不能证明实际运行、战役可达性、全部调用者或未解析资源中不存在其他调用。`DynamicPawnSpawner:GetCurrentPopulationMax` 的 10 条命中属于生成/人口系统，不当作玩家社区招募门槛。全量导出初期出现过 `CommunityScreenLayoutMode.uasset` 空值警告；修正临时导出器空值保护并重跑后，该资源成功导出，最终全量审计和全局关键词命中集均为零警告。临时解析器改动未进入任何 Mod。

这 163 条真正解析出的 `CommunityMembers` 条件中，82 条是 `LessOrEqual`、32 条 `Greater`、7 条 `Less`、4 条 `NotEqual`、1 条 `GreaterOrEqual`，另外 37 条没有序列化 `Comparison`。扩展到所解析的 266 个 `CommunityMissionCondition` 对象后，共有 40 条缺失该字段；另外 226 条显式值全是非 `Equal` 比较。随后对全部 105,357 个导出 JSON 按 `Type=CommunityMissionCondition` 做全包清点：315 个对象分布在 19 个包中，269 个显式序列化 `Comparison`，46 个没有；其中 43 个属于 `CommunityMembers`，另有 1 个 `CommunityOutposts` 和 2 个缺少 `ComparisonStat`。对同一导出树增加的定义搜索没有找到名为 `Default__CommunityMissionCondition` 的默认对象、`EMissionConditionComparison` 的 cooked `UserDefinedEnum` 定义或名为 `CommunityMissionCondition` 的 cooked `UserDefinedStruct` 定义。进一步追踪固定 EXE 中枚举类型名的唯一代码引用，沿 Windows x64 `.pdata` `CHAININFO` 片段解码原生注册路径：注册器把含 6 个比较项和 `_MAX` 的名称表传给枚举构造辅助函数，并将显式数值数组置空；辅助函数在该空值分支中把当前循环索引写入每条 16 字节枚举记录，再交给虚拟 setter。因此 `Equal=0`、`Greater=1`、`GreaterOrEqual=2`、`Less=3`、`LessOrEqual=4`、`NotEqual=5`（`_MAX=6`）是强静态推断。由于 setter 的虚函数实现未符号化，这仍保留为强静态推断；更关键的是，这只能给出枚举值，不能确定 `CommunityMissionCondition` 缺省 `Comparison` 的类默认值，所以缺字段条件语义仍未知。新补的固定 EXE UTF-16 名称清点找到 3 处 `UCommunityMissionCondition`；其中一处去掉 `U` 前缀的宽字符串被指令 `0xA2F92B` 引用，位于 `.pdata` 范围 `0xA2F8F0–0xA2F987`，该函数随后调用 `0x11A4680` 并传入类注册相关静态参数。这证明了一个原生类名使用点，但没有显示缺省 `Comparison` 的赋值，也不能代替类默认对象证据。证据报告为 `mission-condition-enum-native-pointer-evidence.json`、`mission-condition-enum-native-registration.json` 和 `community-mission-condition-native-name-xrefs.json`；全包属性清点为 `community-full-uasset-mission-condition-census.json`。

新解码的 `UCommunityMissionCondition` 初始化链位于 `0xFC7C40`：它先调用 `0xF32160` 准备 `Value`、`Comparison` 属性，再调用该类的注册例程；同一链随后以 `0x30` 注册 `ComparisonStat`。按指令传给属性偏移构造器的候选偏移为 `Comparison=0x28`、`Value=0x2C`、`ComparisonStat=0x30`，类注册大小参数为 `0x38`。另一个 `UMissionCondition` 注册例程传入 `0x28` 大小参数。字段名、偏移和初始化顺序构成强静态布局推断；属性所有者和 C++ 继承关系没有符号化类型信息直接证明。它仍没有恢复 CDO 或构造函数中的默认值，因此缺少 `Comparison` 的条件语义继续未知。报告为 `community-mission-condition-native-layout.json`。

从每条 Mission 记录的显式事件索引出发，沿 `EventIndexes` / `ElseEventIndexes` 追踪，发现 34 条记录能连到 `RecruitCharacter` 事件，共 48 次记录级事件命中；有 5 条记录中的 6 个条件事件可达 `CommunityMembers` 条件。Builder 遗产其中四条 `≤11`、一条 `≤10` 分支连到发往 `PlayerCommunity` 的招募事件；第六条 `Value=11` 的条件也连到招募，但其 `Comparison` 缺失，不能认定条件方向。它们是任务数据里的独立限制，当前原生资格补丁不会移除这些任务分支条件，因此不能宣称所有剧情招募路径都可超过 12 人。

另对 131 个已解析 `MissionAsset` 的顶层 `Events` 数组做了 `EventName` 清点：共有 2954 条非空名称记录，按包相加有 1155 个包内唯一名称；64 个包在多条记录中复用名称，其中 433 组在同一事件类型内重复，43 个名称跨事件类型复用。比如 `Mission_Complete_Rewards` 在同一任务资产的 `StandardMissionRewards` 类型中重复六次，`Event_Loot_Item` 同时出现在添加与移除地图标记的事件类型里。这证明 `EventName` 不能当作唯一节点 ID；重复可能是有意分组，也可能只是标记，现有静态证据不足以确认语义，因此分析器只统计和保留名称，不以相同名称连边。

全包事件生命周期字节码筛选报告 `community-full-uasset-mission-event-lifecycle-call-analysis.json` 共找到 18 条调用引用、7 个目标，其中 `MissionCastingComponent_BP` 的七个 `Create*MissionEvent` 函数都调用 `MissionEventInstance::InitializeEvent`；另有任务实例/状态查询及活动任务枚举。报告中没有序列化 Blueprint 调用 `FinishConditionCheck`、`SendMissionToState`、任务完成/取消通知或 `TrySpawnMission` 系列。固定 EXE 的这些原生入口已纳入唯一函数目录；反汇编显示它们是参数封送包装体并调用匿名内部函数，例如初始化 `0x5DC5B0`、发状态 `0x5E3590`、完成 `0x6DB8C0`、取消 `0x6DB820`。这类包装入口本身无直接 E8 调用者，反射或虚调用仍可能使用它们；匿名实现的类归属、参数结构、任务名分发和生命周期顺序仍未闭合。

目前已完成的自动化证据包括：13 个补丁及 guard、唯一 Game API 补丁源和研究目录一致性检查；全部 105,357 个 `.uasset` 的字符串扫描与无警告 JSON 导出；全包 16,579 个 Blueprint 函数字节码和 209,339 个顶层表达式统计；招募/社区及击杀/经验/事件/身份/属性调用引用清单；全量 259,728 个 `.pdata` 函数范围的直接调用分析及独立 E8/E9 交叉核验；8 个匿名成长链入口的一跳全量直接调用、E8/E9 审计及指令/数据地址候选扫描；14 个击杀/经验关键函数及 26 个 CHAININFO 分段的直接与间接调用解码；37 个 Blueprint 经验调用点的参数 AST 与局部赋值链，以及 28 行技能经验表和 16 个调用标签的匹配；CommunityMissionCondition 比较枚举的指针表、原生注册构造器、链式 unwind 片段与顺序值强静态推断，以及全量 ASCII/UTF-16 名称代码引用扫描；全包僵尸枚举使用、17 行遭遇类型类路径、28 行外观变体表、通用丧尸 Plague 标记分支、47 个相关资源的标记赋值清点及 9 个 Boons/Banes 密度分类清点；1,500 个路径/符号候选和 248 个任务/社区选择的定向结构化分析；显式 Mission 事件索引图遍历；Capstone 原生调用分析；以及固定版本招募机器码的私有内存仿真。结构化分析摘要分别保存在 `community-cooked-blueprint-analysis.json`、`community-full-uasset-cooked-audit.json` 和全包调用报告。所有工作只读取本地 EXE/PAK，在独立测试分配区执行复制出来的代码；没有启动、附加或修改游戏进程。

静态阶段的状态拆分如下：

- **已完成的静态提取与覆盖**：固定 EXE 身份和补丁 guard；35 个 PAK 索引与全部 105,357 个 `.uasset` 可读字符串扫描；全部 `.uasset` 结构化导出和字节码读取（105,357 个 JSON、0 解码错误、0 导出警告）；全包 Blueprint 函数/表达式统计与两类目标调用筛选；1,500 个路径/符号候选及 248 个任务/社区资源的结构化分析；显式 `EventIndexes` / `ElseEventIndexes` 图遍历；已登记目标原生函数的边界解码、全部可执行 `.pdata` 范围的一次性解码、选定 160 个目标的完整直接调用清点和独立 E8/E9 核验，以及 8 个匿名成长链候选地址的一跳直接调用/地址引用扫描；14 个击杀/经验函数体和 26 个 CHAININFO 分段的调用操作数摘要、37 个 Blueprint 经验调用点的参数 AST/局部赋值链、28 行技能经验表与 16 个标签匹配及血疫字段名称全量代码引用扫描；比较枚举与 `EZombieVariantType` 名称表及链式原生注册路径的顺序值强静态推断；社区任务条件相关 ASCII/UTF-16 名称在全部 `.pdata` 范围内的直接引用扫描，以及 `UCommunityMissionCondition` 初始化链和 `Comparison`/`Value`/`ComparisonStat` 偏移候选的静态解码；全包 `CommunityMissionCondition` 属性清点、僵尸遭遇类路径、通用丧尸外观变体及 Plague 标记分支；招募机器码仿真及研究数据库自动校验。
- **仍未完成的静态语义逆向**：全量序列化清点的 315 个 `CommunityMissionCondition` 对象中有 46 个缺少 `Comparison`（43 个使用 `CommunityMembers`，1 个使用 `CommunityOutposts`，2 个未序列化 `ComparisonStat`），字段偏移已有强静态推断，但类默认对象/构造函数默认值仍需从类构造或默认对象证据确认；任务 `EventName` 的原生动态分发与生命周期顺序未闭合；击杀责任方、重复通知和经验奖励之间的原生间接/委托链仍不确定；`EZombieVariantType` 的 Plague 底层值已有原生注册顺序强静态推断，且与蓝图 `byte == 4` 分支一致，但死亡通知中的受害者类型/字段、奖励分类是否读取 Plague 标记仍未证明；角色稳定身份、名册保存/迁移格式及所有消费方还未由结构与函数语义证明。所选 160 个原生目标的直接 E8 调用集合已完整清点并独立核验，另有 8 个匿名成长链入口的单独跟进；这不包括虚调用、间接调用和未选目标。
- **只能实机验收**：超过 12 人时的存读档、云同步、切图、社区 UI 排版/选中、领袖更换、驱逐、背包访问、随从派遣、遗产转移及各任务/电台招募路线。

因此，目前可以确认全包离线提取、字节码覆盖、筛选调用清单及自动化一致性检查已经完成，但**不能声称静态语义逆向全部完成**。剩余项目已收敛到类默认值、动态任务分发、击杀/经验责任链与名册存档语义；静态证据不足处保持未知，不用运行时猜测补齐。`CommunityScreenManager` 的集合和对象池字段说明其界面按集合处理部分成员，但不能证明超过原版上限后界面、存档和其他系统都安全。

对可取得的提取资产运行轻量字符串扫描（只找可读字符串，不解析完整资产结构）：

```powershell
python .\Research\tools\scan_uasset_symbols.py --pattern "(?i)(/Script/IggyPlugin|CommonUIMoviePlayer|IggyPlayer|IggyValue)" <extracted-assets-directory>
```

脚本只接受调用者指定的离线资产路径，不包含或分发游戏资产，也不会连接游戏进程。

工具盘点也没有找到与目标资产版本匹配的 Blueprint 编辑器/cooker。工作区里的 `u4pak` 文档只承诺较旧 PAK 格式打包，未证明与 SoD2 资源格式兼容；`SoD2-Editor` 的说明要求游戏运行并连接进程内存，与本轮离线静态分析约束不兼容，因此没有使用。当前 MCM 的 D3D11/ImGui 绘制和 `UiSurface` 仍只是开发覆盖层，原版 Character/Community UI 接入是发布门槛。


逐对象 Iggy 目录复现：从固定版本资源提取三个本地载荷后运行 `python Research/tools/export_iggy_object_catalog.py --settings <settings.iggy> --character <character.iggy> --pause <pause.iggy> --output <catalog.json>`。工具会验证三份载荷散列，并生成只含逐对象偏移、类型、索引布局和相对字段摘要的 JSON。


Iggy 候选对象链接（2026-09-25）：新增 `native-settings-iggy-object-links.json` 与 `Research/tools/analyze_iggy_object_links.py`，在 kind-1 记录尾区和 kind-3 双指针候选区间中按有界 4 字节步长扫描有符号相对值，只保留同时满足字段、位移、目标 8 字节对齐且精确落在同电影对象起点的候选链接。三个样本找到 1,455 条：kind-1 区 86 条全部指向 type-4 对象；kind-3 区 1,369 条指向 type-1/3/6 对象，其中 +0x30 槽位出现 592 次。除设置电影的一条 kind-3 前向候选外，其余 1,454 条均向后链接。kind-1 范围终点和 kind-3 边界虽可复现，字段语义仍未确认。未按父子、贴图或形状关系解释这些链接。

Iggy 运行时导出静态分析（2026-09-25）：`native-settings-iggy-runtime-api.json` 锁定已安装 `iggy_w64.dll` 的 SHA-256，静态追踪 11 个电影创建、脚本调用、事件、焦点和 ValueRef 导出接口的可达 x64 控制流，处理了导出函数跨 `.pdata` 冷代码区段的情况。`IggyPlayerGetFocusableObjects` 会遍历现有对象并向调用方写入 24 字节焦点记录；这是枚举/焦点接口的证据，不是创建或插入 UI 控件的证据。脚本调用接口分别可达内部分发目标 `0xB2520` 和 `0xB29C0`，说明后续应追查脚本路径；导出名扫描没有发现明确的显示树添加接口，但这不能排除脚本调用或未文档化路径。候选 side-block 链尚未与运行时解析器消费点关联，设置页控件插入契约仍未找到。

### 角色、社区、HUD 与地图原版 UI 适配点（静态研究）

`native-ui-screen-adapters.json` 由 `Research/tools/analyze_native_ui_movies.py` 从固定散列的 Character、Community、HUD、Map 资源所含 Iggy 电影提取 ActionScript 3 字节码，并用 FFDec 26.3.0 只生成方法/API 元数据；工具不会把解译源码或原始游戏资源写入报告。Map 资源的声明区不是单个 ABC，而是 349 个通过相对步长串接的 ABC 块；分析器现会逐块校验版本、边界和终止记录，再给 FFDec 构造临时多 DoABC 文件，临时脚本随分析结束删除。

角色页公开特质/效果添加方法，可作为原版特质区适配器；社区页公开按角色 ID 更新状态、文字和图标的方法，并能动态创建角色覆盖组件；两者均依赖游戏提供的角色 ID、锚点和页面生命周期。HUD 公开三秒自动收起的原版通知，以及可按整数 ID 添加、更新、移除并回收的状态图标气泡；这是成长提示和常驻增益图标的可用展示缝隙，但不提供任意文本面板或自定义交互控件。

Map 公开任务、目标和目标位置的添加/更新/移除方法。目标位置必须挂在已有 Objective 上，添加位置时若目标还未归属 Mission，不会显示；移除需提供 Objective 与 Location 两个句柄。坐标参数是地图电影自己的 X/Y 值，接口本身没有提供世界坐标换算，也不是独立任意地图标记接口。因此可把它作为原版任务目标上的标注适配器，不应用来伪造任务目标或猜测角色/位置 ID。该层调用是否能由游戏外 Mod 安全调用仍未验证。

因此，首批有边界的屏幕适配器可分别承载角色成长信息、社区角色状态、HUD 等级/增益提示，以及附着在现有任务目标上的地图位置标注。固定版本角色电影已通过一条受 guard 保护的 AVM2 单字节改写，将特质名称/描述池容量从 4 改为 6，电影大小和索引流边界保持不变；再用 `NativeSettingsAssetWriter replace-iggy` 写回固定版本 `character.uasset`，CUE4Parse 可重新解析，最终包长度不变且仅偏移 `2469842` 的 1 字节变化。实验报告见 `native-character-trait-pool-probe.json` 和 `native-ui-screen-adapters.json`。这证明固定长度字节码可以安全回写到目标包，不证明新增两行可见、布局正确或能成为成品 Mod。相反，FFDec 源码导入把 ABC 从 244,745 字节扩到 353,302 字节；直接替换后索引流仍终止于旧电影边界，故该重编写路线判为无效。

要成为通用 UI 框架，还需确认 Iggy `CallMethodRS` 的路径和值参数 ABI、角色/社区页面创建与销毁时机、角色 ID 的映射和调用授权；要支持任意按钮、滑块或可聚焦输入，还需建立 Iggy 显示对象/控件创建、焦点注册、键鼠和手柄导航及清理的受支持路径。现有静态证据没有证明这些通用控件能力。本研究没有运行或注入游戏。

复现角色/社区电影分析（需要本机从固定版本 PAK 提取 `character.iggy` 和 `community.iggy`，不提交游戏资源）：

```powershell
python .\Research\tools\analyze_native_ui_movies.py --character <character.iggy> --community <community.iggy> --hud <hud.iggy> --map <map.iggy> --ffdec-cli <ffdec-cli.exe> --report .\Research\StateOfDecay2\16535856\native-ui-screen-adapters.json
python .\Research\tools\patch_character_trait_pool_probe.py --input <character.iggy> --output <local-probe.iggy> --ffdec-cli <ffdec-cli.exe> --report .\Research\StateOfDecay2\16535856\native-character-trait-pool-probe.json
```
