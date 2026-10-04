use serde_json::json;
use sod2se_abi::*;
use sod2se_runtime::Services;
#[test]
fn inert_host_registry_and_missing_game_capabilities() {
    let path = std::env::temp_dir().join(format!("sod2se-host-{}", std::process::id()));
    std::fs::create_dir_all(&path).unwrap();
    {
        let mut host = Services::open(path.clone(), false).unwrap();
        host.owners.insert(1, "example".into());
        host.owners.insert(2, "other".into());
        assert_eq!(
            host.request(1, "game.followers.acquire", json!({})),
            Err(UNSUPPORTED)
        );
        host.request(1,"settings.register",json!({"definitions":[{"id":"enabled","kind":"boolean","default":false,"minimum":null,"maximum":null,"label":"example.enabled","description":"example.help","apply":"immediate","risk":"normal"}]})).unwrap();
        assert!(
            host.request(1, "settings.snapshot", json!({})).unwrap()["definitions"]["example"]
                .is_object()
        );
        assert_eq!(
            host.request(
                2,
                "settings.set",
                json!({"module":"example","id":"enabled","value":true,"revision":0})
            ),
            Err(INVALID)
        );
        host.frontends.insert(2);
        host.request(
            2,
            "settings.set",
            json!({"module":"example","id":"enabled","value":true,"revision":0}),
        )
        .unwrap();
        host.cleanup(1).unwrap();
        assert_eq!(
            host.request(1, "settings.snapshot", json!({})),
            Err(INVALID)
        );
    }
    std::fs::remove_dir_all(path).unwrap();
}
