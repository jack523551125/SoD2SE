use super::*;
use sod2se_game_api::process::{module_path, wide};
use std::ptr;
use windows_sys::Win32::Foundation::FreeLibrary;
use windows_sys::Win32::System::LibraryLoader::*;

// Modules remain resident until game exit. Only services and callbacks are withdrawn on stop.
struct Loaded {
    _module: usize,
    owner: u64,
    stop: Stop,
}
static LOADED: OnceLock<Mutex<Vec<Loaded>>> = OnceLock::new();
static STARTED: std::sync::atomic::AtomicBool = std::sync::atomic::AtomicBool::new(false);
pub fn start() -> Result<(), i32> {
    sod2se_game_api::process::verify_current()?;
    if STARTED.swap(true, std::sync::atomic::Ordering::AcqRel) {
        return Err(BUSY);
    }
    let result = start_inner();
    if result.is_err() {
        cleanup();
    }
    result
}
fn start_inner() -> Result<(), i32> {
    sod2se_game_api::process::verify_current()?;
    if SERVICES.get().is_some() {
        return Err(BUSY);
    }
    let image = module_path(ptr::null_mut())?;
    let root = image
        .parent()
        .and_then(|p| p.parent())
        .and_then(|p| p.parent())
        .and_then(|p| p.parent())
        .ok_or(INVALID)?;
    let local = PathBuf::from(std::env::var_os("LOCALAPPDATA").ok_or(INVALID)?);
    let profile = std::env::var("SOD2SE_PROFILE").unwrap_or_else(|_| "default".into());
    if !sod2se_services::valid_id(&profile) {
        return Err(INVALID);
    }
    let data = local.join("StateOfDecay2/SoD2SE/Rust").join(profile);
    let session = data.join("session.json");
    let mut services = Services::open(data, true)?;
    services.catalog.locale = sod2se_game_api::language::detect(root, &local);
    let legacy = local.join("StateOfDecay2/SoD2SE/mcm.ini");
    if legacy.exists() {
        services.settings.import_legacy(&legacy)?;
    }
    SERVICES.set(Mutex::new(services)).map_err(|_| BUSY)?;
    LOADED.set(Mutex::new(Vec::new())).map_err(|_| BUSY)?;
    let plugins = root.join("Plugins");
    for (path, _) in sod2se_services::plugin::discover(&plugins)? {
        load(&path)?;
    }
    // UI resources are inert until an explicit, package-verified receipt is present.
    let receipt = root.join("SoD2SE/Assets/native-ui.json");
    if receipt.exists()
        && !SERVICES
            .get()
            .unwrap()
            .lock()
            .map_err(|_| INTERNAL)?
            .ui
            .extensions()
            .is_empty()
    {
        let receipt: Value = serde_json::from_slice(&std::fs::read(receipt).map_err(|_| INTERNAL)?)
            .map_err(|_| INVALID)?;
        if receipt["game_sha256"].as_str()
            != Some(&sod2se_game_api::target().sha256.to_ascii_lowercase())
            || receipt["reviewed"].as_bool() != Some(true)
        {
            cleanup();
            return Err(UNSUPPORTED);
        }
        let asset = root.join("SoD2SE/Assets/settings.uasset");
        if sod2se_services::diagnostics::digest(&asset)?
            != receipt["sha256"].as_str().ok_or(INVALID)?
        {
            cleanup();
            return Err(UNSUPPORTED);
        }
        super::workers::spawn("SoD2SE-NativeUI", || {
            while !super::workers::stopping() {
                match sod2se_game_api::native_ui::try_install(super::native_query) {
                    Ok(true) => break,
                    Ok(false) => std::thread::sleep(std::time::Duration::from_millis(100)),
                    Err(code) => {
                        if let Ok(s) = SERVICES.get().unwrap().lock() {
                            let _ = s.logger.write(
                                3,
                                "game-api",
                                "NATIVE_UI_REFUSED",
                                &format!("Iggy adapter: {code}"),
                            );
                        }
                        break;
                    }
                }
            }
        })?;
    }
    SERVICES
        .get()
        .unwrap()
        .lock()
        .map_err(|_| INTERNAL)?
        .logger
        .write(
            1,
            "runtime",
            "RUNTIME_READY",
            "Native runtime initialized; save/UI acceptance remains pending",
        )?;
    let (listener, endpoint) = sod2se_services::transport::bind(&session)?;
    listener.set_nonblocking(true).map_err(|_| INTERNAL)?;
    super::workers::spawn("SoD2SE-Diagnostics", move || {
        while !super::workers::stopping() {
            let mut stream = match listener.accept() {
                Ok((stream, _)) => stream,
                Err(e) if e.kind() == std::io::ErrorKind::WouldBlock => {
                    std::thread::sleep(std::time::Duration::from_millis(10));
                    continue;
                }
                Err(_) => break,
            };
            let timeout = Some(std::time::Duration::from_secs(2));
            let _ = stream.set_read_timeout(timeout);
            let _ = stream.set_write_timeout(timeout);
            let result = (|| -> Result<Value, i32> {
                let request = sod2se_services::transport::receive(&mut stream)?;
                if request["nonce"].as_str() != Some(&endpoint.nonce) {
                    return Err(INVALID);
                }
                let operation = request["operation"].as_str().ok_or(INVALID)?;
                if ![
                    "capabilities",
                    "plugins.snapshot",
                    "settings.snapshot",
                    "settings.get",
                    "settings.set",
                    "translation.locale",
                    "ui.extensions",
                ]
                .contains(&operation)
                {
                    return Err(UNSUPPORTED);
                }
                let mut services = SERVICES.get().unwrap().lock().map_err(|_| INTERNAL)?;
                // A tools identity can only use the explicit diagnostic allowlist above.
                services.owners.insert(u64::MAX, "developer-tools".into());
                services.frontends.insert(u64::MAX);
                let result = services.request(u64::MAX, operation, request["input"].clone());
                services.owners.remove(&u64::MAX);
                services.frontends.remove(&u64::MAX);
                result
            })();
            let (status, value) = match result {
                Ok(value) => (OK, value),
                Err(code) => (code, Value::Null),
            };
            let _ = sod2se_services::transport::send(
                &mut stream,
                &json!({"pid":endpoint.pid,"status":status,"value":value}),
            );
        }
    })?;
    super::workers::spawn("SoD2SE-Scheduler", || {
        while !super::workers::stopping() {
            if let Ok(mut services) = SERVICES.get().unwrap().lock() {
                services.tick();
            }
            std::thread::sleep(std::time::Duration::from_millis(10));
        }
    })?;
    Ok(())
}
fn load(path: &std::path::Path) -> Result<(), i32> {
    let checked = sod2se_services::plugin::Manifest::read(path)?;
    checked.verify(path.parent().ok_or(INVALID)?)?;
    let manifest = serde_json::to_value(checked).map_err(|_| INVALID)?;
    if manifest["abi"].as_u64() != Some(ABI_VERSION as u64) {
        return Err(UNSUPPORTED);
    }
    let id = manifest["id"].as_str().ok_or(INVALID)?;
    let file = manifest["file"].as_str().ok_or(INVALID)?;
    if !sod2se_services::valid_id(id)
        || !sod2se_services::install::safe_relative(file)
        || file.contains('/')
    {
        return Err(INVALID);
    }
    let library = path.parent().ok_or(INVALID)?.join(file);
    if sod2se_services::diagnostics::digest(&library)?
        != manifest["sha256"].as_str().ok_or(INVALID)?
    {
        return Err(INVALID);
    }
    let library = library.canonicalize().map_err(|_| INTERNAL)?;
    let parent = path
        .parent()
        .ok_or(INVALID)?
        .canonicalize()
        .map_err(|_| INTERNAL)?;
    if !library.starts_with(parent) {
        return Err(INVALID);
    }
    let module = unsafe {
        LoadLibraryExW(
            wide(&library).as_ptr(),
            ptr::null_mut(),
            LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR | LOAD_LIBRARY_SEARCH_DEFAULT_DIRS,
        )
    };
    if module.is_null() {
        return Err(INTERNAL);
    }
    let Some(entry) = (unsafe { GetProcAddress(module, c"sod2se_plugin_entry".as_ptr().cast()) })
    else {
        unsafe {
            FreeLibrary(module);
        }
        return Err(UNSUPPORTED);
    };
    let entry: Entry = unsafe { std::mem::transmute(entry) };
    let mut api = std::mem::MaybeUninit::<PluginApi>::zeroed();
    let result = unsafe { entry(ABI_VERSION, api.as_mut_ptr()) };
    if result != OK {
        unsafe {
            FreeLibrary(module);
        }
        return Err(result);
    }
    let api = unsafe { api.assume_init() };
    if api.abi_version != ABI_VERSION
        || api.struct_size < std::mem::size_of::<PluginApi>() as u32
        || unsafe { api.id.read()? } != id
        || unsafe { api.version.read()? } != manifest["version"].as_str().ok_or(INVALID)?
    {
        return Err(UNSUPPORTED);
    }
    let stop = api.stop.ok_or(INVALID)?;
    let begin = api.start.ok_or(INVALID)?;
    let owner = {
        let mut services = SERVICES.get().unwrap().lock().map_err(|_| INTERNAL)?;
        if services.owners.values().any(|x| x == id) {
            return Err(INVALID);
        }
        let owner = services
            .owners
            .keys()
            .next_back()
            .copied()
            .unwrap_or(0)
            .checked_add(1)
            .ok_or(INTERNAL)?;
        services.owners.insert(owner, id.into());
        owner
    };
    if manifest["permissions"]
        .as_array()
        .is_some_and(|a| a.iter().any(|p| p == "settings.frontend"))
    {
        SERVICES
            .get()
            .unwrap()
            .lock()
            .map_err(|_| INTERNAL)?
            .frontends
            .insert(owner);
    }
    let host = host_api(owner);
    let result = unsafe { begin(&host) };
    if result != OK {
        unsafe {
            stop();
        }
        let _ = SERVICES
            .get()
            .unwrap()
            .lock()
            .map_err(|_| INTERNAL)?
            .cleanup(owner);
        return Err(result);
    }
    LOADED
        .get()
        .unwrap()
        .lock()
        .map_err(|_| INTERNAL)?
        .push(Loaded {
            _module: module as usize,
            owner,
            stop,
        });
    Ok(())
}
fn cleanup() {
    super::workers::stop();
    let _ = sod2se_game_api::native_ui::shutdown();
    if let Some(loaded) = LOADED.get()
        && let Ok(mut loaded) = loaded.lock()
    {
        for plugin in loaded.drain(..).rev() {
            let stopped = unsafe { (plugin.stop)() };
            if let Some(s) = SERVICES.get()
                && let Ok(mut s) = s.lock()
            {
                let cleaned = s.cleanup(plugin.owner);
                if stopped != OK || cleaned.is_err() {
                    let _ = s.logger.write(
                        3,
                        "runtime",
                        "CLEANUP_REFUSED",
                        "Plugin cleanup did not complete; exit the game before changing files",
                    );
                }
            }
        }
    }
}
