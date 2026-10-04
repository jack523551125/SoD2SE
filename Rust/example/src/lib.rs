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
            {"id":"number","kind":"integer","default":5,"minimum":1,"maximum":10,"label":"example.number","description":"example.number.help","apply":"immediate","risk":"experimental"}
        ]}))?;
        host.request("translation.register",json!({
            "en-US":{"example.title":"Developer test example","example.description":"Configuration only; no gameplay changes","example.enabled":"Test toggle","example.enabled.help":"Tests Registry persistence only","example.number":"Test number","example.number.help":"Tests range, input and persistence only"},
            "zh-CN":{"example.title":"开发验收示例","example.description":"仅测试配置，不改变玩法","example.enabled":"测试开关","example.enabled.help":"仅用于验证 Registry 保存","example.number":"测试数值","example.number.help":"仅用于验证范围、输入和保存"}
        }))?;
        host.log(1, "EXAMPLE_READY", "Example registered without MCM");
        Ok(())
    })
}
unsafe extern "C" fn stop() -> i32 {
    OK
}
