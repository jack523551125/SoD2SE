# 独立产品的离线构建与打包

SoD2SE 仓库负责 framework Core、GameApi、Loader snapshot、共享 native runtime 和框架安装包。运行 workspace `Automation/dev.ps1 build/check/test/package SoD2SE`，或在此仓库使用 `Automation/Build/build.ps1`、`Automation/Test/check.ps1`、`Automation/Test/test.ps1` 与 `Automation/Package/package.ps1`。所有默认构建输出进入 `.work`；离线流程不会安装、部署或访问游戏文件。

MCM、MeleeSpeed、UnlimitedCommunity、UnlimitedFollowers、NativeModSettingsEntry、SkipStartupIntro 和 Roguelite 分别从各自仓库的 `build.ps1`、`check.ps1`、`test.ps1`、`package.ps1` 构建与打包。workspace dispatcher 调用相同入口，不再扫描 SoD2SE 的 `Plugins/` 或 `Mods/` 来代表独立产品。每个产品的 `src/mod.json` 是现有包版本与目标映射的权威。

产品 native 构建使用 `dependencies.lock.json` 固定的 SoD2SE revision 中的 Core/GameApi、共享 native contracts、MinHook 和构建 helper。ZIP 只从产品清单列出的文件生成，写入新的 `.work` 目录且拒绝覆盖同名包。打包完成不代表实机验收。

NativeModSettingsEntry 缺少经核验的固定版本本地资产时必须返回 `SKIPPED`。Roguelite 的 `publish=false` 必须保持，打包入口会拒绝发布。发布包、tag 和 GitHub release 不属于本地迁移验收。
