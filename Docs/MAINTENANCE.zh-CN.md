# 维护、验证与产物管理

## 当前离线入口

从 workspace root 使用 `Automation/dev.ps1 check workspace` 检查固定 submodule revisions 和产品 metadata，再对受影响的 owner 运行 `Automation/dev.ps1 check/test <ID>`。SoD2SE 仓库自身使用 `Automation/Test/check.ps1` 与 `Automation/Test/test.ps1`。这些默认离线入口不会启动、附加或部署到游戏。

产品的源码、测试、manifest、package 和 release 输入归各自仓库。MCM、MeleeSpeed 与 Roguelite 的 native CMake 使用 `dependencies.lock.json` 固定 SoD2SE shared runtime/helper revision。不要把产品代码放回 SoD2SE `Plugins/`、`Mods/`，不要恢复源码 junction。

构建和包验证输出放在 `.work`。历史发布包保留原始字节，新的包用新的临时输出目录验证；本地迁移不发布版本，不覆盖 `dist` 中的文件。NativeModSettingsEntry 缺少经核验的固定版本资产时记录 `SKIPPED`。Roguelite 必须保持 `publish=false`。

## 研究和证据

ReverseEngineering submodule 维护经审查的自著工具、测试、文档和证据。游戏原件、dump、解包资源、私人资料、第三方本地 checkout、缓存和未审查生成输出仍是受保护的本地数据。缺少原始输入时标记 `SKIPPED`，不得伪造替代证据。

每个新结论应记录目标版本、输入散列、证据来源、推导过程、消费者和未确认项。区分直接观察与推断。证据和生成器不能自动证明游戏语义或实机兼容。

## 历史维护记录

以下记录描述历史日期的状态，不代表本次迁移仍使用相同路径：

- 2026-09-24：研究工具发现 57 项测试，50 项执行通过，7 项跳过；归档映射和文档链接检查通过。跳过项不算验收。
- 2026-09-24：旧 dist、验证日志和临时目录归档至当时的 `archive/2026-09-24-cleanup`；归档快照不是当前维护源。
- 2026-09-29：旧版 `verify_native.py` 报告 MCM 原生偏移清单中存在未命名 RVA。该记录针对当时的 SoD2SE 物理布局；本次 MCM native 代码归其产品仓库，需使用产品入口验证。

历史记录中的路径、脚本输出和验证范围均不能替代当前仓库的验收结果。
