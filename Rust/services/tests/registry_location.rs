//! Authored configuration fixtures only; no real player data is used.
use sod2se_services::settings::Registry;
#[test]
fn location_migration_preserves_source_and_never_overwrites_new_configuration() {
    let root = std::env::temp_dir().join(format!("sod2se-location-{}", std::process::id()));
    std::fs::create_dir(&root).unwrap();
    let old = root.join("old.json");
    let bytes=br#"{"schema":1,"revision":7,"values":{"example":{"enabled":true}},"legacy_imported":true,"module_schemas":{}}"#;
    std::fs::write(&old, bytes).unwrap();
    let new = root.join("Plugins/SoD2SE/Settings/profile/registry.json");
    {
        let mut registry = Registry::open(&new).unwrap();
        assert!(registry.import_document(&old).unwrap());
        assert_eq!(registry.document.revision, 7);
        assert!(!registry.import_document(&old).unwrap());
        assert_eq!(std::fs::read(&old).unwrap(), bytes);
        assert_eq!(
            std::fs::read(old.with_extension("json.before-plugins")).unwrap(),
            bytes
        );
    }
    std::fs::write(&old, b"damaged old data").unwrap();
    let mut registry = Registry::open(&new).unwrap();
    assert!(!registry.import_document(&old).unwrap());
    assert_eq!(registry.document.revision, 7);
    drop(registry);
    std::fs::remove_dir_all(root).unwrap();
}
