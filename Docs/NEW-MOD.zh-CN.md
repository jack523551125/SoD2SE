# 新增 Mod 项目

DLL Mod 的唯一可编辑源码建在 `Plugins/<Id>`；资源 Mod 建在 `Mods/<Id>`。`Id` 使用英文字母开头的字母数字名称，与目录名完全一致。每个目录必须有 `mod.json`，声明 `schema: 1`、`id`、中英文预设 `name`、`version`、`publish`、`requires` 和 `files`。文件映射的 `input` 可使用 `build:`（新构建输出）、`source:`（源码树）或 `external:`（明确传入的固定版本生成资产）；`target` 是 MO2 虚拟安装路径，以 `Root/` 或 `Saved/` 开头。

例如托管插件：

```json
{
  "schema": 1,
  "id": "Example",
  "name": "示例 - Example",
  "version": "0.1.0-preview",
  "publish": false,
  "requires": ["SoD2SE Framework"],
  "files": [
    {"input": "build:Plugins/Example.dll", "target": "Root/Plugins/Example.dll"}
  ]
}
```

开发期间保持 `publish: false`，使批量打包跳过未验收原型；单独传 `-Ids Example` 仍可生成测试包。`build.ps1` 自动编译包含 C# 源码的插件目录，并从对应 `mod.json` 生成程序集版本。需要共用游戏接口时修改 `Core`/`GameApi` 的公开契约、测试与研究证据；原生组件需明确加入 `Native/build_native.ps1`，并在 `files` 中声明产物。不要从 MO2 已安装目录复制 DLL。

源码树和目录导航的关系见工作区 [README.zh-CN.md](../../../README.zh-CN.md)。如果需要在根工作区 `Projects` 下增加可见入口，新增项目 README，再把 `Source` 的相对映射写进 `workspace-links.json`，运行 `Initialize-Workspace.ps1` 创建联接点。此入口是导航，源码依然由 `SoD2SE` 仓库管理。

运行 `build.ps1`、对应单元测试、`verify_sources.py`、`package_mo2.ps1 -ValidateOnly`，最后按 [发布说明](RELEASE.zh-CN.md)用全新输出目录打包。研究结论应写入 `Research/StateOfDecay2/16535856` 并注明固定版本证据；不要把原始游戏资产纳入 Git 或安装包。
