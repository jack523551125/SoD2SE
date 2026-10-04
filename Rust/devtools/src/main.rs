use serde_json::json;
use std::path::PathBuf;
mod report;
fn run() -> Result<(), String> {
    let mut args = std::env::args().skip(1);
    match args.next().as_deref() {
        Some("verify-plugins") => {
            let game:PathBuf=args.next().ok_or("verify-plugins requires the game root")?.into();
            let package:sod2se_services::install::Manifest=serde_json::from_slice(&std::fs::read(game.join("framework.manifest.json")).map_err(|e|e.to_string())?).map_err(|e|e.to_string())?;
            package.verify(&game).map_err(|c|format!("PACKAGE_REFUSED: {c}"))?;
            let info:serde_json::Value=serde_json::from_slice(&std::fs::read(game.join("SoD2SE/build-info.json")).map_err(|e|e.to_string())?).map_err(|e|e.to_string())?;
            let plugins=sod2se_services::plugin::discover_all(&game).map_err(|c|format!("PLUGIN_PREFLIGHT_REFUSED: {c}"))?;
            if plugins.iter().any(|(_,manifest)|Some(manifest.framework_revision.as_str())!=info["revision"].as_str()) {return Err("PLUGIN_DEPENDENCY_REFUSED: framework revision mismatch".into());}
            println!("PASS: {} plugin manifests, ABI, hashes and framework pins",plugins.len());Ok(())
        },
        Some("recover-overlay") => {
            let profile=args.next().ok_or("recover-overlay requires a profile id")?;
            if !sod2se_services::valid_id(&profile){return Err("Invalid profile id".into());}
            ensure_stopped()?;
            let local=PathBuf::from(std::env::var_os("LOCALAPPDATA").ok_or("LOCALAPPDATA unavailable")?);
            sod2se_services::overlay::recover(
                &local.join("StateOfDecay2/Saved/Cooked/WindowsNoEditor/StateOfDecay2/Content/Art/UI/settings.uasset"),
                &local.join("StateOfDecay2/SoD2SE/Rust").join(profile).join("ui-overlay.json")
            ).map_err(|c|format!("OVERLAY_RECOVERY_REFUSED: {c}; foreign resources preserved"))?;
            println!("PASS: owned UI overlay recovered");Ok(())
        },
        Some("archive-legacy") | Some("restore-legacy") => {
            let archive=std::env::args().nth(1).as_deref()==Some("archive-legacy");
            let game:PathBuf=args.next().ok_or("An explicit game root is required")?.into();
            ensure_stopped()?;
            sod2se_game_api::verify_image(&game.join("StateOfDecay2/Binaries/Win64").join(sod2se_game_api::SHIPPING)).map_err(|c|format!("GAME_REFUSED: {c}"))?;
            if archive {
                let receipt:PathBuf=args.next().ok_or("archive-legacy requires a reviewed hash inventory")?.into();
                let review=serde_json::from_slice(&std::fs::read(receipt).map_err(|e|e.to_string())?).map_err(|e|e.to_string())?;
                sod2se_services::legacy::archive(&game,review)
            } else { sod2se_services::legacy::restore(&game) }
            .map_err(|c|format!("LEGACY_TRANSITION_REFUSED: {c}; restore only after native uninstall"))?;
            println!("PASS: reviewed legacy transition processed");Ok(())
        },
        Some("recover-settings") => {
            let path:PathBuf=args.next().ok_or("recover-settings requires an offline settings.json")?.into();
            sod2se_services::settings::Registry::recover(&path).map_err(|c|format!("SETTINGS_RECOVERY_REFUSED: {c}"))?;
            println!("PASS: last-good settings restored; damaged input preserved");Ok(())
        },
        Some("report") => {
            let session: PathBuf = args.next().ok_or("report requires an explicit session.json")?.into();
            let destination: PathBuf = args.next().ok_or("report requires a fresh output JSON path")?.into();
            if args.next().is_some() { return Err("Unexpected report argument".into()); }
            report::export(&session, &destination)?;
            println!("PASS: diagnostic report exported; live acceptance remains separate");
            Ok(())
        },
        Some("doctor") => {
            let image:PathBuf=args.next().ok_or("doctor requires the shipping EXE path")?.into();
            let result=sod2se_game_api::verify_image(&image);
            #[cfg(windows)]if args.next().as_deref()==Some("--native-ui") {let root=image.parent().and_then(|p|p.parent()).and_then(|p|p.parent()).and_then(|p|p.parent()).ok_or("Invalid shipping path")?;sod2se_game_api::native_ui::verify_files(root).map_err(|c|format!("NATIVE_UI_REFUSED: {c}"))?;}
            println!("{}",json!({"version":env!("CARGO_PKG_VERSION"),"expected_build":sod2se_game_api::GAME_BUILD,"image_verified":result.is_ok(),"error":result.err(),"live_acceptance":"NOT_RUN"}));
            result.map_err(|c|format!("GAME_REFUSED: {c}"))
        },
        Some("install")=>{
            let package:PathBuf=args.next().ok_or("install requires package Root")?.into();let game:PathBuf=args.next().ok_or("install requires game root")?.into();
            sod2se_game_api::verify_image(&game.join("StateOfDecay2/Binaries/Win64").join(sod2se_game_api::SHIPPING)).map_err(|c|format!("GAME_REFUSED: {c}"))?;
            ensure_stopped()?;
            sod2se_services::install::install(&package,&game).map_err(|c|format!("INSTALL_REFUSED: {c}; existing files preserved; pending transactions require recover-install"))?;println!("Installed SoD2SE prerequisite. MCM is optional.");Ok(())
        },
        Some("recover-install")|Some("uninstall")=>{
            let recover=std::env::args().nth(1).as_deref()==Some("recover-install");
            let game:PathBuf=args.next().ok_or("An explicit game root is required")?.into();ensure_stopped()?;
            if std::env::current_exe().map_err(|e|e.to_string())?.starts_with(game.canonicalize().map_err(|e|e.to_string())?){return Err("Run the tool from the original unpacked prerequisite package, outside the installed game directory".into());}
            let result=if recover{sod2se_services::install::recover(&game)}else{sod2se_services::install::uninstall(&game)};
            result.map_err(|c|format!("OWNERSHIP_REFUSED: {c}; modified files were preserved"))?;println!("Framework-owned files processed; configuration and saves retained");Ok(())
        },
        Some("settings") => {
            let path:PathBuf=args.next().ok_or("settings requires an explicit offline settings.json path")?.into();
            let registry=sod2se_services::settings::Registry::open(path).map_err(|c|format!("SETTINGS_REFUSED: {c}"))?;
            println!("{}",serde_json::to_string_pretty(&registry.document).map_err(|e|e.to_string())?); Ok(())
        },
        Some("connect")|Some("live-check")=>{
            let path:PathBuf=args.next().ok_or("An explicit runtime session.json path is required")?.into();
            let operation=args.next().unwrap_or_else(||"capabilities".into());
            if !["capabilities","plugins.snapshot","settings.snapshot","ui.extensions"].contains(&operation.as_str()){return Err("Unsupported diagnostic operation".into());}
            let result=sod2se_services::transport::connect(&path,&operation,json!({})).map_err(|c|format!("CONNECTION_REFUSED: {c}"))?;
            println!("{}",serde_json::to_string_pretty(&result).map_err(|e|e.to_string())?);Ok(())
        },
        Some("set")=>{
            let path:PathBuf=args.next().ok_or("set requires session.json")?.into();
            let module=args.next().ok_or("set requires module")?;let id=args.next().ok_or("set requires setting id")?;
            let value:serde_json::Value=serde_json::from_str(&args.next().ok_or("set requires a JSON value")?).map_err(|e|e.to_string())?;
            let acknowledgement=args.next().as_deref()==Some("--ack-risk");
            let snapshot=sod2se_services::transport::connect(&path,"settings.snapshot",json!({})).map_err(|c|format!("SNAPSHOT_REFUSED: {c}"))?;
            let result=sod2se_services::transport::connect(&path,"settings.set",json!({"module":module,"id":id,"value":value,"revision":snapshot["revision"],"risk_ack":acknowledgement})).map_err(|c|format!("SETTING_REFUSED: {c}"))?;
            println!("{result}");Ok(())
        },
        Some("verify-package") => {
            let root:PathBuf=args.next().ok_or("verify-package requires a package directory")?.into();
            let manifest:sod2se_services::install::Manifest=serde_json::from_slice(&std::fs::read(root.join("framework.manifest.json")).map_err(|e|e.to_string())?).map_err(|e|e.to_string())?;
            manifest.verify(&root).map_err(|c|format!("PACKAGE_REFUSED: {c}"))?; println!("PASS: package hashes and paths"); Ok(())
        },
        _=>Err("Usage: sod2se-devtools doctor <EXE> | settings <offline settings.json> | connect <session.json> [operation] | live-check <session.json> | set <session.json> <mod> <id> <JSON> [--ack-risk] | verify-package <directory>".into()),
    }
}
fn ensure_stopped() -> Result<(), String> {
    #[cfg(windows)]
    {
        use windows_sys::Win32::{Foundation::*, System::Diagnostics::ToolHelp::*};
        let handle = unsafe { CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0) };
        if handle == INVALID_HANDLE_VALUE {
            return Err("Cannot inspect process list".into());
        }
        let mut entry: PROCESSENTRY32W = unsafe { std::mem::zeroed() };
        entry.dwSize = std::mem::size_of::<PROCESSENTRY32W>() as u32;
        let mut present = unsafe { Process32FirstW(handle, &mut entry) } != 0;
        let mut running = false;
        while present {
            let n = entry
                .szExeFile
                .iter()
                .position(|&c| c == 0)
                .unwrap_or(entry.szExeFile.len());
            let name = String::from_utf16_lossy(&entry.szExeFile[..n]).to_lowercase();
            running |= [
                "stateofdecay2.exe",
                "stateofdecay2-win64-shipping.exe",
                "sod2se.loader.exe",
            ]
            .contains(&name.as_str());
            present = unsafe { Process32NextW(handle, &mut entry) } != 0;
        }
        unsafe {
            CloseHandle(handle);
        }
        if running {
            return Err("Exit the game and loader before installation/update/uninstall".into());
        }
    }
    Ok(())
}
fn main() {
    if let Err(e) = run() {
        eprintln!("{e}");
        std::process::exit(1);
    }
}
