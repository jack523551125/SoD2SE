//! Native ABI 1. This is a separate contract from legacy managed plugin API 1.
use std::ffi::c_void;

pub const ABI_VERSION: u32 = 1;
pub const OK: i32 = 0;
pub const INVALID: i32 = -1;
pub const UNSUPPORTED: i32 = -2;
pub const BUSY: i32 = -3;
pub const INTERNAL: i32 = -4;
pub const BUFFER_TOO_SMALL: i32 = -5;
pub const NOT_FOUND: i32 = -6;
pub const STALE: i32 = -7;

#[repr(C)]
#[derive(Clone, Copy)]
pub struct Utf8 {
    pub data: *const u8,
    pub len: u32,
}
impl Utf8 {
    pub fn borrowed(value: &str) -> Self {
        Self {
            data: value.as_ptr(),
            len: value.len() as u32,
        }
    }
    /// # Safety
    /// Nonempty data must reference readable memory for len bytes until this call returns.
    pub unsafe fn read<'a>(self) -> Result<&'a str, i32> {
        if self.len > 1024 * 1024 || (self.len != 0 && self.data.is_null()) {
            return Err(INVALID);
        }
        if self.len == 0 {
            return Ok("");
        }
        std::str::from_utf8(unsafe { std::slice::from_raw_parts(self.data, self.len as usize) })
            .map_err(|_| INVALID)
    }
}

pub type Request =
    unsafe extern "C" fn(*mut c_void, u64, Utf8, Utf8, *mut u8, u32, *mut u32) -> i32;
pub type Log = unsafe extern "C" fn(*mut c_void, u64, u32, Utf8, Utf8) -> i32;
#[repr(C)]
#[derive(Clone, Copy)]
pub struct HostApi {
    pub abi_version: u32,
    pub struct_size: u32,
    pub context: *mut c_void,
    pub owner: u64,
    pub request: Option<Request>,
    pub log: Option<Log>,
}
pub type Start = unsafe extern "C" fn(*const HostApi) -> i32;
pub type Stop = unsafe extern "C" fn() -> i32;
#[repr(C)]
#[derive(Clone, Copy)]
pub struct PluginApi {
    pub abi_version: u32,
    pub struct_size: u32,
    pub id: Utf8,
    pub version: Utf8,
    pub start: Option<Start>,
    pub stop: Option<Stop>,
}
pub type Entry = unsafe extern "C" fn(u32, *mut PluginApi) -> i32;

/// All public entrypoints contain Rust unwinding; access violations are not recoverable here.
pub fn boundary(f: impl FnOnce() -> Result<(), i32>) -> i32 {
    match std::panic::catch_unwind(std::panic::AssertUnwindSafe(f)) {
        Ok(Ok(())) => OK,
        Ok(Err(code)) => code,
        Err(_) => INTERNAL,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn layouts() {
        assert_eq!(std::mem::size_of::<Utf8>(), 16);
        assert_eq!(std::mem::size_of::<HostApi>(), 40);
        assert_eq!(std::mem::size_of::<PluginApi>(), 56);
    }
    #[test]
    fn panic_is_contained() {
        assert_eq!(boundary(|| panic!("fixture")), INTERNAL);
    }
    #[test]
    fn rejects_invalid_strings() {
        assert!(
            unsafe {
                Utf8 {
                    data: std::ptr::null(),
                    len: 2,
                }
                .read()
            }
            .is_err()
        );
    }
}
