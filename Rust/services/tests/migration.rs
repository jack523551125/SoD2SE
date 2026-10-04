use serde_json::json;
use sod2se_abi::STALE;
use sod2se_services::settings::*;
#[test]
fn module_migration_is_atomic_and_downgrades_refused() {
    let directory = std::env::temp_dir().join(format!(
        "sod2se-schema-{}-{}",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    ));
    std::fs::create_dir(&directory).unwrap();
    let path = directory.join("settings.json");
    {
        let mut r = Registry::open(&path).unwrap();
        let mut d = Definition {
            id: "old".into(),
            kind: "integer".into(),
            default: json!(100),
            minimum: Some(25),
            maximum: Some(1000),
            label: "example.rate".into(),
            description: "example.help".into(),
            apply: "immediate".into(),
            risk: "normal".into(),
        };
        r.register(1, "example", vec![d.clone()]).unwrap();
        r.set(0, "example", "old", json!(250), false).unwrap();
        r.unregister(1);
        d.id = "new".into();
        d.risk = "dangerous".into();
        r.register_schema(2, "example", 2, vec![d.clone()]).unwrap();
        assert_eq!(r.get("example", "new"), Err(STALE));
        let before = std::fs::read(&path).unwrap();
        assert!(
            r.migrate(
                2,
                "example",
                1,
                1,
                2,
                serde_json::from_value(json!({"new":1001})).unwrap()
            )
            .is_err()
        );
        assert_eq!(std::fs::read(&path).unwrap(), before);
        assert!(
            r.migrate(
                2,
                "example",
                1,
                1,
                2,
                serde_json::from_value(json!({"new":250})).unwrap()
            )
            .is_err()
        );
        assert_eq!(std::fs::read(&path).unwrap(), before);
        r.migrate(
            2,
            "example",
            1,
            1,
            2,
            serde_json::from_value(json!({"new":100})).unwrap(),
        )
        .unwrap();
        assert_eq!(r.get("example", "new").unwrap(), json!(100));
        assert!(r.set(2, "example", "new", json!(250), false).is_err());
        r.set(2, "example", "new", json!(250), true).unwrap();
        r.unregister(2);
        assert_eq!(r.register_schema(3, "example", 1, vec![d]), Err(STALE));
    }
    std::fs::remove_dir_all(directory).unwrap();
}
