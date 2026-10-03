# SoD2SE 开发与资料导航

## 维护入口

- [SoD2SE 说明](../README.zh-CN.md)：框架、Core、GameApi 和共享 native runtime。
- [仓库内部布局](INTERNAL_LAYOUT.md)：本仓库源码边界和独立命令。
- [维护与验证](MAINTENANCE.zh-CN.md)：离线检查、产物和恢复边界。
- [新增 Mod](NEW-MOD.zh-CN.md)：产品入口和现有兼容接口。
- [框架离线打包](RELEASE.zh-CN.md)：框架包与独立产品包的边界。
- [测试说明](../Tests/README.md)：本仓库测试范围。
- [共享界面协议](Products/UI.zh-CN.md)：SoD2SE Core 的界面契约。

## 独立产品与研究仓库

产品源码、测试、manifest 和 release 输入位于各自仓库：

- [MCM](../../MCM/README.zh-CN.md)
- [MeleeSpeed](../../MeleeSpeed/README.zh-CN.md)
- [UnlimitedCommunity](../../UnlimitedCommunity/README.zh-CN.md)
- [UnlimitedFollowers](../../UnlimitedFollowers/README.zh-CN.md)
- [NativeModSettingsEntry](../../NativeModSettingsEntry/README.zh-CN.md)
- [SkipStartupIntro](../../SkipStartupIntro/README.zh-CN.md)
- [Roguelite prototype](../../../Labs/Roguelite/README.zh-CN.md)
- [ReverseEngineering 研究状态](../../../ReverseEngineering/Topics/RESEARCH-STATUS.zh-CN.md)
- [原版设置菜单研究](../../../ReverseEngineering/Topics/NATIVE-SETTINGS-UI.zh-CN.md)

本仓库不跟踪产品内部源码，也不依赖源码 junction。Core、GameApi 和共享 native runtime 由 SoD2SE 拥有；ReverseEngineering 只收录经审查的自著工具、测试、文档和证据。游戏原件、dump、解包资源、私人数据、第三方 checkout 和未审查生成输出留在受保护的本地数据中。
