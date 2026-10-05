//! Native runtime bootstrap. DllMain is deliberately absent: initialization is explicit.
use serde_json::{Value, json};
use sod2se_abi::*;
use sod2se_services::{
    diagnostics::Logger,
    settings::{Definition, Registry},
    ui::{Extension, Model, UiRegistry},
};
use std::{
    collections::BTreeMap,
    path::PathBuf,
    sync::{Mutex, OnceLock},
};

pub struct Services {
    state: sod2se_services::state::Store,
    pub settings: Registry,
    pub ui: UiRegistry,
    pub ui_surface: String,
    pub owners: BTreeMap<u64, String>,
    pub logger: Logger,
    #[cfg(windows)]
    followers: sod2se_game_api::process::FollowerLease,
    pub game_verified: bool,
    pub catalog: sod2se_services::translation::Catalog,
    pub native_session: sod2se_services::native_settings::Session,
    pub frontends: std::collections::BTreeSet<u64>,
    pub events: sod2se_services::events::Events,
    pub scheduler: sod2se_services::events::Scheduler,
    subscriptions: BTreeMap<u64, u64>,
    epoch: std::time::Instant,
}
impl Services {
    pub fn open(path: PathBuf, game_verified: bool) -> Result<Self, i32> {
        let settings = path.join("settings.json");
        Self::open_with_settings(path, settings, game_verified)
    }
    pub fn open_with_settings(
        path: PathBuf,
        settings: PathBuf,
        game_verified: bool,
    ) -> Result<Self, i32> {
        Ok(Self {
            state: sod2se_services::state::Store::open(&path.join("state"))?,
            settings: Registry::open(settings)?,
            ui: UiRegistry::default(),
            ui_surface: "settings".into(),
            owners: BTreeMap::new(),
            logger: Logger::new(path.join("runtime.jsonl")),
            game_verified,
            catalog: sod2se_services::translation::Catalog::new("en-US".into()),
            native_session: Default::default(),
            frontends: Default::default(),
            events: Default::default(),
            scheduler: Default::default(),
            subscriptions: Default::default(),
            epoch: std::time::Instant::now(),
            #[cfg(windows)]
            followers: Default::default(),
        })
    }
    pub fn request(&mut self, owner: u64, operation: &str, input: Value) -> Result<Value, i32> {
        let module = self.owners.get(&owner).ok_or(INVALID)?.clone();
        let string = |name: &str| input[name].as_str().ok_or(INVALID);
        match operation {
            "state.read" | "state.write" => {
                if string("scope")? != "profile" {
                    return Err(UNSUPPORTED);
                }
                let schema =
                    u32::try_from(input["schema"].as_u64().ok_or(INVALID)?).map_err(|_| INVALID)?;
                if operation == "state.read" {
                    serde_json::to_value(self.state.read(&module, schema)?).map_err(|_| INTERNAL)
                } else {
                    let revision = self.state.write(
                        &module,
                        schema,
                        input["revision"].as_u64().ok_or(INVALID)?,
                        input.get("value").ok_or(INVALID)?.clone(),
                    )?;
                    Ok(json!({"revision":revision}))
                }
            }
            "events.subscribe" => {
                let handle = self.events.subscribe(owner, string("prefix")?.into())?;
                self.subscriptions.insert(handle, owner);
                Ok(json!({"handle":handle}))
            }
            "events.poll" => {
                let handle = input["handle"].as_u64().ok_or(INVALID)?;
                if self.subscriptions.get(&handle) != Some(&owner) {
                    return Err(INVALID);
                }
                let (cursor, events) = self
                    .events
                    .poll(handle, input["since"].as_u64().ok_or(INVALID)?)?;
                Ok(json!({"cursor":cursor,"events":events}))
            }
            "events.publish" => {
                let id = string("id")?;
                if !id.starts_with(&format!("mod.{module}.")) {
                    return Err(INVALID);
                }
                Ok(json!({"sequence":self.events.publish(owner,id.into(),input["data"].clone())?}))
            }
            "tasks.schedule" => Ok(
                json!({"handle":self.scheduler.schedule(owner,self.epoch.elapsed().as_millis() as u64,input["delay_ms"].as_u64().ok_or(INVALID)?,input["repeat_ms"].as_u64())?}),
            ),
            "tasks.cancel" => {
                self.scheduler
                    .cancel(owner, input["handle"].as_u64().ok_or(INVALID)?)?;
                Ok(json!({}))
            }
            "plugins.snapshot" => Ok(json!(
                self.owners
                    .iter()
                    .map(|(owner, id)| json!({"owner":owner,"id":id}))
                    .collect::<Vec<_>>()
            )),
            "translation.register" => {
                let entries = serde_json::from_value(input).map_err(|_| INVALID)?;
                self.catalog.register(owner, &module, entries)?;
                Ok(json!({}))
            }
            "translation.get" => Ok(json!(self.catalog.get(string("key")?))),
            "translation.locale" => Ok(json!(self.catalog.locale)),
            "capabilities" => {
                #[cfg(windows)]
                let (followers_active, followers_poisoned) =
                    (self.followers.active(), self.followers.poisoned());
                #[cfg(not(windows))]
                let (followers_active, followers_poisoned) = (false, false);
                #[cfg(windows)]
                let ui_ready = sod2se_game_api::native_ui::ready();
                #[cfg(not(windows))]
                let ui_ready = false;
                Ok(
                    json!({"game_build":sod2se_game_api::GAME_BUILD,"followers":self.game_verified && !followers_poisoned,"followers_active":followers_active,"followers_poisoned":followers_poisoned,"native_settings":ui_ready && self.ui_surface=="settings","native_pause_mcm":ui_ready && self.ui_surface=="pause","ui_surface":self.ui_surface,"live_acceptance":"NOT_RUN"}),
                )
            }
            "settings.register" => {
                let definitions: Vec<Definition> =
                    serde_json::from_value(input["definitions"].clone()).map_err(|_| INVALID)?;
                let schema =
                    u32::try_from(input["schema"].as_u64().unwrap_or(1)).map_err(|_| INVALID)?;
                self.settings
                    .register_schema(owner, &module, schema, definitions)?;
                Ok(json!({}))
            }
            "settings.snapshot" => Ok(
                json!({"revision":self.settings.document.revision,"definitions":self.settings.definitions,"values":self.settings.document.values,"schemas":self.settings.document.module_schemas}),
            ),
            "settings.schema" => Ok(json!(self.settings.schema(string("module")?))),
            "settings.migrate" => {
                let from = u32::try_from(input["from_schema"].as_u64().ok_or(INVALID)?)
                    .map_err(|_| INVALID)?;
                let to = u32::try_from(input["to_schema"].as_u64().ok_or(INVALID)?)
                    .map_err(|_| INVALID)?;
                let values =
                    serde_json::from_value(input["values"].clone()).map_err(|_| INVALID)?;
                Ok(
                    json!({"revision":self.settings.migrate(owner,&module,input["revision"].as_u64().ok_or(INVALID)?,from,to,values)?}),
                )
            }
            "settings.get" => Ok(self.settings.get(string("module")?, string("id")?)?),
            "settings.set" => {
                let target = string("module")?;
                if target != module && !self.frontends.contains(&owner) {
                    return Err(INVALID);
                }
                let revision = input["revision"].as_u64().ok_or(INVALID)?;
                Ok(
                    json!({"revision":self.settings.set(revision,target,string("id")?,input["value"].clone(),input["risk_ack"].as_bool().unwrap_or(false))?}),
                )
            }
            "settings.changes" => Ok(json!(
                self.settings
                    .changes(input["since"].as_u64().ok_or(INVALID)?)?
            )),
            "ui.register" => {
                let extension: Extension = serde_json::from_value(input).map_err(|_| INVALID)?;
                if self.game_verified && extension.target != self.ui_surface { return Err(UNSUPPORTED); }
                self.ui.register(owner, extension)?;
                Ok(json!({}))
            }
            "ui.publish" => {
                let model: Model =
                    serde_json::from_value(input["model"].clone()).map_err(|_| INVALID)?;
                self.ui.publish(owner, string("id")?, model)?;
                self.native_session.refresh(self.ui.models());
                Ok(json!({}))
            }
            "ui.actions" => Ok(json!(self.ui.drain(owner, string("id")?)?)),
            "ui.complete" => {
                if !self
                    .native_session
                    .pending_extension()
                    .is_some_and(|id| self.ui.owns(owner, id))
                {
                    return Err(INVALID);
                }
                self.native_session.complete(
                    i32::try_from(input["token"].as_i64().ok_or(INVALID)?).map_err(|_| INVALID)?,
                    i32::try_from(input["status"].as_i64().ok_or(INVALID)?).map_err(|_| INVALID)?,
                    string("message")?.into(),
                    self.settings.document.revision,
                )?;
                Ok(json!({}))
            }
            "ui.extensions" => Ok(json!(self.ui.extensions())),
            "game.followers.acquire" => {
                if !self.game_verified {
                    return Err(UNSUPPORTED);
                }
                #[cfg(windows)]
                {
                    self.followers.acquire(owner)?;
                    Ok(json!({"active":true}))
                }
                #[cfg(not(windows))]
                {
                    Err(UNSUPPORTED)
                }
            }
            "game.followers.release" => {
                #[cfg(windows)]
                {
                    self.followers.release(owner)?;
                    Ok(json!({"active":false}))
                }
                #[cfg(not(windows))]
                {
                    Err(UNSUPPORTED)
                }
            }
            _ => Err(UNSUPPORTED),
        }
    }
    pub fn cleanup(&mut self, owner: u64) -> Result<(), i32> {
        #[cfg(windows)]
        if self.followers.owned_by(owner) {
            self.followers.release(owner)?;
        }
        self.settings.unregister(owner);
        self.ui.unregister(owner);
        self.catalog.unregister(owner);
        self.owners.remove(&owner);
        self.frontends.remove(&owner);
        self.scheduler.unregister(owner);
        let handles: Vec<_> = self
            .subscriptions
            .iter()
            .filter(|(_, o)| **o == owner)
            .map(|(&id, _)| id)
            .collect();
        for handle in handles {
            self.subscriptions.remove(&handle);
            self.events.remove(handle);
        }
        Ok(())
    }
    pub fn tick(&mut self) {
        self.scheduler
            .tick(self.epoch.elapsed().as_millis() as u64, &mut self.events);
    }
}
static SERVICES: OnceLock<Mutex<Services>> = OnceLock::new();
unsafe extern "C" fn request(
    _context: *mut std::ffi::c_void,
    owner: u64,
    operation: Utf8,
    input: Utf8,
    output: *mut u8,
    capacity: u32,
    used: *mut u32,
) -> i32 {
    boundary(|| {
        if output.is_null() || used.is_null() || !(128..=1024 * 1024).contains(&capacity) {
            return Err(BUFFER_TOO_SMALL);
        }
        let operation = unsafe { operation.read()? };
        let input = unsafe { input.read()? };
        let value: Value = serde_json::from_str(input).map_err(|_| INVALID)?;
        let mut services = SERVICES
            .get()
            .ok_or(INTERNAL)?
            .lock()
            .map_err(|_| INTERNAL)?;
        let result = services.request(owner, operation, value);
        if let Err(code) = result {
            let _ = services.logger.write(
                3,
                &owner.to_string(),
                "SERVICE_FAILED",
                &format!("{operation}: {code}"),
            );
            return Err(code);
        }
        let bytes = serde_json::to_vec(&result.unwrap()).map_err(|_| INTERNAL)?;
        if bytes.len() > capacity as usize {
            return Err(BUFFER_TOO_SMALL);
        }
        unsafe {
            std::ptr::copy_nonoverlapping(bytes.as_ptr(), output, bytes.len());
            *used = bytes.len() as u32;
        }
        Ok(())
    })
}
unsafe extern "C" fn log(
    _context: *mut std::ffi::c_void,
    owner: u64,
    level: u32,
    code: Utf8,
    message: Utf8,
) -> i32 {
    boundary(|| {
        let services = SERVICES
            .get()
            .ok_or(INTERNAL)?
            .lock()
            .map_err(|_| INTERNAL)?;
        let module = services.owners.get(&owner).ok_or(INVALID)?;
        services
            .logger
            .write(level, module, unsafe { code.read()? }, unsafe {
                message.read()?
            })
    })
}
pub fn host_api(owner: u64) -> HostApi {
    HostApi {
        abi_version: ABI_VERSION,
        struct_size: std::mem::size_of::<HostApi>() as u32,
        context: std::ptr::null_mut(),
        owner,
        request: Some(request),
        log: Some(log),
    }
}
#[cfg(windows)]
fn native_query(
    op: i32,
    token: i32,
    index: i32,
    value: i32,
) -> sod2se_services::native_settings::Reply {
    use sod2se_services::native_settings::Reply;
    let Some(lock) = SERVICES.get() else {
        return Reply::Number(-4);
    };
    let Ok(mut services) = lock.try_lock() else {
        return Reply::Number(-3);
    };
    if op == 0 {
        let models = services.ui.models();
        return Reply::Number(services.native_session.open(models));
    }
    if op == 19 {
        let (level, code) = match index {
            0 => (1, "MCM_PANEL_OPENED"),
            1 => (1, "MCM_PANEL_CLOSED"),
            2 => (3, "MCM_PANEL_REFUSED"),
            _ => return Reply::Number(INVALID),
        };
        return match services.logger.write(level, "native-ui", code, "Independent pause panel lifecycle") {
            Ok(()) => Reply::Number(1),
            Err(code) => Reply::Number(code),
        };
    }
    match services.native_session.query(op, token, index, value) {
        Reply::Edit {
            extension,
            revision,
            token,
            value,
        } => match services.ui.action(&extension, revision, "set", value) {
            Ok(()) => Reply::Number(1),
            Err(code) => {
                let r = services.settings.document.revision;
                let _ = services.native_session.complete(
                    token,
                    code,
                    "Page changed; reopen settings / 页面已变化，请重新打开".into(),
                    r,
                );
                Reply::Number(-2)
            }
        },
        reply => reply,
    }
}
#[cfg(windows)]
mod bootstrap;
#[cfg(windows)]
mod workers;
#[unsafe(no_mangle)]
/// # Safety
/// Invoke only through the verified native bootstrap in the target process, outside DllMain.
pub unsafe extern "system" fn sod2se_runtime_start(_argument: *mut std::ffi::c_void) -> u32 {
    #[cfg(windows)]
    {
        boundary(bootstrap::start) as u32
    }
    #[cfg(not(windows))]
    {
        UNSUPPORTED as u32
    }
}
