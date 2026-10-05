use super::*;
use sod2se_game_api::process::{Handle, wide};
use std::{ffi::c_void, os::windows::process::CommandExt, ptr};
use windows_sys::Win32::System::Diagnostics::Debug::WriteProcessMemory;
use windows_sys::Win32::{
    Foundation::*,
    System::{Diagnostics::ToolHelp::*, LibraryLoader::*, Memory::*, Threading::*},
};

fn remote_module(pid: u32, name: &Path) -> Result<usize, i32> {
    for _ in 0..100 {
        match remote_module_once(pid, name) {
            Err(sod2se_abi::NOT_FOUND) => std::thread::sleep(std::time::Duration::from_millis(20)),
            result => return result,
        }
    }
    Err(sod2se_abi::NOT_FOUND)
}
fn remote_module_once(pid: u32, name: &Path) -> Result<usize, i32> {
    let snapshot = module_snapshot(pid)?;
    if snapshot.0 == INVALID_HANDLE_VALUE {
        return Err(INTERNAL);
    }
    let mut entry: MODULEENTRY32W = unsafe { std::mem::zeroed() };
    entry.dwSize = std::mem::size_of::<MODULEENTRY32W>() as u32;
    let mut present = unsafe { Module32FirstW(snapshot.0, &mut entry) } != 0;
    while present {
        let n = entry
            .szExePath
            .iter()
            .position(|&c| c == 0)
            .unwrap_or(entry.szExePath.len());
        let path = PathBuf::from(String::from_utf16_lossy(&entry.szExePath[..n]));
        if same_module_path(&path, name) {
            return Ok(entry.modBaseAddr as usize);
        }
        present = unsafe { Module32NextW(snapshot.0, &mut entry) } != 0;
    }
    Err(sod2se_abi::NOT_FOUND)
}
pub(super) fn injection_self_test() -> Result<(), String> {
    let executable = std::env::current_exe().map_err(|e| e.to_string())?;
    let directory = executable.parent().ok_or("Missing test binary directory")?;
    let runtime = directory
        .join(if directory.join("sod2se_runtime.dll").exists() {
            "sod2se_runtime.dll"
        } else {
            "SoD2SE.Runtime.dll"
        })
        .canonicalize()
        .map_err(|e| e.to_string())?;
    let mut child = Command::new(&executable)
        .arg("--inert-host-child")
        .spawn()
        .map_err(|e| e.to_string())?;
    let result = if unsafe { GetModuleHandleW(wide(Path::new("usvfs_x64.dll")).as_ptr()) }.is_null()
    {
        inject(child.id(), &runtime)
    } else {
        ensure_usvfs(&mut child).and_then(|_| inject(child.id(), &runtime))
    };
    // This process was created exclusively as an authored non-game ABI fixture.
    let _ = child.kill();
    let _ = child.wait();
    if result != Err(sod2se_abi::UNSUPPORTED) {
        return Err(format!(
            "Inert injection expected bootstrap UNSUPPORTED, got {result:?}"
        ));
    }
    println!(
        "PASS: remote Runtime loaded in an authored inert child; bootstrap refused the foreign image"
    );
    Ok(())
}
fn same_module_path(left: &Path, right: &Path) -> bool {
    fn normalize(path: &Path) -> String {
        let path = path.to_string_lossy().replace('/', "\\");
        let lower = path.to_lowercase();
        if let Some(unc) = lower.strip_prefix("\\\\?\\unc\\") {
            format!("\\\\{unc}")
        } else {
            lower.strip_prefix("\\\\?\\").unwrap_or(&lower).to_owned()
        }
    }
    normalize(left) == normalize(right)
}
fn diagnostic(code: &str, message: &str) {
    eprintln!("{code}: {message}");
    if let Some(local) = std::env::var_os("LOCALAPPDATA") {
        let _ = sod2se_services::diagnostics::Logger::new(
            PathBuf::from(local).join("StateOfDecay2/SoD2SE/Rust/loader.jsonl"),
        )
        .write(1, "loader", code, message);
    }
}
fn module_snapshot(pid: u32) -> Result<Handle, i32> {
    for _ in 0..100 {
        let handle =
            unsafe { CreateToolhelp32Snapshot(TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32, pid) };
        if handle != INVALID_HANDLE_VALUE {
            return Ok(Handle(handle));
        }
        let error = unsafe { GetLastError() };
        if ![ERROR_BAD_LENGTH, ERROR_PARTIAL_COPY].contains(&error) {
            diagnostic(
                "MODULE_SNAPSHOT_FAILED",
                &format!("PID {pid}; Win32 {error}"),
            );
            return Err(INTERNAL);
        }
        std::thread::sleep(std::time::Duration::from_millis(20));
    }
    Err(sod2se_abi::BUSY)
}
fn ensure_usvfs(child: &mut std::process::Child) -> Result<(), i32> {
    let deadline = std::time::Instant::now() + std::time::Duration::from_secs(10);
    while std::time::Instant::now() < deadline {
        if let Some(status) = child.try_wait().map_err(|_| INTERNAL)? {
            diagnostic(
                "CHILD_EXITED_BEFORE_USVFS",
                &format!("PID {}; {status}", child.id()),
            );
            return Err(INTERNAL);
        }
        let snapshot = module_snapshot(child.id())?;
        let mut entry: MODULEENTRY32W = unsafe { std::mem::zeroed() };
        entry.dwSize = std::mem::size_of::<MODULEENTRY32W>() as u32;
        let mut present = unsafe { Module32FirstW(snapshot.0, &mut entry) } != 0;
        while present {
            let count = entry
                .szModule
                .iter()
                .position(|&c| c == 0)
                .unwrap_or(entry.szModule.len());
            let name = String::from_utf16_lossy(&entry.szModule[..count]).to_ascii_lowercase();
            if name.starts_with("usvfs") && name.ends_with(".dll") {
                diagnostic("MO2_CHILD_READY", &format!("PID {}", child.id()));
                return Ok(());
            }
            present = unsafe { Module32NextW(snapshot.0, &mut entry) } != 0;
        }
        std::thread::sleep(std::time::Duration::from_millis(20));
    }
    diagnostic(
        "MO2_CHILD_USVFS_TIMEOUT",
        "Created child did not expose USVFS within the readiness deadline",
    );
    Err(sod2se_abi::UNSUPPORTED)
}
fn invoke(process: HANDLE, function: usize, argument: *const c_void) -> Result<u32, i32> {
    let routine: unsafe extern "system" fn(*mut c_void) -> u32 =
        unsafe { std::mem::transmute(function) };
    let thread = Handle(unsafe {
        CreateRemoteThread(
            process,
            ptr::null(),
            0,
            Some(routine),
            argument,
            0,
            ptr::null_mut(),
        )
    });
    if thread.0.is_null() {
        return Err(INTERNAL);
    }
    if unsafe { WaitForSingleObject(thread.0, 15000) } != WAIT_OBJECT_0 {
        return Err(sod2se_abi::BUSY);
    }
    let mut result = 0;
    if unsafe { GetExitCodeThread(thread.0, &mut result) } == 0 {
        return Err(INTERNAL);
    }
    Ok(result)
}
fn inject(pid: u32, runtime: &Path) -> Result<(), i32> {
    diagnostic("INJECTION_BEGIN", &format!("PID {pid}"));
    let process = Handle(unsafe {
        OpenProcess(
            PROCESS_CREATE_THREAD
                | PROCESS_QUERY_INFORMATION
                | PROCESS_VM_OPERATION
                | PROCESS_VM_WRITE
                | PROCESS_VM_READ,
            0,
            pid,
        )
    });
    if process.0.is_null() {
        return Err(INTERNAL);
    }
    let kernel = unsafe { GetModuleHandleW(wide(Path::new("kernel32.dll")).as_ptr()) };
    let load =
        unsafe { GetProcAddress(kernel, c"LoadLibraryW".as_ptr().cast()) }.ok_or(INTERNAL)?;
    let mut owner = ptr::null_mut();
    if unsafe {
        GetModuleHandleExW(
            GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
            load as *const u16,
            &mut owner,
        )
    } == 0
    {
        return Err(INTERNAL);
    }
    let owner_path = sod2se_game_api::process::module_path(owner)?;
    let remote_owner = remote_module(pid, &owner_path)?;
    let name = wide(runtime);
    let size = name.len() * 2;
    let memory = unsafe {
        VirtualAllocEx(
            process.0,
            ptr::null(),
            size,
            MEM_COMMIT | MEM_RESERVE,
            PAGE_READWRITE,
        )
    };
    if memory.is_null() {
        return Err(INTERNAL);
    }
    let mut written = 0;
    if unsafe { WriteProcessMemory(process.0, memory, name.as_ptr().cast(), size, &mut written) }
        == 0
        || written != size
    {
        unsafe {
            VirtualFreeEx(process.0, memory, 0, MEM_RELEASE);
        }
        return Err(INTERNAL);
    }
    let result = invoke(
        process.0,
        remote_owner + load as usize - owner as usize,
        memory,
    );
    // A timed-out remote thread may still read this allocation. Leave it resident.
    if result != Err(sod2se_abi::BUSY) {
        unsafe {
            VirtualFreeEx(process.0, memory, 0, MEM_RELEASE);
        }
    }
    result?;
    diagnostic(
        "LOAD_LIBRARY_RETURNED",
        "Remote library call completed; checking full module address",
    );
    // Confirm the full module address; remote-thread exit codes cannot hold a 64-bit HMODULE.
    let remote = remote_module(pid, runtime).inspect_err(|_| {
        diagnostic(
            "RUNTIME_MODULE_NOT_FOUND",
            "Library absent or module path mismatch",
        )
    })?;
    diagnostic(
        "RUNTIME_MODULE_FOUND",
        "Full Runtime module address resolved",
    );
    let local = unsafe {
        LoadLibraryExW(
            wide(runtime).as_ptr(),
            ptr::null_mut(),
            DONT_RESOLVE_DLL_REFERENCES,
        )
    };
    if local.is_null() {
        return Err(INTERNAL);
    }
    let export = unsafe { GetProcAddress(local, c"sod2se_runtime_start".as_ptr().cast()) };
    let address = export.map(|f| remote + f as usize - local as usize);
    unsafe {
        FreeLibrary(local);
    }
    let status = invoke(process.0, address.ok_or(INTERNAL)?, ptr::null())? as i32;
    diagnostic("RUNTIME_BOOTSTRAP_RESULT", &format!("status {status}"));
    if status != sod2se_abi::OK {
        return Err(status);
    }
    Ok(())
}
pub(super) fn launch(exe: &Path, options: &Options) -> Result<(), i32> {
    let instance = Handle(unsafe {
        CreateMutexW(
            ptr::null(),
            0,
            wide(Path::new("Local\\SoD2SE.Native.Loader")).as_ptr(),
        )
    });
    if instance.0.is_null() || unsafe { GetLastError() } == ERROR_ALREADY_EXISTS {
        return Err(sod2se_abi::BUSY);
    }
    // Never recover an overlay while another loader is using it.
    if !options.preflight {
        recover_resources(options)?;
    }
    let dir = std::env::current_exe()
        .map_err(|_| INTERNAL)?
        .parent()
        .ok_or(INVALID)?
        .to_path_buf();
    let runtime = dir
        .join("SoD2SE.Runtime.dll")
        .canonicalize()
        .map_err(|_| INTERNAL)?;
    if dir.canonicalize().map_err(|_| INTERNAL)?
        != sod2se_game_api::game_root(exe)?
            .canonicalize()
            .map_err(|_| INTERNAL)?
    {
        return Err(INVALID);
    }
    let manifest: sod2se_services::install::Manifest = serde_json::from_slice(
        &std::fs::read(dir.join("framework.manifest.json")).map_err(|_| INTERNAL)?,
    )
    .map_err(|_| INVALID)?;
    manifest.verify(&dir)?;
    let info: serde_json::Value = serde_json::from_slice(
        &std::fs::read(dir.join("SoD2SE/build-info.json")).map_err(|_| INTERNAL)?,
    )
    .map_err(|_| INVALID)?;
    let revision = info["revision"].as_str().ok_or(INVALID)?;
    if info["version"].as_str() != Some(env!("CARGO_PKG_VERSION")) {
        return Err(sod2se_abi::UNSUPPORTED);
    }
    let asset = sod2se_game_api::native_ui::asset_name(&dir)?;
    let (target, ownership) = overlay_paths(&options.profile, asset)?;
    let mut mounted = false;
    // In MO2 this directory is virtual and its creation target is overwrite.
    if !options.mo2 {
        std::fs::create_dir_all(dir.join("Plugins")).map_err(|_| INTERNAL)?;
    }
    let plugins = sod2se_services::plugin::discover_all(&dir)?;
    if plugins
        .iter()
        .any(|(_, m)| m.framework_revision != revision)
    {
        return Err(sod2se_abi::UNSUPPORTED);
    }
    let ui_required = plugins.iter().any(|(_, m)| {
        m.capabilities
            .iter()
            .any(|c| c == sod2se_game_api::SETTINGS || c == sod2se_game_api::PAUSE_MCM)
    });
    if ui_required {
        sod2se_game_api::native_ui::verify_files(&dir)?;
        let receipt: serde_json::Value = serde_json::from_slice(
            &std::fs::read(dir.join("SoD2SE/Assets/native-ui.json")).map_err(|_| INTERNAL)?,
        )
        .map_err(|_| INVALID)?;
        if receipt["reviewed"].as_bool() != Some(true)
            || receipt["game_sha256"].as_str()
                != Some(&sod2se_game_api::target().sha256.to_lowercase())
        {
            return Err(sod2se_abi::UNSUPPORTED);
        }
        let hash = receipt["sha256"].as_str().ok_or(INVALID)?;
        if options.mo2 {
            if sod2se_services::diagnostics::digest(&target)? != hash {
                return Err(sod2se_abi::UNSUPPORTED);
            }
        } else if !options.preflight {
            sod2se_services::overlay::prepare(
                &dir.join(format!("SoD2SE/Assets/{asset}.uasset")),
                hash,
                &target,
                &ownership,
            )?;
            mounted = true;
        }
    }
    if options.preflight {
        diagnostic(
            "PREFLIGHT_READY",
            "Version, framework, plugin dependencies and native UI preflight passed; game not started",
        );
        return Ok(());
    }
    let mut command = Command::new(exe);
    command
        .current_dir(exe.parent().ok_or(INVALID)?)
        .env("SOD2SE_PROFILE", &options.profile);
    if !options.arguments.is_empty() {
        command.raw_arg(&options.arguments);
    }
    let mut child = match command.spawn() {
        Ok(child) => child,
        Err(_) => {
            if mounted {
                let _ = sod2se_services::overlay::recover(&target, &ownership);
            }
            return Err(INTERNAL);
        }
    };
    // MO2 launches this exact child with inherited USVFS; never attach or search unrelated games.
    let result = (|| -> Result<(), i32> {
        if options.mo2 {
            ensure_usvfs(&mut child)?;
        }
        inject(child.id(), &runtime)
    })();
    if let Err(code) = result {
        eprintln!("RUNTIME_REFUSED: {code}; game session remains tracked until exit");
    }
    // Keep the GUI/MO2 parent alive for the complete game session, including failed initialization.
    child.wait().map_err(|_| INTERNAL)?;
    if mounted {
        sod2se_services::overlay::recover(&target, &ownership)?;
    }
    result
}
fn overlay_paths(profile: &str, asset: &str) -> Result<(PathBuf, PathBuf), i32> {
    let local = PathBuf::from(std::env::var_os("LOCALAPPDATA").ok_or(INVALID)?);
    if !["settings", "pause"].contains(&asset) { return Err(sod2se_abi::UNSUPPORTED); }
    Ok((local.join(format!("StateOfDecay2/Saved/Cooked/WindowsNoEditor/StateOfDecay2/Content/Art/UI/{asset}.uasset")),local.join("StateOfDecay2/SoD2SE/Rust").join(profile).join(if asset=="settings" {"ui-overlay.json"} else {"pause-ui-overlay.json"})))
}
pub(super) fn recover_resources(options: &Options) -> Result<(), i32> {
    if options.mo2 {
        return Ok(());
    }
    for asset in ["settings", "pause"] {
        let (target, ownership) = overlay_paths(&options.profile, asset)?;
        sod2se_services::overlay::recover(&target, &ownership)?;
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn extended_paths_identify_the_same_module_without_basename_matching() {
        assert!(same_module_path(
            Path::new(r"\\?\E:\Game\SoD2SE.Runtime.dll"),
            Path::new(r"E:\Game\SoD2SE.Runtime.dll")
        ));
        assert!(same_module_path(
            Path::new(r"\\?\UNC\server\share\Runtime.dll"),
            Path::new(r"\\server\share\Runtime.dll")
        ));
        assert!(!same_module_path(
            Path::new(r"E:\Other\Runtime.dll"),
            Path::new(r"E:\Game\Runtime.dll")
        ));
    }
}
