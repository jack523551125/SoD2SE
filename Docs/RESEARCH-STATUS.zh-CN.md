# 研究状态与交接（2026-09-24）

本文是导航与证据边界说明，详细结果以 Research/StateOfDecay2/16535856 中的报告为准。静态证据、自动化测试、运行能力和实机验收必须分别记录。

## 版本与结论

目标构建：16535856。EXE SHA256：`EBF0A73E164BAA701F74655585F262F8E38A32B1F6DC5057303489BA5B333ECE`。
框架源码版本：0.6.0-preview。新增研究没有解锁幸存者成长，也没有重新发布可玩版本。

| 领域 | 已取得的证据 | 尚不能据此认定 |
|---|---|---|
| 经验原生入口 | 14 个选定函数、26 个 CHAININFO 范围及直接/间接调用报告 | 全伤害来源的唯一击杀事件或责任角色 |
| Blueprint 经验调用 | 7 个资产、13 个函数、37 处调用及参数/局部变量来源 | 运行路径必然执行、网络权限或死亡去重 |
| ExperienceRewards | 28 行，16 个调用标签候选均匹配表行 | 原生 helper 确实读取此表；该表提供自定义角色等级经验 |
| 丧尸分类 | 资产分类、血疫行及枚举注册证据 | 死亡事件中可安全取得类别与血疫状态 |
| 社区条件 | Comparison/Value/ComparisonStat 的静态布局推断 | 未序列化 Comparison 的默认值与所有人数消费者 |
| 原生血疫标志 | 名称字符串引用和上下文 | 无字符串引用等于没有字段访问 |

经验表实际关联原版 CharacterSkillDefinition 技能经验；不能直接当作成长 Mod 的杀敌经验表。0x1CF9CA 是根函数 0x1CF910 的 CHAININFO 片段起点，不是独立函数。研究数据库已经保留这一更正。

## 仍需完成的关键工作

1. 逐类闭合近战、枪械、车辆、投射物、持续伤害的死亡责任链，确认去重标识与权限。
2. 确认角色持久身份的存储和消费者，证明跨社区与遗产池稳定；不得用名字或指针猜测合并。
3. 闭合八种强化的原生计算入口、适用条件和对象生命周期；确认共享攻速提供者与其他增益合成。
4. 确认暂停、载入、切换角色、死亡、模式切换接口及租约释放语义。
5. 确认原版 Character/Community UI 资源、构建与插入方式以及输入导航；覆盖层不能冒充原生 UI。

原版设置菜单另已闭合 `PauseUI_BP → SettingsUI_BP → Art/UI/settings` 的离线资源引用链，并完成固定长度文字替换的独立解析实验；见 [设置页研究](NATIVE-SETTINGS-UI.zh-CN.md)。仍缺 Iggy 控件回写、输入绑定和游戏加载验证，不能据此迁移 MCM。
6. 闭合经验 helper 与 DataTable 的消费关系、丧尸分类字段读取、动态事件分发和社区条件缺失默认值。
7. 对接后再做合成事件、故障注入、保存事务和旧插件兼容测试。未经验证的能力保持禁用并说明原因。

这些项不能标记为“全部静态完成”。静态接口确认后仍需另行进行实机验收，尤其是击杀覆盖、暂停、跨社区迁移与原生 UI；当前任务不进行实机操作。

## 主要报告入口

- `roguelite-capabilities.json`：成长能力状态及证据引用。
- `roguelite-kill-experience-disassembly.json`：经验调用及 CHAININFO。
- `roguelite-experience-blueprint-call-contexts.json`：调用参数与赋值链。
- `roguelite-experience-reward-table.json`：技能经验表与标签匹配。
- `roguelite-native-followup-direct-xrefs.json` 及 audit/address-references：后续入口引用。
- `zombie-variant-enum-native-registration.json`：分类枚举注册。
- `zombie-plague-flag-native-name-references.json`：血疫名称引用。
- `roguelite-enemy-classification-static.json`：资产侧分类。
- `community-mission-condition-native-layout.json`：社区条件布局。

以上文件均位于同一个固定版本资料目录。不要复制数字到运行代码来绕过能力门控。
