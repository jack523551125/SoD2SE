# 固定版本设置资产写回与 Iggy 提取工具

离线写回和 Iggy 提取仅处理《腐烂国度 2》构建 16535856 的固定散列 UI 资产：`Art/UI/settings.uasset`、`Art/UI/character.uasset`、`Art/UI/community.uasset`、`Art/UI/pause.uasset`、`Art/UI/hud.uasset` 和 `Art/UI/map.uasset`。`inspect-ui` 还可只读检查固定散列的 `hud`、`map` 和 `character_manager` 候选包。所有操作只接收散列匹配的原版文件，并要求输出路径与输入不同；工具不会覆盖原件，也不生成可安装 Mod。Settings 的文字编辑，以及 Settings、Character、Community 的 Iggy 替换已通过包级解析验证；HUD、Map 和 Pause 目前只允许提取。

```powershell
dotnet run --project Research/tools/native_settings_asset_writer/NativeSettingsAssetWriter.csproj -- roundtrip <settings.uasset> <new-output.uasset>
dotnet run --project Research/tools/native_settings_asset_writer/NativeSettingsAssetWriter.csproj -- replace-text <settings.uasset> <new-output.uasset> ID_ACCESSIBILITY_AIM_ASSIST "Aim Assist" "Mod Settings"
dotnet run --project Research/tools/native_settings_asset_writer/NativeSettingsAssetWriter.csproj -- add-text <settings.uasset> <new-output.uasset> ID_MOD_SETTINGS "Mod Settings"
dotnet run --project Research/tools/native_settings_asset_writer/NativeSettingsAssetWriter.csproj -- extract-iggy <settings.uasset> <local-analysis.iggy>
dotnet run --project Research/tools/native_settings_asset_writer/NativeSettingsAssetWriter.csproj -- replace-iggy <settings.uasset> <new-output.uasset> <validated.iggy>
```

每个操作都会用 UAssetAPI 重读并检查二进制往返；再用 CUE4Parse 按 UE4.13 加载生成文件，确认资源仍识别为 `IggyPlayer`，并核对 `TextTable` 条目数。改字模式只修改指定 FText 的源字符串；新增模式只添加文字表项。

这验证了 Unreal 包容器及 `IggyPlayer` 文字表可以被重建和独立解析。新增文字表项不会让菜单显示文字，也不会创建 Iggy 显示对象、按钮、回调、焦点行为或导航。该工具仍属于离线研究工具，输出中的游戏资源不得分发。

`extract-iggy` 只接受上述三个固定散列锁定的 16535856 UI 资产，按各自导出对象提取数据，验证 20 字节 Unreal/Iggy 封装、相同的两个载荷长度字段、Iggy 签名和 64 位标记，再把载荷写到新路径。可将本地载荷交给只读结构检查器：

```powershell
python Research/tools/inspect_iggy_movie.py <local-analysis.iggy> --report <local-report.json>
```

检查器验证子流、相对指针边界和对象指针表；只读取 6 号文本对象的索引/边界/文本长度和哈希，不保存原始字符串，也不解释 1、3、4 等对象类型。它不能重建显示树，也不能证明游戏会加载编辑过的资源。

依赖：UAssetAPI 1.1.0、CUE4Parse 1.2.1。项目仅供固定版本研究和本机原件验证使用。

`replace-iggy` 可对上述三个已验证资源执行离线写回：保留原封装字段、更新两个载荷长度、重建包后核对载荷字节，并用 CUE4Parse 重新解析包。角色页验证样例只将预分配特质槽从 4 增到 6；包长度不变，二进制差异只有一个字节。该结果证明固定长度 Iggy 修改可回写 Unreal 包，不证明新增特质一定显示完整，也不证明游戏会加载该包。内部脚本、索引和对象布局应先通过专用验证；复现步骤和实机验收限制见 `Docs/NativeModSettingsEntry.zh-CN.md`。


对固定版本三个 Iggy 载荷生成无文本/图像字节的逐对象研究索引：

```powershell
python Research/tools/export_iggy_object_catalog.py --settings <settings.iggy> --character <character.iggy> --pause <pause.iggy> --output <catalog.json>
```

导出器锁定三个载荷散列；对象类型 1、3、4 仍是未解码的候选结构。


对固定版本 kind-1/kind-3 有界侧块中可能指向对象起点的有符号相对引用进行只读扫描：

```powershell
python Research/tools/analyze_iggy_object_links.py --settings <settings.iggy> --character <character.iggy> --pause <pause.iggy> --output <object-links.json>
```

结果仅为候选对象链接，不证明 UI 父子或绘制语义；工具检查固定载荷散列，不保存原始块数据。
