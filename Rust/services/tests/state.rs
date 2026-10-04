use serde_json::json;
use sod2se_abi::{STALE, UNSUPPORTED};
use sod2se_services::state::Store;
#[test]
fn state_is_separate_versioned_and_preserves_future_or_damaged_data() {
    let root = std::env::temp_dir().join(format!(
        "sod2se-state-{}-{}",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    ));
    {
        let store = Store::open(&root).unwrap();
        assert!(store.read("../foreign", 1).is_err());
        assert_eq!(store.read("example", 1).unwrap().revision, 0);
        store.write("example", 1, 0, json!({"counter":1})).unwrap();
        assert_eq!(store.write("example", 1, 0, json!({})), Err(STALE));
        store.write("example", 2, 1, json!({"counter":2})).unwrap();
        assert!(matches!(store.read("example", 1), Err(UNSUPPORTED)));
        assert_eq!(store.write("example", 1, 2, json!({})), Err(UNSUPPORTED));
        assert!(root.join("example/last-good.json").exists());
        std::fs::write(root.join("example/state.json"), b"damaged input").unwrap();
        assert!(store.write("example", 2, 2, json!({})).is_err());
        assert_eq!(
            std::fs::read(root.join("example/state.json")).unwrap(),
            b"damaged input"
        );
    }
    std::fs::remove_dir_all(root).unwrap();
}
