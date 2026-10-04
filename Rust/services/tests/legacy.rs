use sod2se_services::{
    diagnostics::digest,
    install::{FileEntry, Manifest},
    legacy::{self, Review},
};
use std::{fs, path::PathBuf};
struct Directory(PathBuf);
static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
impl Directory {
    fn new() -> Self {
        let path = std::env::temp_dir().join(format!(
            "sod2se-legacy-{}-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, std::sync::atomic::Ordering::Relaxed),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        fs::create_dir(&path).unwrap();
        Self(path)
    }
    fn review(&self, name: &str) -> Review {
        Review {
            schema: 1,
            reviewed: true,
            reason: "Authored offline fixture; not a game input".into(),
            manifest: Manifest {
                schema: 1,
                version: "legacy-fixture".into(),
                files: vec![FileEntry {
                    path: name.into(),
                    sha256: digest(&self.0.join(name)).unwrap(),
                }],
            },
        }
    }
}
impl Drop for Directory {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}
#[test]
fn legacy_archive_restore_and_foreign_conflicts() {
    let d = Directory::new();
    let loader = d.0.join("SoD2SE.Loader.exe");
    fs::write(&loader, b"legacy fixture").unwrap();
    legacy::archive(&d.0, d.review("SoD2SE.Loader.exe")).unwrap();
    assert!(!loader.exists());
    fs::write(&loader, b"foreign replacement").unwrap();
    assert!(legacy::restore(&d.0).is_err());
    assert_eq!(fs::read(&loader).unwrap(), b"foreign replacement");
    fs::remove_file(&loader).unwrap();
    legacy::restore(&d.0).unwrap();
    assert_eq!(fs::read(loader).unwrap(), b"legacy fixture");
}
#[test]
fn archive_rejects_originals_and_unreviewed_inventory() {
    let d = Directory::new();
    fs::write(d.0.join("StateOfDecay2.exe"), b"authored path fixture").unwrap();
    assert!(legacy::archive(&d.0, d.review("StateOfDecay2.exe")).is_err());
    fs::write(d.0.join("SoD2SE.Loader.exe"), b"legacy fixture").unwrap();
    let mut review = d.review("SoD2SE.Loader.exe");
    review.reviewed = false;
    assert!(legacy::archive(&d.0, review).is_err());
    assert!(d.0.join("SoD2SE.Loader.exe").exists());
}
#[test]
fn interrupted_restore_recognizes_only_same_file_identity() {
    let d = Directory::new();
    let name = "SoD2SE.Loader.exe";
    fs::write(d.0.join(name), b"legacy fixture").unwrap();
    legacy::archive(&d.0, d.review(name)).unwrap();
    let journal: serde_json::Value =
        serde_json::from_slice(&fs::read(d.0.join("SoD2SE/legacy-transition.json")).unwrap())
            .unwrap();
    let backup = d.0.join(journal["backup"].as_str().unwrap()).join(name);
    fs::copy(&backup, d.0.join(name)).unwrap();
    assert!(legacy::restore(&d.0).is_err());
    fs::remove_file(d.0.join(name)).unwrap();
    fs::hard_link(&backup, d.0.join(name)).unwrap();
    legacy::restore(&d.0).unwrap();
    assert!(!backup.exists());
}
