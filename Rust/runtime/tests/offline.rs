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
            host.request(1, "state.read", json!({"scope":"save","schema":1})),
            Err(UNSUPPORTED)
        );
        host.request(
            1,
            "state.write",
            json!({"scope":"profile","schema":1,"revision":0,"value":{"counter":1}}),
        )
        .unwrap();
        assert_eq!(
            host.request(2, "state.read", json!({"scope":"profile","schema":1}))
                .unwrap()["value"],
            serde_json::Value::Null
        );
        assert_eq!(
            host.request(1, "state.read", json!({"scope":"profile","schema":1}))
                .unwrap()["value"]["counter"],
            1
        );
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
        host.request(1,"ui.register",json!({"id":"example.settings","target":"settings","title":"example.title","description":"example.help"})).unwrap();
        host.request(1,"ui.publish",json!({"id":"example.settings","model":{"revision":1,"settings_revision":1,"language":"en-US","pages":[{"id":"example","name":"Example","description":"Help","loaded":true}],"options":[{"module":"example","id":"enabled","page":0,"label":"Enabled","description":"Help","kind":0,"value":1,"minimum":0,"maximum":1,"restart":false,"risk":"normal"}]}})).unwrap();
        let token = host.native_session.open(host.ui.models());
        assert!(matches!(
            host.native_session.query(15, token, 0, 0),
            sod2se_services::native_settings::Reply::Edit { .. }
        ));
        assert_eq!(
            host.request(
                2,
                "ui.complete",
                json!({"token":token,"status":0,"message":"foreign"})
            ),
            Err(INVALID)
        );
        host.request(1,"ui.complete",json!({"token":token,"status":0,"message":"owned UI without MCM or frontend permission"})).unwrap();
        host.cleanup(1).unwrap();
        assert_eq!(
            host.request(1, "settings.snapshot", json!({})),
            Err(INVALID)
        );
    }
    std::fs::remove_dir_all(path).unwrap();
}
