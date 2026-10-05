use serde_json::json;
use sod2se_services::{
    install::*, native_settings::*, settings::Registry, translation::Catalog, ui::*,
};
use std::{fs, path::PathBuf};
struct Directory(PathBuf);
static NONCE: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
impl Directory {
    fn new() -> Self {
        let p = std::env::temp_dir().join(format!(
            "sod2se-lifecycle-{}-{}-{}",
            std::process::id(),
            NONCE.fetch_add(1, std::sync::atomic::Ordering::Relaxed),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        fs::create_dir(&p).unwrap();
        Self(p)
    }
}
impl Drop for Directory {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}
fn package(root: &std::path::Path, bytes: &[u8]) {
    fs::create_dir_all(root).unwrap();
    fs::write(root.join("SoD2SE.Loader.exe"), bytes).unwrap();
    let manifest = Manifest {
        schema: 1,
        version: "fixture".into(),
        files: vec![FileEntry {
            path: "SoD2SE.Loader.exe".into(),
            sha256: sod2se_services::diagnostics::digest(&root.join("SoD2SE.Loader.exe")).unwrap(),
        }],
    };
    fs::write(
        root.join("framework.manifest.json"),
        serde_json::to_vec(&manifest).unwrap(),
    )
    .unwrap();
}
#[test]
fn owned_install_update_and_uninstall_preserve_other_files() {
    let dir = Directory::new();
    let source = dir.0.join("package");
    let target = dir.0.join("destination");
    fs::create_dir(&target).unwrap();
    fs::write(target.join("unrelated.txt"), b"preserved").unwrap();
    package(&source, b"authored fixture v1");
    install(&source, &target).unwrap();
    package(&source, b"authored fixture v2");
    install(&source, &target).unwrap();
    assert_eq!(
        fs::read(target.join("SoD2SE.Loader.exe")).unwrap(),
        b"authored fixture v2"
    );
    uninstall(&target).unwrap();
    assert!(!target.join("SoD2SE.Loader.exe").exists());
    assert_eq!(
        fs::read(target.join("unrelated.txt")).unwrap(),
        b"preserved"
    );
}
#[test]
fn foreign_and_modified_installed_payloads_block_before_writes() {
    let dir = Directory::new();
    let source = dir.0.join("package");
    let target = dir.0.join("destination");
    fs::create_dir(&target).unwrap();
    package(&source, b"fixture");
    fs::write(target.join("SoD2SE.Loader.exe"), b"foreign").unwrap();
    assert!(install(&source, &target).is_err());
    assert_eq!(
        fs::read(target.join("SoD2SE.Loader.exe")).unwrap(),
        b"foreign"
    );
    fs::remove_file(target.join("SoD2SE.Loader.exe")).unwrap();
    install(&source, &target).unwrap();
    fs::write(target.join("SoD2SE.Loader.exe"), b"edited").unwrap();
    assert!(uninstall(&target).is_err());
    assert_eq!(
        fs::read(target.join("SoD2SE.Loader.exe")).unwrap(),
        b"edited"
    );
}
#[test]
fn game_original_path_never_admitted() {
    let dir = Directory::new();
    let source = dir.0.join("package");
    let target = dir.0.join("destination");
    fs::create_dir(&target).unwrap();
    package(&source, b"fixture");
    fs::write(source.join("StateOfDecay2.exe"), b"not a game fixture").unwrap();
    let manifest = Manifest {
        schema: 1,
        version: "fixture".into(),
        files: vec![FileEntry {
            path: "StateOfDecay2.exe".into(),
            sha256: sod2se_services::diagnostics::digest(&source.join("StateOfDecay2.exe"))
                .unwrap(),
        }],
    };
    fs::write(
        source.join("framework.manifest.json"),
        serde_json::to_vec(&manifest).unwrap(),
    )
    .unwrap();
    assert!(install(&source, &target).is_err());
    assert!(!target.join("StateOfDecay2.exe").exists());
}
#[test]
fn interrupted_transaction_restores_owned_backup() {
    let dir = Directory::new();
    let source = dir.0.join("package");
    let target = dir.0.join("destination");
    fs::create_dir(&target).unwrap();
    package(&source, b"old fixture");
    install(&source, &target).unwrap();
    let before: Manifest =
        serde_json::from_slice(&fs::read(target.join("SoD2SE/install.json")).unwrap()).unwrap();
    let backup = target.join("SoD2SE/Backups/interrupted");
    for file in &before.files {
        let p = backup.join(&file.path);
        fs::create_dir_all(p.parent().unwrap()).unwrap();
        fs::copy(target.join(&file.path), p).unwrap();
    }
    fs::write(target.join("SoD2SE.Loader.exe"), b"new fixture").unwrap();
    let mut after = before.clone();
    after.files[0].sha256 =
        sod2se_services::diagnostics::digest(&target.join("SoD2SE.Loader.exe")).unwrap();
    fs::write(target.join("SoD2SE/install.pending.json"),json!({"before":before,"after":after,"backup":"SoD2SE/Backups/interrupted","intents":["SoD2SE.Loader.exe"]}).to_string()).unwrap();
    recover(&target).unwrap();
    assert_eq!(
        fs::read(target.join("SoD2SE.Loader.exe")).unwrap(),
        b"old fixture"
    );
    assert!(!target.join("SoD2SE/install.pending.json").exists());
}
#[test]
fn translations_check_placeholders_and_fallback() {
    let mut c = Catalog::new("de-DE".into());
    c.register(1,"example",serde_json::from_value(json!({"en-US":{"example.title":"Value {value}"},"zh-CN":{"example.title":"数值 {value}"}})).unwrap()).unwrap();
    assert_eq!(c.get("example.title"), "Value {value}");
    let mut bad = Catalog::default();
    assert!(bad.register(1,"example",serde_json::from_value(json!({"en-US":{"example.title":"Value {value}"},"zh-CN":{"example.title":"数值 {other}"}})).unwrap()).is_err());
    c.unregister(1);
    assert_eq!(c.get("example.title"), "example.title");
}
#[test]
fn native_snapshot_acknowledgement_and_risk_refusal() {
    let row = OptionRow {
        module: "example".into(),
        id: "rate".into(),
        page: 0,
        label: "Rate".into(),
        description: "Help".into(),
        kind: 1,
        value: 100,
        minimum: 25,
        maximum: 1000,
        restart: false,
        risk: "normal".into(),
        default_value: Some(100),
    };
    let model = Model {
        revision: 1,
        settings_revision: 0,
        language: "en-US".into(),
        pages: vec![Page {
            id: "example".into(),
            name: "Example".into(),
            description: "Help".into(),
            loaded: true,
            version: None,
        }],
        options: vec![row],
        ..Default::default()
    };
    let mut session = Session::default();
    let token = session.open(vec![("example.settings".into(), model.clone())]);
    assert!(matches!(
        session.query(15, token, 0, 200),
        Reply::Edit { .. }
    ));
    assert!(matches!(session.query(18, token, 0, 0), Reply::Number(1)));
    assert_eq!(session.open(vec![]), 0);
    session.complete(token, -1, "refused".into(), 0).unwrap();
    assert!(matches!(session.query(10, token, 0, 0), Reply::Number(100)));
    assert!(matches!(
        session.query(15, token, 0, 200),
        Reply::Edit { revision: 1, .. }
    ));
    let mut updated = model.clone();
    updated.revision = 2;
    updated.settings_revision = 1;
    updated.options[0].value = 200;
    session.refresh(vec![("example.settings".into(), updated.clone())]);
    session.complete(token, 0, "saved".into(), 1).unwrap();
    session.refresh(vec![("example.settings".into(), updated.clone())]);
    // A foreign update must not silently advance the player's snapshot.
    updated.revision = 3;
    updated.options[0].value = 300;
    session.refresh(vec![("example.settings".into(), updated)]);
    assert!(matches!(
        session.query(15, token, 0, 250),
        Reply::Edit { revision: 2, .. }
    ));
    session.complete(token, -1, "refused".into(), 1).unwrap();
    let mut dangerous = model;
    dangerous.options[0].risk = "dangerous".into();
    let token = session.open(vec![("example.settings".into(), dangerous)]);
    assert!(matches!(
        session.query(15, token, 0, 200),
        Reply::Number(-3)
    ));
    assert!(matches!(
        session.query(10, token - 1, 0, 0),
        Reply::Number(-2)
    ));
}
#[test]
fn same_ui_publication_does_not_invalidate_open_actions() {
    let mut ui = UiRegistry::default();
    ui.register(
        1,
        Extension {
            id: "example".into(),
            target: "settings".into(),
            title: "example.title".into(),
            description: "example.help".into(),
        },
    )
    .unwrap();
    ui.publish(
        1,
        "example",
        Model {
            revision: 1,
            ..Default::default()
        },
    )
    .unwrap();
    ui.publish(
        1,
        "example",
        Model {
            revision: 2,
            ..Default::default()
        },
    )
    .unwrap();
    assert_eq!(ui.model("example").unwrap().revision, 1);
    ui.action("example", 1, "close", json!({})).unwrap();
}
#[test]
fn explicit_settings_recovery_retains_corrupt_bytes() {
    let dir = Directory::new();
    let path = dir.0.join("settings.json");
    let good = json!({"schema":1,"revision":0,"values":{},"legacy_imported":false});
    fs::write(path.with_extension("json.last-good"), good.to_string()).unwrap();
    fs::write(&path, b"corrupt").unwrap();
    Registry::recover(&path).unwrap();
    let registry = Registry::open(&path).unwrap();
    assert_eq!(registry.document.schema, 1);
    assert!(
        fs::read_dir(&dir.0)
            .unwrap()
            .filter_map(Result::ok)
            .any(|e| e
                .file_name()
                .to_string_lossy()
                .starts_with("settings.json.corrupt-"))
    );
}
#[test]
fn overlay_never_replaces_foreign_files() {
    let dir = Directory::new();
    let source = dir.0.join("authored-resource");
    let target = dir.0.join("overlay");
    let receipt = dir.0.join("overlay.json");
    fs::write(&source, b"self-authored generic fixture").unwrap();
    let hash = sod2se_services::diagnostics::digest(&source).unwrap();
    fs::write(&target, b"foreign").unwrap();
    assert!(sod2se_services::overlay::prepare(&source, &hash, &target, &receipt).is_err());
    assert_eq!(fs::read(&target).unwrap(), b"foreign");
    fs::remove_file(&target).unwrap();
    sod2se_services::overlay::prepare(&source, &hash, &target, &receipt).unwrap();
    sod2se_services::overlay::recover(&target, &receipt).unwrap();
    assert!(!target.exists());
}
