//! Thin client: does not own a registry, game addresses, or runtime state.
pub use serde_json;
pub use serde_json::{Value, json};
pub use sod2se_abi::*;
#[derive(Clone, Copy)]
pub struct Host {
    api: HostApi,
}
// The host contract serializes services and permits requests from plugin workers.
unsafe impl Send for Host {}
unsafe impl Sync for Host {}
impl Host {
    /// # Safety
    /// api must point to a live HostApi whose context/functions outlive this Host.
    pub unsafe fn from_raw(api: *const HostApi) -> Result<Self, i32> {
        if api.is_null() {
            return Err(INVALID);
        }
        let api = unsafe { *api };
        if api.abi_version != ABI_VERSION
            || api.struct_size < std::mem::size_of::<HostApi>() as u32
            || api.request.is_none()
            || api.owner == 0
        {
            return Err(UNSUPPORTED);
        }
        Ok(Self { api })
    }
    pub fn request(&self, operation: &str, input: Value) -> Result<Value, i32> {
        let input = input.to_string();
        // A single call prevents retries from duplicating mutations.
        let size = if [
            "settings.snapshot",
            "plugins.snapshot",
            "ui.actions",
            "ui.extensions",
            "events.poll",
        ]
        .contains(&operation)
        {
            1024 * 1024
        } else {
            8192
        };
        let mut output = vec![0u8; size];
        let mut length = 0;
        let status = unsafe {
            self.api.request.unwrap()(
                self.api.context,
                self.api.owner,
                Utf8::borrowed(operation),
                Utf8::borrowed(&input),
                output.as_mut_ptr(),
                output.len() as u32,
                &mut length,
            )
        };
        if status != OK {
            return Err(status);
        }
        if length as usize > output.len() {
            return Err(INTERNAL);
        }
        serde_json::from_slice(&output[..length as usize]).map_err(|_| INTERNAL)
    }
    pub fn log(&self, level: u32, code: &str, message: &str) {
        if let Some(log) = self.api.log {
            unsafe {
                log(
                    self.api.context,
                    self.api.owner,
                    level,
                    Utf8::borrowed(code),
                    Utf8::borrowed(message),
                );
            }
        }
    }
}
