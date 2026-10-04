use sod2se_abi::{INTERNAL, INVALID};
use std::{
    path::{Path, PathBuf},
    process::Command,
};
#[cfg(windows)]
mod windows;

#[derive(Default, Debug)]
struct Options {
    exe: Option<PathBuf>,
    arguments: String,
    mo2: bool,
    diagnose: bool,
    profile: String,
}
fn parse(args: impl IntoIterator<Item = String>) -> Result<Options, String> {
    let mut result = Options {
        profile: "default".into(),
        arguments: std::env::var("SOD2_GAME_ARGS").unwrap_or_default(),
        ..Options::default()
    };
    let mut args = args.into_iter();
    while let Some(argument) = args.next() {
        match argument.as_str() {
            "--game-exe" => {
                result.exe = Some(args.next().ok_or("--game-exe requires a path")?.into())
            }
            "--profile-id" => result.profile = args.next().ok_or("--profile-id requires an id")?,
            "--mo2" => result.mo2 = true,
            "--direct-main" | "--console" => {}
            "--diagnose-launch" => result.diagnose = true,
            _ if argument.starts_with("--game-args=") => result.arguments = argument[12..].into(),
            _ => return Err(format!("Unsupported argument: {argument}")),
        }
    }
    if !sod2se_services::valid_id(&result.profile) {
        return Err("Invalid profile id".into());
    }
    if result.mo2 && result.profile == "default" {
        return Err("MO2 mode requires a profile id from the native support integration".into());
    }
    Ok(result)
}
fn resolve(options: &Options) -> Result<PathBuf, i32> {
    let candidate = options.exe.clone().unwrap_or(
        std::env::current_exe()
            .map_err(|_| INTERNAL)?
            .parent()
            .ok_or(INVALID)?
            .into(),
    );
    let exe = if candidate.is_dir() {
        candidate
            .join("StateOfDecay2/Binaries/Win64")
            .join(sod2se_game_api::SHIPPING)
    } else {
        candidate
    };
    sod2se_game_api::verify_image(&exe)?;
    exe.canonicalize().map_err(|_| INTERNAL)
}
fn run() -> Result<(), String> {
    if std::env::args().nth(1).as_deref() == Some("--inert-host-child") {
        std::thread::sleep(std::time::Duration::from_secs(20));
        return Ok(());
    }
    if std::env::args().any(|a| a == "--self-test") {
        assert!(parse(vec!["--attach".into()]).is_err());
        assert!(
            sod2se_game_api::verify_image(&std::env::current_exe().map_err(|e| e.to_string())?)
                .is_err()
        );
        println!(
            "PASS: native loader refuses foreign images and unsupported arguments; no game launched"
        );
        #[cfg(windows)]
        windows::injection_self_test()?;
        return Ok(());
    }
    let options = parse(std::env::args().skip(1))?;
    let exe = resolve(&options).map_err(|e| {
        format!(
            "GAME_REFUSED: {e}; required build {}",
            sod2se_game_api::GAME_BUILD
        )
    })?;
    if options.diagnose {
        println!(
            "{}",
            serde_json::json!({"game":exe,"build":sod2se_game_api::GAME_BUILD,"mo2":options.mo2,"arguments":options.arguments,"action":"diagnose-only"})
        );
        return Ok(());
    }
    #[cfg(windows)]
    {
        windows::launch(&exe, &options).map_err(|e| format!("LAUNCH_FAILED: {e}"))
    }
    #[cfg(not(windows))]
    {
        Err("Native loader requires Windows x64".into())
    }
}
fn main() {
    if let Err(error) = run() {
        eprintln!("{error}");
        if let Some(local) = std::env::var_os("LOCALAPPDATA") {
            let _ = sod2se_services::diagnostics::Logger::new(
                PathBuf::from(local).join("StateOfDecay2/SoD2SE/Rust/loader.jsonl"),
            )
            .write(3, "loader", "LAUNCH_REFUSED", &error);
        }
        std::process::exit(1);
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn command_line() {
        let options = parse(vec![
            "--mo2".into(),
            "--profile-id".into(),
            "test".into(),
            "--game-exe".into(),
            "C:/game path/game.exe".into(),
            "--game-args=".into(),
        ])
        .unwrap();
        assert!(options.mo2);
        assert_eq!(options.arguments, "");
        assert!(parse(vec!["--game-exe".into()]).is_err());
        assert!(parse(vec!["--mo2".into()]).is_err());
    }
    #[test]
    fn diagnose_foreign_refuses() {
        let options = Options {
            exe: Some(std::env::current_exe().unwrap()),
            diagnose: true,
            ..Default::default()
        };
        assert!(resolve(&options).is_err());
    }
}
