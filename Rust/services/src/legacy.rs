//! Explicit, hash-reviewed evacuation of legacy framework files before native installation.
use crate::{
    diagnostics::digest,
    install::{Manifest, bounded_path, deployment_lock},
    settings::atomic_save,
};
use serde::{Deserialize, Serialize};
use sod2se_abi::{BUSY, INTERNAL, INVALID};
use std::{fs, path::Path};

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Review {
    pub schema: u32,
    pub reviewed: bool,
    pub reason: String,
    pub manifest: Manifest,
}
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Transition {
    review: Review,
    backup: String,
}
fn validate(review: &Review) -> Result<(), i32> {
    if review.schema != 1
        || !review.reviewed
        || review.reason.trim().is_empty()
        || review.manifest.files.is_empty()
        || review.manifest.files.iter().any(|v| {
            !["SoD2SE.Loader.exe", "SoD2SE.Core.dll", "SoD2SE.GameApi.dll"]
                .contains(&v.path.as_str())
        })
    {
        return Err(INVALID);
    }
    Ok(())
}
pub fn archive(root: &Path, review: Review) -> Result<(), i32> {
    let root = root.canonicalize().map_err(|_| INTERNAL)?;
    let _lock = deployment_lock(&root)?;
    validate(&review)?;
    review.manifest.verify(&root)?;
    let journal = bounded_path(&root, "SoD2SE/legacy-transition.json")?;
    if journal.exists()
        || bounded_path(&root, "SoD2SE/install.json")?.exists()
        || bounded_path(&root, "SoD2SE/install.pending.json")?.exists()
    {
        return Err(BUSY);
    }
    let backup = format!(
        "SoD2SE/Backups/legacy-{}",
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map_err(|_| INTERNAL)?
            .as_nanos()
    );
    let transition = Transition { review, backup };
    // Durable write before any move: restore handles interruption at every file.
    atomic_save(
        &journal,
        &serde_json::to_vec_pretty(&transition).map_err(|_| INVALID)?,
    )?;
    for entry in &transition.review.manifest.files {
        let source = bounded_path(&root, &entry.path)?;
        let destination = bounded_path(&root, &format!("{}/{}", transition.backup, entry.path))?;
        fs::create_dir_all(destination.parent().ok_or(INVALID)?).map_err(|_| INTERNAL)?;
        if digest(&source)? != entry.sha256 || destination.exists() {
            return Err(INVALID);
        }
        fs::rename(source, &destination).map_err(|_| INTERNAL)?;
        if digest(&destination)? != entry.sha256 {
            return Err(INVALID);
        }
    }
    Ok(())
}
pub fn restore(root: &Path) -> Result<(), i32> {
    let root = root.canonicalize().map_err(|_| INTERNAL)?;
    let _lock = deployment_lock(&root)?;
    if bounded_path(&root, "SoD2SE/install.json")?.exists()
        || bounded_path(&root, "SoD2SE/install.pending.json")?.exists()
    {
        return Err(BUSY);
    }
    let journal = bounded_path(&root, "SoD2SE/legacy-transition.json")?;
    let transition: Transition =
        serde_json::from_slice(&fs::read(&journal).map_err(|_| INTERNAL)?).map_err(|_| INVALID)?;
    validate(&transition.review)?;
    if !transition.backup.starts_with("SoD2SE/Backups/legacy-") {
        return Err(INVALID);
    }
    for entry in &transition.review.manifest.files {
        let target = bounded_path(&root, &entry.path)?;
        let source = bounded_path(&root, &format!("{}/{}", transition.backup, entry.path))?;
        // Either already restored/unmoved, or archived. Ambiguity fails before writes.
        if !target.exists() && !source.exists() {
            return Err(INVALID);
        }
        if target.exists()
            && source.exists()
            && crate::overlay::identity(&fs::File::open(&target).map_err(|_| INTERNAL)?)?
                != crate::overlay::identity(&fs::File::open(&source).map_err(|_| INTERNAL)?)?
        {
            return Err(INVALID);
        }
        if digest(if target.exists() { &target } else { &source })? != entry.sha256 {
            return Err(INVALID);
        }
    }
    for entry in &transition.review.manifest.files {
        let source = bounded_path(&root, &format!("{}/{}", transition.backup, entry.path))?;
        if source.exists() {
            if digest(&source)? != entry.sha256 {
                return Err(INVALID);
            }
            let target = bounded_path(&root, &entry.path)?;
            // Link publication is exclusive; never overwrite a late foreign target.
            if !target.exists() {
                fs::hard_link(&source, &target).map_err(|_| INVALID)?;
            }
            fs::remove_file(source).map_err(|_| INTERNAL)?;
        }
    }
    fs::rename(
        &journal,
        bounded_path(&root, &format!("{}/restored.json", transition.backup))?,
    )
    .map_err(|_| INTERNAL)?;
    Ok(())
}
