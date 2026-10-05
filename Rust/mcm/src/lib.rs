//! Optional settings frontend. Registry and native game/UI access remain host-owned.
#![allow(non_snake_case)] // Preserve the published DLL filename.
use sod2se_sdk::*;
use std::sync::{
    Arc, Mutex,
    atomic::{AtomicBool, Ordering},
};
struct Worker {
    stop: Arc<AtomicBool>,
    thread: std::thread::JoinHandle<()>,
}
static WORKER: Mutex<Option<Worker>> = Mutex::new(None);
#[unsafe(no_mangle)]
/// # Safety
/// ABI 1 callers provide writable PluginApi storage and keep the host table live through stop.
pub unsafe extern "C" fn sod2se_plugin_entry(version: u32, output: *mut PluginApi) -> i32 {
    boundary(|| {
        if version != ABI_VERSION || output.is_null() {
            return Err(UNSUPPORTED);
        }
        unsafe {
            *output = PluginApi {
                abi_version: ABI_VERSION,
                struct_size: std::mem::size_of::<PluginApi>() as u32,
                id: Utf8::borrowed("mcm"),
                version: Utf8::borrowed(env!("CARGO_PKG_VERSION")),
                start: Some(start),
                stop: Some(stop),
            };
        }
        Ok(())
    })
}
fn publish(host: Host, revision: u64) -> Result<(), i32> {
    let snapshot = host.request("settings.snapshot", json!({}))?;
    let plugins = host.request("plugins.snapshot", json!({}))?;
    let mut pages = Vec::new();
    let mut rows = Vec::new();
    if let Some(modules) = snapshot["definitions"].as_object() {
        for (module, definitions) in modules {
            if module == "mcm" && definitions.as_object().is_some_and(|d|d.is_empty()) { continue; }
            let page = pages.len();
            let name = host.request("translation.get", json!({"key":format!("{module}.title")}))?;
            let description = host.request(
                "translation.get",
                json!({"key":format!("{module}.description")}),
            )?;
            let plugin=plugins.as_array().and_then(|a|a.iter().find(|p|p["id"].as_str()==Some(module.as_str())));
            pages.push(json!({"version":plugin.and_then(|p|p.get("version")),"id":module,"name":name,"description":description,"loaded":plugins.as_array().is_some_and(|a|a.iter().any(|p|p["id"].as_str()==Some(module.as_str())))}));
            if let Some(definitions) = definitions.as_object() {
                for (id, definition) in definitions {
                    let mut value = snapshot["values"][module][id].clone();
                    if value.is_null() {
                        value = definition["default"].clone();
                    }
                    let boolean = definition["kind"] == "boolean";
                    let translate = |key: &str| {
                        host.request("translation.get", json!({"key":definition[key]}))
                            .ok()
                            .and_then(|v| v.as_str().map(str::to_owned))
                            .unwrap_or_else(|| definition[key].as_str().unwrap_or("").into())
                    };
                    let lo = if boolean {
                        0
                    } else {
                        definition["minimum"].as_i64().ok_or(INVALID)?
                    };
                    let hi = if boolean {
                        1
                    } else {
                        definition["maximum"].as_i64().ok_or(INVALID)?
                    };
                    let n = if boolean {
                        value.as_bool().ok_or(INVALID)? as i64
                    } else {
                        value.as_i64().ok_or(INVALID)?
                    };
                    rows.push(json!({"module":module,"id":id,"page":page,"label":translate("label"),"description":translate("description"),"kind":if boolean{0}else{1},"value":i32::try_from(n).map_err(|_|INVALID)?,"minimum":i32::try_from(lo).map_err(|_|INVALID)?,"maximum":i32::try_from(hi).map_err(|_|INVALID)?,"restart":definition["apply"]=="restart","risk":definition["risk"],"default_value":if boolean { definition["default"].as_bool().map(|v|v as i32) } else { definition["default"].as_i64().and_then(|v|i32::try_from(v).ok()) }}));
                }
            }
        }
    }
    let locale = host.request("translation.locale", json!({}))?;
    let contract:Value=serde_catalog(include_str!("../ui-contract.json"))?;
    let chrome:Vec<Value>=contract["chrome_keys"].as_array().ok_or(INVALID)?.iter().map(|key|host.request("translation.get",json!({"key":key}))).collect::<Result<_,_>>()?;
    host.request("ui.publish",json!({"id":"mcm.settings","model":{"presentation":2,"chrome":chrome,"revision":revision,"settings_revision":snapshot["revision"],"language":locale,"pages":pages,"options":rows}}))?;
    Ok(())
}
unsafe extern "C" fn start(api: *const HostApi) -> i32 {
    boundary(|| {
        let host = unsafe { Host::from_raw(api)? };
        let mut slot = WORKER.lock().map_err(|_| INTERNAL)?;
        if slot.is_some() {
            return Err(BUSY);
        }
        host.request("translation.register",json!({"en-US":serde_catalog(include_str!("../locales/en-US.json"))?,"zh-CN":serde_catalog(include_str!("../locales/zh-CN.json"))?}))?;
        host.request("settings.register", json!({"definitions":[]}))?;
        host.request("ui.register",json!({"id":"mcm.settings","target":"pause","title":"mcm.title","description":"mcm.description"}))?;
        publish(host, 1)?;
        let stop = Arc::new(AtomicBool::new(false));
        let signal = stop.clone();
        let thread=std::thread::Builder::new().name("SoD2SE-MCM".into()).spawn(move|| {
            let mut revision=2u64;
            while !signal.load(Ordering::Acquire) {
                match host.request("ui.actions",json!({"id":"mcm.settings"})) {
                    Ok(actions)=> if let Some(actions)=actions.as_array() { for action in actions {
                        if action["action"]=="set" {
                            let value=&action["value"];
                            let result=host.request("settings.set",json!({"module":value["module"],"id":value["id"],"value":value["value"],"revision":value["settings_revision"],"risk_ack":value["risk_ack"]}));
                            let (status,message)=match result {Ok(_)=>(0,host.request("translation.get",json!({"key":"mcm.ui.saved"})).ok().and_then(|v|v.as_str().map(str::to_owned)).unwrap_or_default()),Err(error)=>{host.log(3,"MCM_SETTING_REFUSED",&format!("Registry refused {}.{}: {error}",value["module"].as_str().unwrap_or("?"),value["id"].as_str().unwrap_or("?")));(error,host.request("translation.get",json!({"key":if error==STALE{"mcm.ui.stale"}else{"mcm.ui.failed"}})).ok().and_then(|v|v.as_str().map(str::to_owned)).unwrap_or_default())}};
                            let _=host.request("ui.complete",json!({"token":value["token"],"status":status,"message":message}));
                        }
                    } },
                    Err(error)=>host.log(3,"MCM_ACTIONS_REFUSED",&format!("UI actions unavailable: {error}")),
                }
                if let Err(error)=publish(host,revision) { host.log(3,"MCM_PUBLISH_REFUSED",&format!("Settings view unavailable: {error}")); }
                revision=match revision.checked_add(1){Some(r)=>r,None=>break};
                std::thread::sleep(std::time::Duration::from_millis(100));
            }
        }).map_err(|_|INTERNAL)?;
        *slot = Some(Worker { stop, thread });
        host.log(
            1,
            "MCM_READY",
            "Optional Registry frontend registered; native UI readiness is reported by GameApi",
        );
        Ok(())
    })
}
fn serde_catalog(text: &str) -> Result<Value, i32> {
    sod2se_sdk::serde_json::from_str(text).map_err(|_| INVALID)
}
unsafe extern "C" fn stop() -> i32 {
    boundary(|| {
        let worker = WORKER.lock().map_err(|_| INTERNAL)?.take();
        if let Some(worker) = worker {
            worker.stop.store(true, Ordering::Release);
            worker.thread.join().map_err(|_| INTERNAL)?;
        }
        Ok(())
    })
}
#[cfg(test)]
mod tests {
    use super::*;
    static GATE: Mutex<()> = Mutex::new(());
    static OPERATIONS: Mutex<Vec<String>> = Mutex::new(Vec::new());
    unsafe extern "C" fn request(
        _: *mut std::ffi::c_void,
        _: u64,
        op: Utf8,
        _: Utf8,
        out: *mut u8,
        capacity: u32,
        used: *mut u32,
    ) -> i32 {
        let name = unsafe { op.read().unwrap() };
        OPERATIONS.lock().unwrap().push(name.into());
        let value = match name {
            "settings.snapshot" => {
                json!({"revision":0,"definitions":{"example":{"enabled":{"kind":"boolean","default":false,"minimum":null,"maximum":null,"label":"example.enabled","description":"example.help","apply":"immediate","risk":"normal"}}},"values":{}})
            }
            "plugins.snapshot" => json!([{"id":"example"}]),
            "ui.actions" => json!([]),
            "translation.locale" => json!("en-US"),
            "translation.get" => json!("Example"),
            "settings.register" | "translation.register" | "ui.register" | "ui.publish" => {
                json!({})
            }
            _ => return UNSUPPORTED,
        };
        let bytes = value.to_string();
        if bytes.len() > capacity as usize {
            return BUFFER_TOO_SMALL;
        }
        unsafe {
            std::ptr::copy_nonoverlapping(bytes.as_ptr(), out, bytes.len());
            *used = bytes.len() as u32;
        }
        OK
    }
    #[test]
    fn abi_rejects_legacy_without_starting_worker() {
        let _guard = GATE.lock().unwrap();
        assert_eq!(
            unsafe { sod2se_plugin_entry(0, std::ptr::null_mut()) },
            UNSUPPORTED
        );
        assert_eq!(unsafe { stop() }, OK);
    }
    #[test]
    fn frontend_publishes_registry_model_and_joins_worker() {
        let _guard = GATE.lock().unwrap();
        OPERATIONS.lock().unwrap().clear();
        let host = HostApi {
            abi_version: ABI_VERSION,
            struct_size: std::mem::size_of::<HostApi>() as u32,
            context: std::ptr::null_mut(),
            owner: 1,
            request: Some(request),
            log: None,
        };
        assert_eq!(unsafe { start(&host) }, OK);
        assert_eq!(unsafe { start(&host) }, BUSY);
        assert_eq!(unsafe { stop() }, OK);
        let operations = OPERATIONS.lock().unwrap();
        assert!(operations.iter().any(|o| o == "settings.snapshot"));
        assert!(operations.iter().any(|o| o == "ui.publish"));
        assert!(operations.iter().all(|o| !o.starts_with("game.")));
    }
}
