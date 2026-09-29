# 维护、验证与产物管理

## 静态工作流程

从 `E:\CODE\SoD2_MOD_Dev\Projects\SoD2SE` 运行以下命令；它们不启动游戏、不注入、不读取运行中的游戏。

```powershell
python -m unittest discover -s Research/tools -p 'test_*.py'
python Research/validate_research.py
python verify_research.py
python verify_sources.py
python verify_protocol.py
python -m unittest discover -s Tests -p test_package_mo2.py
```

可选 Capstone 依赖缺失时部分工具测试会跳过；记录实际执行数与跳过数，不把跳过算作通过。需要复现离线扫描时先查看相应 Research/tools 脚本的参数，使用报告记录的固定版本文件与资产输入。

补丁唯一源为 `Research/StateOfDecay2/16535856/patches.json`，变更后运行 `python Research/sync_research.py` 并重新验证。不要直接维护两份根目录 manifest。

`build.ps1` 默认生成 compiled；`package.ps1` 生成开发归档，`package_mo2.ps1` 按各 Mod 的 `mod.json` 生成可安装包。实际发布应使用全新的输出目录，按 [离线发布](RELEASE.zh-CN.md)核对每个 ZIP 与元数据。运行整套 verify_all.ps1 前阅读其步骤，不能将它与纯资料验证等同。

截至 2026-09-29，`verify_native.py` 仍报告 `Native/NativeSettingsIggy.h:268` 的裸 RVA `0x57bd0` 未在偏移清单记名；这是已有的原生静态检查未完成项。不得把上述构建和打包测试通过描述为整套原生验证通过。

## 资料更新规范

每个新结论记录目标版本、输入散列、证据地址/资产、推导过程、消费者和未确认项。区分入口、CHAININFO 片段、字符串引用、字段访问与控制流推断。报告与生成器配套，补充能发现回归的测试；只有报告生成不能替代游戏语义闭合。

研究说明存放在项目与 Docs/Research；面向 MO2 的 Mod 包只包含运行文件及供安装器消费的元数据，不夹带开发文档。框架包不包含 MO2 meta.ini。开发源码归档与可安装包须分别标识。

## 2026-09-24 目录整理（历史记录）

历史编译检查、打包暂存、旧 dist、五轮渲染测试、旧验证日志以及非 0.6.0-preview 输出已归档到工作区 `archive/2026-09-24-cleanup`。共 50 个顶层文件或目录移动，映射见该目录 manifest.json。当前源码、compiled、0.6.0-preview 产物和早期原始研究输入保持原路径。

归档中的源码和说明是历史快照，不作为维护源。旧快照里记录的相对路径可能已失效；如需完整复现旧版本，先按清单恢复到隔离工作副本。恢复时根据 manifest 的 destination 找到文件，放回 source，先确认目标不存在，不能覆盖新文件。

批量删除请求被自动审批拒绝；此次实际只做可恢复归档，未删除缓存或空目录。没有修改游戏安装、MO2、用户配置或成长存档。之后清理缓存可单独评估，当前无需依靠删除来使用整理后的目录。

## 本次验证记录

2026-09-24：研究工具发现 57 项测试，50 项执行通过，7 项跳过；Research/validate_research.py、verify_research.py、verify_sources.py 全部通过。新增四份文档的本地链接及 50 条归档映射检查通过。跳过项意味着本次没有覆盖对应测试，不算实机验收。未重新构建或打包运行文件。
