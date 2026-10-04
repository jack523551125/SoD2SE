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
        host.request("settings.register", json!({"definitions":[{"id":"enabled","kind":"boolean","default":false,"minimum":null,"maximum":null,"label":"example.enabled","description":"example.enabled.help","apply":"immediate","risk":"normal"}]}))?;
        host.log(1, "EXAMPLE_READY", "Example registered without MCM");
        Ok(())
    })
}
unsafe extern "C" fn stop() -> i32 {
    OK
}
