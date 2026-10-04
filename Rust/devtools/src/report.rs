use serde_json::{Value, json};
use std::{fs::OpenOptions, io::Write, path::Path};

/// Query an explicitly selected session. Export only diagnostic metadata.
pub fn export(session: &Path, destination: &Path) -> Result<(), String> {
    let mut checks = Vec::new();
    for operation in [
        "capabilities",
        "plugins.snapshot",
        "settings.snapshot",
        "ui.extensions",
    ] {
        let result = sod2se_services::transport::connect(session, operation, json!({}));
        checks.push(match result {
            Ok(value) => {
                json!({"operation":operation,"status":"PASS","summary":summary(operation, &value)})
            }
            Err(code) => json!({"operation":operation,"status":"FAIL","code":code}),
        });
    }
    let failed = checks.iter().any(|v| v["status"] == "FAIL");
    let report = json!({"schema":1,"framework_version":env!("CARGO_PKG_VERSION"),
        "kind":"live-diagnostics","checks":checks,"live_acceptance":"NOT_RUN",
        "limitations":["Connectivity does not certify gameplay, saves, uninstall or input devices."]});
    let bytes = serde_json::to_vec_pretty(&report).map_err(|e| e.to_string())?;
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(destination)
        .map_err(|e| format!("REPORT_CREATE_REFUSED: {e}"))?;
    file.write_all(&bytes)
        .and_then(|_| file.write_all(b"\n"))
        .and_then(|_| file.sync_all())
        .map_err(|e| format!("REPORT_WRITE_FAILED: {e}"))?;
    if failed {
        Err("LIVE_DIAGNOSTICS_FAILED: report records failed queries".into())
    } else {
        Ok(())
    }
}

fn summary(operation: &str, value: &Value) -> Value {
    match operation {
        "capabilities" => json!({"game_build":value["game_build"].as_u64(),
            "followers":value["followers"].as_bool(),"native_settings":value["native_settings"].as_bool()}),
        "settings.snapshot" => json!({"revision":value["revision"].as_u64(),
            "registered_modules":value["definitions"].as_object().map(|v|v.len())}),
        _ => json!({"count":value.as_array().map(|v|v.len())}),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn reports_exclude_session_secrets_configuration_and_unapproved_fields() {
        let input = json!({"nonce":"secret","values":{"personal":"private"},
            "path":"protected","revision":4,"definitions":{"example":[]},
            "game_build":16535856,"followers":true,"native_settings":false});
        for operation in [
            "capabilities",
            "settings.snapshot",
            "plugins.snapshot",
            "ui.extensions",
        ] {
            let output = summary(operation, &input).to_string();
            for excluded in ["secret", "private", "protected", "nonce", "values", "path"] {
                assert!(!output.contains(excluded));
            }
        }
    }
}
