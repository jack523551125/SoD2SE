# 2026-09-28 菜单、片头和 20 人测试存档

目标版本：16535856。所有本轮验证均为离线测试；未启动或读取运行中的游戏。

## 菜单

- UnlimitedFollowers / UnlimitedCommunity 0.6.1-preview：仍注册原有页面 ID，不再注册 `enabled` 选项。启停交给 MO2；Core 原有 `IsEnabled` 对无 enabled 选项的页面返回 true，因此旧配置的 false 不阻止本轮加载。
- MeleeSpeed 0.6.1-preview：四个倍率改回 Integer 原版滑条，25–1000 范围、配置 ID、配置值和运行行为不变。原生近战提供者没有重新编译。
- NativeModSettingsEntry 0.3.1-preview：无选项的页面显示名称和加载状态，状态来自 PageLoaded RPC；成功显示绿色勾选“已加载”，没有成功初始化则显示“未加载”。这里的加载指 DLL 初始化完成，不等于降级功能可用。
- 状态行使用隐藏滑条的原版 slider_value_setting，仅作展示；禁用交互并移出 CategoryTracker.Settings，防止 Refresh 覆盖文字为数字 0。保留在显示列表中，参与原版布局。
- 原版 UpdateHints 只识别 slider_setting，未识别其兄弟类 slider_value_setting。新前缀复用游戏现有 205 提示组，原有左右输入和键位映射沿用。
- 沿用现有自动游戏语言接口，没有恢复 F1 覆盖菜单、手动语言设置、说明段落或保存提示。

相关文件：Plugins 下三个插件、Research/tools/patch_native_mcm_bytecode.py、build_native_mcm_settings.py。新增断言和独立 FFDec 回读验证通过；非目标方法/命名空间/traits 不变。Iggy 重新装回 UAsset 后通过 CUE4Parse UE4.13 独立加载。

## 片头

旧 0.1.0-preview 只用用户 Game.ini 清空 StartupMovies，用户实测仍播放。安装配置存在，不能将问题归因于未启用。

固定版本原配置指定 StartupMovies=Logos；磁盘影片为 StateOfDecay2/Content/Movies/Logos.bk2（11647176 字节，SHA256 9cca540c6d8b3cb4a5e64dff49cb169141a80d184098a69fe0f7ac336351bfa3）。本地字符串扫描没有找到可靠的 NoStartupMovies 命令行参数，不采用未经证实的参数。

0.1.1-preview 通过 MO2 Root 映射零字节 Logos.bk2，阻止解码原影片。包不携带游戏影片内容。删除本 Mod 旧 Game.ini，避免整文件覆盖其他用户设置。原版影片文件保持完整。

已验证 MO2 安装器规划、构建副本和 runtime_mappings 保留零字节文件并映射到准确的原影片路径。**影片失败打开后是否立即继续启动，需要实机确认；离线测试没有证明游戏失败路径的行为。** 范围是启动标志影片，不是跳过加载、存档选择或游戏内剧情。

## 测试存档

Tests/CreateTwentySurvivorSave.cs 使用用户本地 Community Editor 的 SaveParser，仅写新目录，不重新分发第三方 DLL。基于玩家普通战役槽 0：保留 3 人，生成独立 ID 11–27 的 17 人，合计 20 人。更新配套 SaveUser 的 NextAvailableSurvivorID；不会用名字或地址生成身份。复制装备/背包及弹药实例，清空新角色继承的叙事身份和亲属关系。

已通过：原件无修改读写的解压数据逐字节一致；原有成员和非目标子树回读一致；独立角色/物品引用；配套账号仅更改下一角色 ID；Apply/Restore 在独立临时目录哈希还原。正式存档未替换。

交付目录 outputs/TwentySurvivorTest-20260928，包含测试存档、原件、Apply-TestSave.cmd、Restore-OriginalSave.cmd 和说明。脚本会在切换时再次备份，拒绝游戏运行时操作及正式存档已变化后的旧快照覆盖。需要退出游戏后手动切换。

## 交付与限制

五个包位于 outputs/MenuAndIntroUpdate-20260928-final，已覆盖安装到 E:/Game/SD2_mod/mods 相同 Mod 目录。原版 MCM DLL、Core、Game API 和近战原生提供者未更新。包只有有效负载和 MO2 元数据，没有开发文档。package-verification.json 记录 5 包、6 个有效负载的哈希/映射验证结果。

备份：E:/Game/SD2_mod/sod2-support-backups/menu-intro-20260928-080205。

待用户实机验收：绿色勾字符和状态行排版；滑条鼠标/手柄提示；无输入框；20 人社区加载与招募第 21 人、保存重载；启动标志是否跳过。20 人存档已存在并通过离线读取，但不等于无上限招募的实机验证通过。
