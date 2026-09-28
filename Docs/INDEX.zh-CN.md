# 开发与资料导航

## 维护入口

- [项目说明](../README.zh-CN.md)：框架、安装和现有插件。
- [研究状态与未完成项](RESEARCH-STATUS.zh-CN.md)：证据边界和后续研究。
- [维护与验证](MAINTENANCE.zh-CN.md)：静态检查、产物管理与归档恢复。
- [固定版本详细研究](../Research/StateOfDecay2/16535856/README.zh-CN.md)。
- [测试说明](../Tests/README.md)。
- [MCM](../MCM.zh-CN.md)、[界面协议](../UI.zh-CN.md)、[近战攻速](../MELEE.zh-CN.md)、[社区招募](../COMMUNITY.zh-CN.md)。
- [原版设置菜单接入研究](NATIVE-SETTINGS-UI.zh-CN.md)：固定版本资源链、离线文字实验与新增控件的阻塞条件。

## 代码与数据职责

| 目录/文件 | 职责 |
|---|---|
| Core | 通用框架、会话、共享服务与插件协议 |
| GameApi | 固定版本游戏接口与能力门控 |
| Loader | 直接启动与插件加载 |
| Plugins | 无限随从、社区招募、近战攻速、MCM、幸存者成长 |
| Native | 原生模块及其依赖 |
| Research/StateOfDecay2/16535856 | 此版本的签名、结构、证据报告和能力状态 |
| Research/tools | 离线报告生成器及其单元测试 |
| Research/sync_research.py | 从唯一补丁表同步派生清单 |
| Research/validate_research.py | 研究数据结构和报告一致性校验 |
| Tests | 框架、插件与协议测试 |
| compiled | 默认编译输出，可重新生成，不是源代码 |

## 旧资料与外部依赖

早期的 assets、各类 UI/配置/近战/招募分析、re-extract、recruitment-tests 与 native-mod 已归入 `E:\CODE\SoD2_MOD_Dev\ReverseEngineering\Legacy\Work`；它们尚未逐文件证明完全重复，保留作历史参考，不作为更新后的权威定义。disasm-libs、native-tools、SoD2-Editor、sod2-tools、u4pak 同处该目录，仍是独立工具或第三方参考项目，不将其授权归属混入自研源码。旧 work 下的同名目录是兼容目录联接点。

完整离线资产导出位于 `E:\CODE\SoD2_MOD_Dev\ReverseEngineering\Inputs\16535856\SoD2StaticFullUassetExportsFinal`，和源码同属总工作目录，但不在源码 Git 仓库内。本项目源码不能单独替代所有报告的原始输入；每个生成器的参数和报告中的 source/hash 决定复现要求。游戏文件与大规模资产导出不应加入对外 Mod 包。

E 盘离线资料已经分类整理到 `E:\CODE\SoD2_MOD_Dev\ReverseEngineering`，目录说明与 `move-manifest-2026-09-24.json` 位于该目录根部。旧路径 `E:\SoD2Research` 是指向新位置的目录联接点。历史 JSON 中的 export_root_name 是保持不变的目录名，不是失效的绝对路径。
