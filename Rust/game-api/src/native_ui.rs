//! Fixed 16535856 Iggy callback adapter, ported from MCM's reviewed NativeSettingsIggy.h.
//! Hash/export/slot facts are private to GameApi. No game/player pointer is retained by services.
use super::*;
use sod2se_abi::INTERNAL;
use sod2se_services::native_settings::Reply;
use std::{
    ffi::c_void,
    ptr,
    sync::atomic::{AtomicBool, AtomicUsize, Ordering},
};
use windows_sys::Win32::{
    Foundation::HMODULE,
    System::{LibraryLoader::*, Memory::*},
};
#[repr(C)]
struct IggyValue {
    kind: i32,
    padding: i32,
    atom: usize,
    number: f64,
    length: usize,
}
#[repr(C)]
struct Call {
    name: *const u8,
    length: i32,
    padding: i32,
    count: i32,
    padding2: i32,
    args: [IggyValue; 4],
}
type Callback = unsafe extern "C" fn(*mut c_void, *mut c_void, *mut Call) -> i32;
type ResultPath = unsafe extern "C" fn(*mut c_void) -> *mut c_void;
type SetInt = unsafe extern "C" fn(*mut c_void, *mut c_void, *const u8, i32) -> i32;
type SetText = unsafe extern "C" fn(*mut c_void, *mut c_void, *const u8, *const u8, i32) -> i32;
type Query = fn(i32, i32, i32, i32) -> Reply;
const IGGY_SHA: &str = "09049ffc7b48639c72336bb809035fa1c1b827e898693fbc2968165bd23940a6";
/// Select only a reviewed, hash-matched fixed-build UI surface.
pub fn asset_name(root: &Path) -> Result<&'static str, i32> {
    let receipt: serde_json::Value = serde_json::from_slice(
        &std::fs::read(root.join("SoD2SE/Assets/native-ui.json")).map_err(|_| INTERNAL)?,
    ).map_err(|_| INVALID)?;
    if receipt["schema"] != 1 || receipt["reviewed"] != true
        || receipt["game_sha256"].as_str() != Some(&target().sha256.to_lowercase()) {
        return Err(UNSUPPORTED);
    }
    let (name, original) = match receipt["asset"].as_str().unwrap_or("settings") {
        "settings" => ("settings", "d8d320363be69ea9dfb39b5c20c8de5237c642841fe3ac86b00f8115050fe06e"),
        "pause" => ("pause", "00b46a42a6fc83645ace9f7068b8fc3b34ed7c9abd0c185580abbfb5a7d53ab6"),
        _ => return Err(UNSUPPORTED),
    };
    if receipt["source_asset_sha256"].as_str() != Some(original)
        || receipt["sha256"].as_str() != Some(&sod2se_services::diagnostics::digest(&root.join(format!("SoD2SE/Assets/{name}.uasset")))?) {
        return Err(UNSUPPORTED);
    }
    Ok(name)
}
pub fn verify_files(root: &Path) -> Result<(), i32> {
    let path = root.join("StateOfDecay2/Plugins/IggyPlugin/Binaries/Win64/iggy_w64.dll");
    if sod2se_services::diagnostics::digest(&path)? != IGGY_SHA {
        return Err(UNSUPPORTED);
    }
    Ok(())
}
pub fn asset_names(root: &Path) -> Result<Vec<&'static str>, i32> {
    let primary = asset_name(root)?;
    let receipt: serde_json::Value = serde_json::from_slice(&std::fs::read(root.join("SoD2SE/Assets/native-ui.json")).map_err(|_| INTERNAL)?).map_err(|_| INVALID)?;
    let mut names = vec![primary];
    if let Some(extra) = receipt.get("additional_assets") {
        let entries = extra.as_array().ok_or(INVALID)?;
        if entries.len() > 2 { return Err(UNSUPPORTED); }
        for entry in entries {
            let (name, original)=match entry["asset"].as_str() {
                Some("main_menu") => ("main_menu","ab1b361d498e8dfba559930085a3f3c2c7a6d0d21fc0ec23e4eda8f9ca5392bb"),
                Some("settings") => ("settings","d8d320363be69ea9dfb39b5c20c8de5237c642841fe3ac86b00f8115050fe06e"),
                _ => return Err(UNSUPPORTED),
            };
            let actual_hash = sod2se_services::diagnostics::digest(&root.join(format!("SoD2SE/Assets/{name}.uasset")))?;
            if names.contains(&name) || entry["source_asset_sha256"] != original
                || entry["sha256"].as_str() != Some(actual_hash.as_str()) {
                return Err(UNSUPPORTED);
            }
            names.push(name);
        }
    }
    Ok(names)
}
static ORIGINAL: AtomicUsize = AtomicUsize::new(0);
static RESULT_PATH: AtomicUsize = AtomicUsize::new(0);
static SET_INT: AtomicUsize = AtomicUsize::new(0);
static SET_TEXT: AtomicUsize = AtomicUsize::new(0);
static WIDE: AtomicBool = AtomicBool::new(false);
static READY: AtomicBool = AtomicBool::new(false);
static TARGET: AtomicUsize = AtomicUsize::new(0);
static QUERY: std::sync::OnceLock<Query> = std::sync::OnceLock::new();
static MODULE: std::sync::OnceLock<usize> = std::sync::OnceLock::new();
unsafe extern "system" {
    fn MH_Initialize() -> i32;
    fn MH_CreateHook(target: *mut c_void, detour: *mut c_void, original: *mut *mut c_void) -> i32;
    fn MH_EnableHook(target: *mut c_void) -> i32;
    fn MH_RemoveHook(target: *mut c_void) -> i32;
    fn MH_DisableHook(target: *mut c_void) -> i32;
}
fn integer(value: &IggyValue, boolean: bool) -> Option<i32> {
    if value.kind == 4
        && value.number.is_finite()
        && value.number.fract() == 0.0
        && value.number >= i32::MIN as f64
        && value.number <= i32::MAX as f64
    {
        return Some(value.number as i32);
    }
    if boolean && value.kind == 3 {
        let n = value.number.to_bits() as u32;
        if n <= 1 {
            return Some(n as i32);
        }
    }
    None
}
unsafe extern "C" fn dispatch(user: *mut c_void, player: *mut c_void, call: *mut Call) -> i32 {
    let original: Callback = unsafe { std::mem::transmute(ORIGINAL.load(Ordering::Acquire)) };
    if call.is_null() {
        return unsafe { original(user, player, call) };
    }
    // Other external calls may have fewer than four args. Read only their fixed
    // header until this exact protocol/count qualifies the complete packet.
    let name_pointer = unsafe { std::ptr::addr_of!((*call).name).read() };
    let name_length = unsafe { std::ptr::addr_of!((*call).length).read() };
    let name = b"SoD2SE_Mcm_v1";
    let protocol_two = name_length == name.len() as i32 && !name_pointer.is_null() && unsafe { if WIDE.load(Ordering::Acquire) { *name_pointer.cast::<u16>().add(name.len()-1) == 50 } else { *name_pointer.add(name.len()-1) == 50 } };
    let ours = name_length == name.len() as i32
        && !name_pointer.is_null()
        && if WIDE.load(Ordering::Acquire) {
            unsafe { std::slice::from_raw_parts(name_pointer.cast::<u16>(), name.len()) }
                .iter()
                .zip(name)
                .enumerate().all(|(i,(a,b))| *a == *b as u16 || (i==name.len()-1 && protocol_two))
        } else {
            { let bytes=unsafe { std::slice::from_raw_parts(name_pointer,name.len()) }; bytes==name || (protocol_two && bytes[..name.len()-1]==name[..name.len()-1]) }
        };
    if !ours {
        return unsafe { original(user, player, call) };
    }
    if unsafe { std::ptr::addr_of!((*call).count).read() } != 4 || player.is_null() {
        return 0;
    }
    let call = unsafe { &*call };
    let reply = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        if call.count != 4 {
            return Reply::Number(-3);
        }
        let mut args = [0; 4];
        for (i, v) in call.args.iter().enumerate() {
            let Some(n) = integer(v, i == 3 && args[0] == 15) else {
                return Reply::Number(-3);
            };
            args[i] = n;
        }
        if !(0..=if protocol_two {30} else {28}).contains(&args[0]) { return Reply::Number(-2); }
        QUERY.get().map_or(Reply::Number(-4), |query| {
            query(args[0] + if protocol_two {1000} else {0}, args[1], args[2], args[3])
        })
    }))
    .unwrap_or(Reply::Number(-4));
    let result: ResultPath = unsafe { std::mem::transmute(RESULT_PATH.load(Ordering::Acquire)) };
    let path = unsafe { result(player) };
    if path.is_null() {
        return 0;
    }
    let written = match reply {
        Reply::Text(text) => {
            let set: SetText = unsafe { std::mem::transmute(SET_TEXT.load(Ordering::Acquire)) };
            unsafe {
                set(
                    path,
                    ptr::null_mut(),
                    ptr::null(),
                    text.as_ptr(),
                    text.len() as i32,
                )
            }
        }
        Reply::Number(n) => {
            let set: SetInt = unsafe { std::mem::transmute(SET_INT.load(Ordering::Acquire)) };
            unsafe { set(path, ptr::null_mut(), ptr::null(), n) }
        }
        Reply::Edit { .. } => 0,
    };
    (written != 0) as i32
}
pub fn ready() -> bool {
    READY.load(Ordering::Acquire)
}
pub fn try_install(query: Query) -> Result<bool, i32> {
    if ready() {
        return Ok(true);
    }
    process::verify_current()?;
    let module = MODULE.get().map_or_else(
        || unsafe { GetModuleHandleW(process::wide(Path::new("iggy_w64.dll")).as_ptr()) },
        |m| *m as HMODULE,
    );
    if module.is_null() {
        return Ok(false);
    }
    if MODULE.get().is_none() {
        if sod2se_services::diagnostics::digest(&process::module_path(module)?)? != IGGY_SHA {
            return Err(UNSUPPORTED);
        }
        let mut pinned = ptr::null_mut();
        if unsafe {
            GetModuleHandleExW(
                GET_MODULE_HANDLE_EX_FLAG_PIN,
                process::wide(Path::new("iggy_w64.dll")).as_ptr(),
                &mut pinned,
            )
        } == 0
            || pinned != module
        {
            return Err(UNSUPPORTED);
        }
        MODULE.set(module as usize).map_err(|_| sod2se_abi::BUSY)?;
    }
    let base = module as usize;
    let exports = [
        (c"IggyPlayerCallbackResultPath", 0x66890usize, &RESULT_PATH),
        (c"IggyValueSetS32RS", 0x67880, &SET_INT),
        (c"IggyValueSetStringUTF8RS", 0x67a30, &SET_TEXT),
    ];
    for (name, rva, store) in exports {
        let address =
            unsafe { GetProcAddress(module, name.as_ptr().cast()) }.ok_or(UNSUPPORTED)? as usize;
        if address != base + rva {
            return Err(UNSUPPORTED);
        }
        store.store(address, Ordering::Release);
    }
    let mut callback = unsafe { ptr::read((base + 0x101d50) as *const usize) };
    let wide = callback == 0;
    if wide {
        callback = unsafe { ptr::read((base + 0x101d60) as *const usize) };
    }
    if callback == 0 {
        return Ok(false);
    }
    let mut memory: MEMORY_BASIC_INFORMATION = unsafe { std::mem::zeroed() };
    if unsafe {
        VirtualQuery(
            callback as *const c_void,
            &mut memory,
            std::mem::size_of::<MEMORY_BASIC_INFORMATION>(),
        )
    } == 0
        || memory.AllocationBase != unsafe { GetModuleHandleW(ptr::null()) }.cast()
        || ![PAGE_EXECUTE, PAGE_EXECUTE_READ, PAGE_EXECUTE_READWRITE].contains(&memory.Protect)
    {
        return Err(UNSUPPORTED);
    }
    let init = unsafe { MH_Initialize() };
    if ![0, 1].contains(&init) {
        return Err(sod2se_abi::INTERNAL);
    }
    QUERY.set(query).map_err(|_| sod2se_abi::BUSY)?;
    WIDE.store(wide, Ordering::Release);
    let mut original = ptr::null_mut();
    if unsafe {
        MH_CreateHook(
            callback as *mut c_void,
            dispatch as *mut c_void,
            &mut original,
        )
    } != 0
    {
        return Err(sod2se_abi::INTERNAL);
    }
    ORIGINAL.store(original as usize, Ordering::Release);
    if unsafe { MH_EnableHook(callback as *mut c_void) } != 0 {
        unsafe {
            MH_RemoveHook(callback as *mut c_void);
        }
        return Err(sod2se_abi::INTERNAL);
    }
    READY.store(true, Ordering::Release);
    TARGET.store(callback, Ordering::Release);
    Ok(true)
}
pub fn shutdown() -> Result<(), i32> {
    let target = TARGET.load(Ordering::Acquire);
    if target == 0 {
        return Ok(());
    }
    if unsafe { MH_DisableHook(target as *mut c_void) } != 0 {
        return Err(sod2se_abi::INTERNAL);
    }
    READY.store(false, Ordering::Release);
    Ok(())
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn abi_layout() {
        assert_eq!(std::mem::size_of::<IggyValue>(), 32);
        assert_eq!(std::mem::offset_of!(Call, args), 24);
    }
    #[test]
    fn typed_arguments() {
        let mut v = IggyValue {
            kind: 4,
            padding: 0,
            atom: 0,
            number: 2.5,
            length: 0,
        };
        assert_eq!(integer(&v, false), None);
        v.number = f64::NAN;
        assert_eq!(integer(&v, false), None);
        v.kind = 3;
        v.number = f64::from_bits(0xdeadbeef00000001);
        assert_eq!(integer(&v, true), Some(1));
    }
}
