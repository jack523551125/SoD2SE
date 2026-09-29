# 原版设置菜单的 Mod 设置入口

当前源码的原版入口包声明版本为 `0.3.1-preview`，MCM 包声明版本为 `0.6.3-preview`；MCM 协议 ABI 为 6。旧 F1 设置覆盖层已从 MCM 原生渲染与按键处理路径移除。用户截图已确认原版菜单入口、设置选项和数值滑块显示。版本声明说明新打包产物的元数据，不代表 MO2 当前安装版本；最新资产仍须单独实机验收。

历史版本记录：`0.2.3-preview` 的逐项诊断定位到设置页面构造阶段；`0.2.6-preview` 修正 MO2 包内 `Root/Saved` 路径；`0.2.7-preview` 引入数值滑块和输入框；`0.2.8-preview` 精简说明与保存状态文字；`0.2.9-preview` 调整输入框配色。当前资源无 MCM 语言下拉框，Core 启动时检测游戏语言。历史版本的输入框外观不代表当前包的视觉状态，不能用旧截图认定最新包已通过验收。

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

完全退出游戏并重新启动，进入原版“设置 → Mod 设置”，检查页面、选项文字、布尔切换、数值调整、返回与关闭。更改游戏语言后重启，应看到入口和 MCM 文案跟随游戏语言；MCM 不提供手动语言切换。F1 不应打开旧菜单；原有 `%LOCALAPPDATA%\StateOfDecay2\SoD2SE\mcm.ini` 配置应保留。若页面再次空白，退出游戏后查看最新 `Mcm-native-<PID>.log`；键鼠/手柄焦点、视觉排版、滚动与实际持久化仍需按最新构建验收。
