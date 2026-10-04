use serde_json::json;
use sod2se_abi::{BUSY, INVALID, STALE, UNSUPPORTED};
use sod2se_services::{install::*, settings::*, ui::*};
use std::{fs, path::PathBuf};
struct Directory(PathBuf);
static NONCE: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
impl Directory {
    fn new() -> Self {
        let path = std::env::temp_dir().join(format!(
            "sod2se-contract-{}-{}-{}",
            std::process::id(),
            NONCE.fetch_add(1, std::sync::atomic::Ordering::Relaxed),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        fs::create_dir(&path).unwrap();
        Self(path)
    }
}
impl Drop for Directory {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}
fn definition() -> Definition {
    Definition {
        id: "rate".into(),
        kind: "integer".into(),
        default: json!(100),
        minimum: Some(25),
        maximum: Some(1000),
        label: "example.rate".into(),
        description: "example.rate.help".into(),
        apply: "immediate".into(),
        risk: "normal".into(),
    }
}
#[test]
fn registry_survives_restart_without_mcm() {
    let dir = Directory::new();
    let path = dir.0.join("settings.json");
    {
        let mut r = Registry::open(&path).unwrap();
        r.register(1, "example", vec![definition()]).unwrap();
        assert_eq!(r.get("example", "rate").unwrap(), json!(100));
        r.set(0, "example", "rate", json!(250), false).unwrap();
        assert_eq!(r.changes(0).unwrap().len(), 1);
        r.unregister(1);
        assert!(r.get("example", "rate").is_err());
    }
    let mut r = Registry::open(&path).unwrap();
    r.register(2, "example", vec![definition()]).unwrap();
    assert_eq!(r.get("example", "rate").unwrap(), json!(250));
    assert_eq!(r.changes(0), Err(STALE));
}
#[test]
fn invalid_and_stale_changes_are_atomic() {
    let dir = Directory::new();
    let path = dir.0.join("settings.json");
    let mut r = Registry::open(&path).unwrap();
    r.register(1, "example", vec![definition()]).unwrap();
    assert_eq!(
        r.set(0, "example", "rate", json!(1001), false),
        Err(INVALID)
    );
    assert!(!path.exists());
    r.set(0, "example", "rate", json!(250), false).unwrap();
    let bytes = fs::read(&path).unwrap();
    assert_eq!(r.set(0, "example", "rate", json!(300), false), Err(STALE));
    assert_eq!(fs::read(&path).unwrap(), bytes);
    fs::remove_file(&path).unwrap();
    fs::create_dir(&path).unwrap();
    assert!(r.set(1, "example", "rate", json!(500), false).is_err());
    assert_eq!(r.get("example", "rate").unwrap(), json!(250));
    assert_eq!(r.document.revision, 1);
}
#[test]
fn future_and_corrupt_documents_are_preserved() {
    let dir = Directory::new();
    let path = dir.0.join("settings.json");
    for bytes in [
        b"{\"schema\":99,\"revision\":0,\"values\":{},\"legacy_imported\":false}".as_slice(),
        b"broken".as_slice(),
    ] {
        fs::write(&path, bytes).unwrap();
        assert!(Registry::open(&path).is_err());
        assert_eq!(fs::read(&path).unwrap(), bytes);
    }
}
#[cfg(windows)]
#[test]
fn two_writers_refused() {
    let dir = Directory::new();
    let path = dir.0.join("settings.json");
    let _first = Registry::open(&path).unwrap();
    assert!(matches!(Registry::open(&path), Err(BUSY)));
}
#[test]
fn dangerous_values_need_acknowledgement() {
    let dir = Directory::new();
    let mut r = Registry::open(dir.0.join("settings.json")).unwrap();
    let mut d = definition();
    d.risk = "dangerous".into();
    r.register(1, "example", vec![d]).unwrap();
    assert_eq!(r.set(0, "example", "rate", json!(250), false), Err(INVALID));
    r.set(0, "example", "rate", json!(250), true).unwrap();
}
#[test]
fn actual_flat_legacy_format_imported_once() {
    let dir = Directory::new();
    let path = dir.0.join("settings.json");
    let old = dir.0.join("mcm.ini");
    let bytes = b"# SoD2SE MCM settings; generated file.\nexample.rate=250\nmcm.shortcut-key=112\n";
    fs::write(&old, bytes).unwrap();
    let mut r = Registry::open(&path).unwrap();
    r.register(1, "example", vec![definition()]).unwrap();
    assert!(r.import_legacy(&old).unwrap());
    assert_eq!(r.get("example", "rate").unwrap(), json!(250));
    assert!(!r.import_legacy(&old).unwrap());
    assert_eq!(fs::read(&old).unwrap(), bytes);
    assert_eq!(
        fs::read(old.with_extension("ini.pre-rust-backup")).unwrap(),
        bytes
    );
}
#[test]
fn invalid_import_preserves_source_and_registry() {
    let dir = Directory::new();
    let old = dir.0.join("mcm.ini");
    fs::write(&old, b"example.rate=1001").unwrap();
    let mut r = Registry::open(dir.0.join("settings.json")).unwrap();
    r.register(1, "example", vec![definition()]).unwrap();
    assert_eq!(r.import_legacy(&old), Err(INVALID));
    assert!(!r.document.legacy_imported);
    assert!(!old.with_extension("ini.pre-rust-backup").exists());
}
#[test]
fn ui_targets_and_stale_actions() {
    let mut ui = UiRegistry::default();
    let mut extension = Extension {
        id: "example".into(),
        target: "character".into(),
        title: "example.title".into(),
        description: "example.help".into(),
    };
    assert_eq!(ui.register(1, extension.clone()), Err(UNSUPPORTED));
    extension.target = "settings".into();
    ui.register(1, extension).unwrap();
    ui.publish(
        1,
        "example",
        Model {
            revision: 1,
            ..Default::default()
        },
    )
    .unwrap();
    assert_eq!(ui.action("example", 0, "confirm", json!({})), Err(STALE));
    ui.action("example", 1, "back", json!({})).unwrap();
    assert_eq!(ui.drain(1, "example").unwrap().len(), 1);
    assert!(ui.drain(2, "example").is_err());
    ui.unregister(1);
    assert!(ui.extensions().is_empty());
}
#[test]
fn package_traversal_and_modified_payload_refused() {
    let dir = Directory::new();
    fs::write(dir.0.join("payload"), b"original").unwrap();
    let m = Manifest {
        schema: 1,
        version: "test".into(),
        files: vec![FileEntry {
            path: "payload".into(),
            sha256: sod2se_services::diagnostics::digest(&dir.0.join("payload")).unwrap(),
        }],
    };
    m.verify(&dir.0).unwrap();
    fs::write(dir.0.join("payload"), b"edited").unwrap();
    assert!(m.verify(&dir.0).is_err());
    for path in [
        "../game.exe",
        "/root",
        "C:/game",
        "a\\b",
        "a/../b",
        "con",
        "a.",
    ] {
        assert!(!safe_relative(path), "{path}");
    }
}
