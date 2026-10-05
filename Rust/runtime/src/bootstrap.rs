use super::*;
use sod2se_game_api::process::{module_path, wide};
use std::ptr;
use windows_sys::Win32::Foundation::{FreeLibrary, HMODULE};
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
    if let Err(code) = result {
        if let Some(services) = SERVICES.get()
            && let Ok(s) = services.lock()
        {
            let _ = s.logger.write(3, "runtime", "RUNTIME_INIT_REFUSED",
                &format!("Initialization status {code}; acquired plugin resources will be withdrawn"));
        }
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
    let package: sod2se_services::install::Manifest = serde_json::from_slice(
        &std::fs::read(root.join("framework.manifest.json")).map_err(|_| INTERNAL)?,
    )
    .map_err(|_| INVALID)?;
    package.verify(root)?;
    let info: Value = serde_json::from_slice(
        &std::fs::read(root.join("SoD2SE/build-info.json")).map_err(|_| INTERNAL)?,
    )
    .map_err(|_| INVALID)?;
    let revision = info["revision"].as_str().ok_or(INVALID)?;
    if info["version"].as_str() != Some(env!("CARGO_PKG_VERSION")) {
        return Err(UNSUPPORTED);
    }
    let discovered = sod2se_services::plugin::discover_all(root)?;
    if discovered
        .iter()
        .any(|(_, manifest)| manifest.framework_revision != revision)
    {
        return Err(UNSUPPORTED);
    }
    let local = PathBuf::from(std::env::var_os("LOCALAPPDATA").ok_or(INVALID)?);
    let profile = std::env::var("SOD2SE_PROFILE").unwrap_or_else(|_| "default".into());
    if !sod2se_services::valid_id(&profile) {
        return Err(INVALID);
    }
    let data = local.join("StateOfDecay2/SoD2SE/Rust").join(&profile);
    let session = data.join("session.json");
    let early_logger = Logger::new(data.join("runtime.jsonl"));
    let config_path = root
        .join("Plugins/SoD2SE/Settings")
        .join(&profile)
        .join("registry.json");
    let mut services =
        Services::open_with_settings(data.clone(), config_path, true).inspect_err(|code| {
            let _ = early_logger.write(
                3,
                "runtime",
                "SERVICES_OPEN_REFUSED",
                &format!("status {code}"),
            );
        })?;
    let ui_assets = sod2se_game_api::native_ui::asset_names(root)?;
    let ui_asset = ui_assets[0];
    services.ui_surface = ui_asset.into();
    services.logger.write(
        1,
        "runtime",
        "SERVICES_OPENED",
        "Profile services initialized",
    )?;
    services
        .settings
        .import_document(&data.join("settings.json"))?;
    services.catalog.locale = sod2se_game_api::language::detect(root, &local);
    let legacy = local.join("StateOfDecay2/SoD2SE/mcm.ini");
    if legacy.exists() {
        services
            .settings
            .import_legacy(&legacy)
            .inspect_err(|code| {
                let _ = services.logger.write(
                    3,
                    "runtime",
                    "LEGACY_IMPORT_REFUSED",
                    &format!("status {code}"),
                );
            })?;
    }
    SERVICES.set(Mutex::new(services)).map_err(|_| BUSY)?;
    LOADED.set(Mutex::new(Vec::new())).map_err(|_| BUSY)?;
    for (path, _) in discovered {
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
        // Revalidate through the same GameApi selector used by Loader. A pause
        // package must never fall back to the retired settings resource path.
        let active_assets = sod2se_game_api::native_ui::asset_names(root).inspect_err(|code| {
            if let Ok(s) = SERVICES.get().unwrap().lock() {
                let _ = s.logger.write(3, "game-api", "UI_RESOURCE_REFUSED",
                    &format!("surface {ui_asset}; validation status {code}"));
            }
        })?;
        if active_assets != ui_assets {
            return Err(UNSUPPORTED);
        }
        SERVICES.get().unwrap().lock().map_err(|_| INTERNAL)?.logger.write(
            1, "game-api", "UI_RESOURCE_VERIFIED", &format!("Validated {active_assets:?} resources before callback activation"))?;
        super::workers::spawn("SoD2SE-NativeUI", || {
            while !super::workers::stopping() {
                match sod2se_game_api::native_ui::try_install(super::native_query) {
                    Ok(true) => {
                        if let Ok(s) = SERVICES.get().unwrap().lock() {
                            let _ = s.logger.write(1, "game-api", "NATIVE_UI_READY", "Fixed-build callback adapter ready");
                        }
                        break;
                    },
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
    let name = path
        .file_name()
        .map(|v| v.to_string_lossy().into_owned())
        .unwrap_or_else(|| "unknown plugin".into());
    let result = load_inner(path);
    if let Err(code) = result
        && let Some(services) = SERVICES.get()
        && let Ok(services) = services.lock()
    {
        let _ = services.logger.write(
            3,
            "runtime",
            "PLUGIN_LOAD_REFUSED",
            &format!("{name}: {code}"),
        );
    }
    result
}
struct InspectedPlugin {
    module: HMODULE,
    manifest: sod2se_services::plugin::Manifest,
    api: PluginApi,
    resident: bool,
}
impl Drop for InspectedPlugin {
    fn drop(&mut self) {
        if !self.resident {
            unsafe {
                FreeLibrary(self.module);
            }
        }
    }
}
fn inspect_plugin(path: &std::path::Path) -> Result<InspectedPlugin, i32> {
    let manifest = sod2se_services::plugin::Manifest::read(path)?;
    // Preserve the virtual namespace for LoadLibraryExW. In USVFS the virtual
    // Plugins directory stays under the game root while DLL bytes resolve to
    // MO2's source tree, so comparing canonical physical paths rejects a
    // valid, hash-verified mapped plugin.
    let library = manifest.verify(path.parent().ok_or(INVALID)?)?;
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
    let mut plugin = InspectedPlugin {
        module,
        manifest,
        api: unsafe { std::mem::zeroed() },
        resident: false,
    };
    let Some(entry) = (unsafe { GetProcAddress(module, c"sod2se_plugin_entry".as_ptr().cast()) })
    else {
        return Err(UNSUPPORTED);
    };
    let entry: Entry = unsafe { std::mem::transmute(entry) };
    let mut api = std::mem::MaybeUninit::<PluginApi>::zeroed();
    let result = unsafe { entry(ABI_VERSION, api.as_mut_ptr()) };
    if result != OK {
        return Err(result);
    }
    let api = unsafe { api.assume_init() };
    if api.abi_version != ABI_VERSION
        || api.struct_size < std::mem::size_of::<PluginApi>() as u32
        || unsafe { api.id.read()? } != plugin.manifest.id
        || unsafe { api.version.read()? } != plugin.manifest.version
    {
        return Err(UNSUPPORTED);
    }
    api.stop.ok_or(INVALID)?;
    api.start.ok_or(INVALID)?;
    plugin.api = api;
    Ok(plugin)
}
#[unsafe(no_mangle)]
/// Inspect a plugin's verified DLL and ABI without activating its callbacks.
/// # Safety
/// manifest_path must reference readable UTF-8 storage for the duration of the call.
pub unsafe extern "C" fn sod2se_runtime_probe_plugin_v1(manifest_path: Utf8) -> i32 {
    boundary(|| {
        let path = std::path::Path::new(unsafe { manifest_path.read()? });
        let _plugin = inspect_plugin(path)?;
        Ok(())
    })
}
fn load_inner(path: &std::path::Path) -> Result<(), i32> {
    let mut plugin = inspect_plugin(path)?;
    let module = plugin.module;
    let id = plugin.manifest.id.as_str();
    let stop = plugin.api.stop.ok_or(INVALID)?;
    let begin = plugin.api.start.ok_or(INVALID)?;
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
        services.versions.insert(owner, plugin.manifest.version.clone());
        owner
    };
    if plugin
        .manifest
        .permissions
        .iter()
        .any(|p| p == "settings.frontend")
    {
        SERVICES
            .get()
            .unwrap()
            .lock()
            .map_err(|_| INTERNAL)?
            .frontends
            .insert(owner);
    }
    // Once activation begins, the module remains resident even on startup failure.
    plugin.resident = true;
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
