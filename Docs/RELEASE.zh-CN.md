# 离线构建与 MO2 打包

从 `E:\CODE\SoD2_MOD_Dev\Projects\SoD2SE` 运行。打包器不读取游戏安装目录或 MO2 已安装目录，也不负责安装。先使用全新的输出目录构建：

```powershell
& .\build.ps1 -OutputDirectory 'E:\CODE\SoD2_MOD_Dev\outputs\build-YYYYMMDD'
python -m unittest discover -s Tests -p test_package_mo2.py
& .\package_mo2.ps1 -ValidateOnly
```

随后打包指定 Mod，例如：

```powershell
& .\package_mo2.ps1 -BuildDirectory 'E:\CODE\SoD2_MOD_Dev\outputs\build-YYYYMMDD' -OutputDirectory 'E:\CODE\SoD2_MOD_Dev\outputs\release-YYYYMMDD' -Ids MeleeSpeed
```

不传 `-Ids` 时自动发现所有 `publish: true` 的 `Plugins/*/mod.json` 与 `Mods/*/mod.json`，并附带框架包。`Roguelite` 目前为开发原型，默认跳过。原版设置入口需要离线构建出的固定版本 `settings.uasset`；传 `-NativeSettingsAsset <绝对路径>` 才能包含该包。使用 `-RequireComplete` 可让缺少该资产成为错误。不能用任意游戏版本的资产替代；构建与验证方法见 [原版设置入口](NativeModSettingsEntry.zh-CN.md)。

`mod.json` 是每个 Mod 的名称、版本、依赖和安装文件映射的唯一维护源。`build.ps1` 以它给托管插件 DLL 写入版本；通用打包器用同一版本生成 ZIP 文件名及 `meta.ini`。框架版本由 `Core/SoD2SE.Core.cs` 的 `FrameworkInfo.Version` 管理。框架包不含 `meta.ini`，用于游戏根目录；MO2 Mod 包根目录含 `meta.ini`，不含开发文档。新输出目录避免覆盖已有包；打包器在写入前核对所有选中输入，缺文件不会留下部分发布包。

构建结果、ZIP 和哈希应在发布前核对。原生 DLL 不携带托管程序集版本，必须与本次 `build.ps1` 产出的托管 DLL 一起打包。MO2 中安装的旧文件不能作为构建输入。打包完成不等于游戏内验收；当前流程只执行离线检查，不启动或注入游戏。

旧的 `package_mcm_language_update.ps1` 和 `package_status_sliders_update.ps1` 仅为兼容入口，内部调用通用打包器。新开发使用 `package_mo2.ps1`。
