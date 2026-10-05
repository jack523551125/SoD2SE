use sod2se_sdk::*;
#[unsafe(no_mangle)]
/// # Safety
/// output must point to writable PluginApi storage when version is native ABI 1.
pub unsafe extern "C" fn sod2se_plugin_entry(version: u32, output: *mut PluginApi) -> i32 {
    boundary(|| {
        if version != ABI_VERSION || output.is_null() {
            return Err(UNSUPPORTED);
        }
        unsafe {
            *output = PluginApi {
                abi_version: ABI_VERSION,
                struct_size: std::mem::size_of::<PluginApi>() as u32,
                id: Utf8::borrowed("example"),
                version: Utf8::borrowed(env!("CARGO_PKG_VERSION")),
                start: Some(start),
                stop: Some(stop),
            };
        }
        Ok(())
    })
}
unsafe extern "C" fn start(api: *const HostApi) -> i32 {
    boundary(|| {
        let host = unsafe { Host::from_raw(api)? };
        host.request("settings.register", json!({"definitions":[
            {"id":"enabled","kind":"boolean","default":false,"minimum":null,"maximum":null,"label":"example.enabled","description":"example.enabled.help","apply":"immediate","risk":"normal"},
            {"id":"number","kind":"integer","default":5,"minimum":1,"maximum":10,"label":"example.number","description":"example.number.help","apply":"immediate","risk":"experimental"},
            {"id":"risk_preview","kind":"boolean","default":false,"minimum":null,"maximum":null,"label":"example.risk","description":"example.risk.help","apply":"immediate","risk":"dangerous"},
            {"id":"restart_preview","kind":"integer","default":1,"minimum":0,"maximum":10,"label":"example.restart","description":"example.restart.help","apply":"restart","risk":"normal"}
        ]}))?;
        host.request("translation.register",json!({
            "en-US":{"example.title":"Developer test example","example.description":"Configuration only; no gameplay changes","example.enabled":"Test toggle","example.enabled.help":"Tests Registry persistence only","example.number":"Test number","example.number.help":"Tests range, input and persistence only","example.risk":"Danger confirmation test","example.risk.help":"UI test only; no gameplay effect. Confirms that cancellation, single-use consent and Registry refusal work correctly.","example.restart":"Restart indicator test","example.restart.help":"UI test only; no gameplay effect. This deliberately long explanation verifies wrapping, fixed font size and scrolling with the mouse, keyboard and Xbox controller. A saved value and a running Mod’s effective value must be distinguished. This fixture does not apply any gameplay changes."},
            "zh-CN":{"example.title":"开发验收示例","example.description":"仅测试配置，不改变玩法","example.enabled":"测试开关","example.enabled.help":"仅用于验证 Registry 保存","example.number":"测试数值","example.number.help":"仅用于验证范围、输入和保存","example.risk":"危险确认流程测试","example.risk.help":"仅测试界面，不影响游戏。用于验证取消、一次性确认凭据和 Registry 拒绝行为。","example.restart":"重启提示测试","example.restart.help":"仅测试界面，不影响游戏。这是一段较长说明，用于验证固定字号、自动换行，以及鼠标、键盘和 Xbox 手柄滚动阅读。保存值与 Mod 实际运行中的生效值需要分别表达。本示例不会执行任何玩法修改。请检查说明能否完整阅读、焦点是否清晰，并确认返回操作能恢复到原菜单。"}
        }))?;
        host.log(1, "EXAMPLE_READY", "Example registered without MCM");
        Ok(())
    })
}
unsafe extern "C" fn stop() -> i32 {
    OK
}
