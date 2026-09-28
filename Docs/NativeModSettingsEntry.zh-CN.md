# 原版设置菜单的 Mod 设置入口

当前资源入口预览为 `0.2.9-preview`，MCM 安装包为 `0.6.3-preview`（`Mcm.dll` 程序集 ABI 仍为 `0.6.0`）。旧 F1 设置覆盖层已从 MCM 原生渲染与按键处理路径移除。原版菜单入口、数值滑块、数字输入框和 `0.2.8-preview` 的精简布局已由用户截图确认显示；`0.2.9-preview` 的输入框配色尚待实机验收。

`0.2.3-preview` 曾通过逐项诊断定位到设置页面构造阶段。当前资源没有 MCM 语言下拉框，改由 Core 在启动时检测游戏语言；原版分类名称和页面文案通过只读语言操作动态选择中英文。`0.2.6-preview` 修正了 MO2 包内 `Root/Saved` 错误路径。`0.2.7-preview` 保留数值滑块，并将右侧数字设为输入框。`0.2.8-preview` 移除了页面和选项解释文字、顶部操作说明、提交状态按钮及底部保存状态行；保存回调保留。`0.2.9-preview` 将输入框的白底黑字改为深棕底、浅色数字和橙色细边，继续使用同一原版 Iggy 页面内的 TextField。新版外观和键盘编辑仍需游戏内确认。

旧版本的安装记录与文件备份位置保存在 Research 资料库的 `native-settings-mcm-bridge.json`。完全退出游戏后重新启动才会加载新的入口资源；新 MCM 原生 DLL 不再提供 F1 旧设置界面。若原版页仍无法显示选项，最新 `%LOCALAPPDATA%\StateOfDecay2\SoD2SE\Mcm-native-*.log` 会给出逐项 RPC 顺序与检查点。

## 页面与数据桥接

- 原版分类列表末尾增加“Mod 设置”，复用原版调试分类槽位 0、控件构造器、鼠标/焦点注册和返回路径；没有增加 Iggy 显示对象或类字段。
- 设置页从 MCM 原生端取得页面快照，显示已注册的页面名、设置名与描述，支持布尔开关和整数输入；页面只读取自动检测到的语言，输入提交和状态提示经 Iggy 回调传回 MCM。
- 保存沿用 MCM 现有 `mcm.ini` 路径与设置命令；本次保留用户配置文件，并移除了旧 F1 设置页面。
- Iggy callback ABI 仅对已核对散列的游戏 DLL 开启，其他回调转发给原始处理器。机器码字段、导出 RVA 和 ABI guard 记录见 `Research/StateOfDecay2/16535856/native-settings-mcm-bridge.json`。

## 构建与验证

复现使用固定版本 `settings.iggy`、JPEXS FFDec 26.3.0 和已知原版 `settings.uasset`：

```powershell
python Research/tools/build_native_mcm_settings.py --iggy <settings.iggy> --ffdec <ffdec-cli.exe> --output <新目录>
dotnet run --project Research/tools/native_settings_asset_writer/NativeSettingsAssetWriter.csproj -- replace-iggy <原版settings.uasset> <新目录/settings-mcm.uasset> <新目录/settings-mcm.iggy>
python -m unittest discover -s Research/tools -p test_patch_native_mcm_bytecode.py -v
```

写入器只接受固定原件散列并写到新路径。FFDec 无改动 XML 往返保持 ABC 逐字节相同；重建检查限制于指定方法体，保留原始绑定、类特征、签名、未目标方法和电影字节。UAssetAPI 二进制往返及独立 CUE4Parse UE4.13 载入均通过。NativeSettings 模型/回调测试、字节码分支测试及资产构建器测试结果列于上述 JSON。

## 用户实测步骤

完全退出游戏并重新启动，进入原版“设置 → Mod 设置”，检查页面是否显示、选项文字、布尔切换、整数编辑提交、保存状态、返回与关闭。更改游戏语言后重启，应看到入口和 MCM 自身文案跟随游戏语言；MCM 不提供手动语言切换。F1 应保持不打开旧菜单；原有 `%LOCALAPPDATA%\StateOfDecay2\SoD2SE\mcm.ini` 配置应保留。若页面仍空白，请退出游戏后提供最新 `Mcm-native-<PID>.log`；键鼠/手柄焦点、视觉排版、滚动与实际持久化仍未实测。
