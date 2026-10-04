//! Authored DLL-byte fixtures; no game is loaded.
use sod2se_services::{diagnostics::digest, plugin::Manifest};
#[test]
fn plugin_names_and_hashes_remain_guarded() {
    let root = std::env::temp_dir().join(format!("sod2se-plugin-path-{}", std::process::id()));
    std::fs::create_dir(&root).unwrap();
    let file = root.join("Example.dll");
    std::fs::write(&file, b"authored inert fixture").unwrap();
    let mut manifest = Manifest {
        schema: 1,
        abi: 1,
        id: "example".into(),
        version: "fixture".into(),
        file: "Example.dll".into(),
        sha256: digest(&file).unwrap(),
        capabilities: vec![],
        permissions: vec![],
        publish: false,
        framework_revision: "a".repeat(40),
    };
    assert_eq!(
        manifest.verify(&root).unwrap(),
        file.canonicalize().unwrap()
    );
    manifest.file = "../Example.dll".into();
    assert!(manifest.verify(&root).is_err());
    manifest.file = "Example.dll".into();
    std::fs::write(&file, b"modified").unwrap();
    assert!(manifest.verify(&root).is_err());
    std::fs::remove_dir_all(root).unwrap();
}
