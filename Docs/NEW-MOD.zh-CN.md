# 新增独立 Mod 产品

每个 Mod 是单独的 Git 仓库，拥有自己的 README/DESIGN/AGENTS、`project.toml`、`src/mod.json`、build/check/test/package 入口和 release 工作流。workspace 只在 `workspace.toml` 登记项目并通过 submodule 固定产品 revision；不要把新产品源码放进 SoD2SE `Plugins/` 或 `Mods/`，也不要添加源码 junction。

托管产品通常维护 `src/`、`tests/managed/`；含原生组件的产品还维护 `native/src/`、`native/tests/` 和产品自己的 `native/CMakeLists.txt`。资源型产品维护它自己的资源相对路径与 manifest。`project.toml` 的 `source.owner` 和 `source.version_file` 都相对于产品仓库根目录。

产品 `src/mod.json` 声明 `schema`、`id`、中英文名称、原有 `version`、`publish`、依赖和文件映射。`input` 可使用 `build:`、`source:` 或显式传入的 `external:`；`target` 是 MO2 虚拟安装路径，以 `Root/` 或 `Saved/` 开头。保持当前版本和安装路径不变，原版输入缺失时报告 `SKIPPED`，不要伪造生成资产。

需要共享运行时代码时依赖固定 revision 的 SoD2SE source checkout，使用产品 `dependencies.lock.json` 检查 revision。Core、GameApi、现有共享 native runtime 与 vendor 仍归 SoD2SE；Packages 保留契约和使用说明，不复制 runtime 实现。产品 CMake 调用 SoD2SE 提供的 native helper，但产品专属 target/source/test 留在产品仓库。

从 workspace root 运行 `Automation/dev.ps1 build/check/test/package <ID>`，或从产品 checkout 调用该仓库自己的脚本。根 Automation 仅做协调；产品脚本不得依赖 `Projects/SoD2SE/Plugins/...` 的旧路径。原始游戏文件、dump、解包资源和第三方 checkout 不进入产品仓库或安装包。
