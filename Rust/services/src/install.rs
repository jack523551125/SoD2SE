//! Package validation and ownership checks; never overwrite an existing foreign file.
use serde::{Deserialize, Serialize};
use sod2se_abi::{INTERNAL, INVALID};
use std::{
    collections::BTreeSet,
    path::{Component, Path},
};
#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct FileEntry {
    pub path: String,
    pub sha256: String,
}
#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Manifest {
    pub schema: u32,
    pub version: String,
    pub files: Vec<FileEntry>,
}
pub fn safe_relative(path: &str) -> bool {
    !path.is_empty()
        && path.is_ascii()
        && !path.bytes().any(|c| c < 32 || b"\\:<>*?\"|".contains(&c))
        && Path::new(path)
            .components()
            .all(|c| matches!(c, Component::Normal(_)))
        && !path.split('/').any(|p| {
            let name = p.split('.').next().unwrap_or("").to_ascii_lowercase();
            p.is_empty()
                || [".", ".."].contains(&p)
                || p.ends_with(['.', ' '])
                || ["con", "prn", "aux", "nul"].contains(&name.as_str())
                || (name.len() == 4
                    && (name.starts_with("com") || name.starts_with("lpt"))
                    && matches!(name.as_bytes()[3], b'1'..=b'9'))
        })
}
impl Manifest {
    pub fn verify(&self, root: &Path) -> Result<(), i32> {
        if self.schema != 1 || self.files.is_empty() {
            return Err(INVALID);
        }
        let root = root.canonicalize().map_err(|_| INTERNAL)?;
        let mut seen = BTreeSet::new();
        for entry in &self.files {
            if !safe_relative(&entry.path)
                || !seen.insert(entry.path.to_lowercase())
                || entry.sha256.len() != 64
            {
                return Err(INVALID);
            }
            let path = root
                .join(&entry.path)
                .canonicalize()
                .map_err(|_| INTERNAL)?;
            if !path.starts_with(&root)
                || super::diagnostics::digest(&path)? != entry.sha256.to_ascii_lowercase()
            {
                return Err(INVALID);
            }
        }
        Ok(())
    }
}

fn framework_path(path: &str) -> bool {
    safe_relative(path)
        && ([
            "SoD2SE.Loader.exe",
            "SoD2SE.Runtime.dll",
            "SoD2SE.DevTools.exe",
            "framework.manifest.json",
        ]
        .contains(&path)
            || (path.starts_with("SoD2SE/")
                && !path.starts_with("SoD2SE/install.")
                && !path.starts_with("SoD2SE/Backups/")))
}
fn contained(root: &Path, relative: &str) -> Result<std::path::PathBuf, i32> {
    if !framework_path(relative) {
        return Err(INVALID);
    }
    bounded_path(root, relative)
}
fn bounded_path(root: &Path, relative: &str) -> Result<std::path::PathBuf, i32> {
    if !safe_relative(relative) {
        return Err(INVALID);
    }
    let path = root.join(relative);
    let mut component = root.to_path_buf();
    for part in Path::new(relative).components() {
        component.push(part);
        if let Ok(metadata) = std::fs::symlink_metadata(&component) {
            #[cfg(windows)]
            {
                use std::os::windows::fs::MetadataExt;
                if metadata.file_attributes() & 0x400 != 0 {
                    return Err(INVALID);
                }
            }
            if metadata.file_type().is_symlink() {
                return Err(INVALID);
            }
        }
    }
    let mut ancestor = path.as_path();
    while !ancestor.exists() {
        ancestor = ancestor.parent().ok_or(INVALID)?;
    }
    if !ancestor
        .canonicalize()
        .map_err(|_| INTERNAL)?
        .starts_with(root)
    {
        return Err(INVALID);
    }
    Ok(path)
}
fn installed(root: &Path) -> Result<Option<Manifest>, i32> {
    let receipt = bounded_path(root, "SoD2SE/install.json")?;
    if !receipt.exists() {
        return Ok(None);
    }
    let manifest: Manifest = serde_json::from_slice(&std::fs::read(receipt).map_err(|_| INTERNAL)?)
        .map_err(|_| INVALID)?;
    manifest.verify(root)?;
    if manifest.files.iter().any(|e| !framework_path(&e.path)) {
        return Err(INVALID);
    }
    Ok(Some(manifest))
}
#[derive(Serialize, Deserialize)]
struct Journal {
    before: Option<Manifest>,
    after: Manifest,
    backup: String,
    intents: Vec<String>,
}
/// Copies only declared framework-owned paths. Existing foreign files always block installation.
pub fn install(package: &Path, destination: &Path) -> Result<(), i32> {
    let package = package.canonicalize().map_err(|_| INTERNAL)?;
    let root = destination.canonicalize().map_err(|_| INTERNAL)?;
    let mut after: Manifest = serde_json::from_slice(
        &std::fs::read(package.join("framework.manifest.json")).map_err(|_| INTERNAL)?,
    )
    .map_err(|_| INVALID)?;
    after.verify(&package)?;
    after.files.push(FileEntry {
        path: "framework.manifest.json".into(),
        sha256: super::diagnostics::digest(&package.join("framework.manifest.json"))?,
    });
    let before = installed(&root)?;
    let pending = bounded_path(&root, "SoD2SE/install.pending.json")?;
    if pending.exists() {
        return Err(sod2se_abi::BUSY);
    }
    for file in &after.files {
        let target = contained(&root, &file.path)?;
        if target.exists()
            && !before
                .as_ref()
                .is_some_and(|b| b.files.iter().any(|e| e.path == file.path))
        {
            return Err(INVALID);
        }
    }
    // Removed payloads require an explicit uninstall before switching this package layout.
    if before.as_ref().is_some_and(|b| {
        b.files
            .iter()
            .any(|f| !after.files.iter().any(|e| e.path == f.path))
    }) {
        return Err(INVALID);
    }
    let backup = format!(
        "SoD2SE/Backups/{}",
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map_err(|_| INTERNAL)?
            .as_nanos()
    );
    if let Some(before) = &before {
        for file in &before.files {
            let path = bounded_path(&root, &format!("{backup}/{}", file.path))?;
            std::fs::create_dir_all(path.parent().ok_or(INVALID)?).map_err(|_| INTERNAL)?;
            std::fs::copy(root.join(&file.path), &path).map_err(|_| INTERNAL)?;
            if super::diagnostics::digest(&path)? != file.sha256 {
                return Err(INVALID);
            }
        }
    }
    let mut journal = Journal {
        before,
        after: after.clone(),
        backup,
        intents: Vec::new(),
    };
    super::settings::atomic_save(
        &pending,
        &serde_json::to_vec(&journal).map_err(|_| INTERNAL)?,
    )?;
    for file in &after.files {
        let target = contained(&root, &file.path)?;
        let bytes = std::fs::read(package.join(&file.path)).map_err(|_| INTERNAL)?;
        // Verify source again, closing the gap between preflight and copy.
        use sha2::{Digest, Sha256};
        if format!("{:x}", Sha256::digest(&bytes)) != file.sha256 {
            return Err(INVALID);
        }
        journal.intents.push(file.path.clone());
        super::settings::atomic_save(
            &pending,
            &serde_json::to_vec(&journal).map_err(|_| INTERNAL)?,
        )?;
        super::settings::atomic_save(&target, &bytes)?;
    }
    super::settings::atomic_save(
        &bounded_path(&root, "SoD2SE/install.json")?,
        &serde_json::to_vec_pretty(&after).map_err(|_| INTERNAL)?,
    )?;
    std::fs::remove_file(pending).map_err(|_| INTERNAL)?;
    Ok(())
}
/// Explicit interrupted-install recovery. Rechecks every intended path before changing any file.
pub fn recover(destination: &Path) -> Result<(), i32> {
    let root = destination.canonicalize().map_err(|_| INTERNAL)?;
    let pending = bounded_path(&root, "SoD2SE/install.pending.json")?;
    let journal: Journal = serde_json::from_slice(&std::fs::read(&pending).map_err(|_| INTERNAL)?)
        .map_err(|_| INVALID)?;
    if !safe_relative(&journal.backup) || !journal.backup.starts_with("SoD2SE/Backups/") {
        return Err(INVALID);
    }
    for relative in &journal.intents {
        let target = contained(&root, relative)?;
        let new = journal
            .after
            .files
            .iter()
            .find(|f| &f.path == relative)
            .ok_or(INVALID)?;
        let old = journal
            .before
            .as_ref()
            .and_then(|b| b.files.iter().find(|f| &f.path == relative));
        if target.exists() {
            let hash = super::diagnostics::digest(&target)?;
            if hash != new.sha256 && !old.is_some_and(|e| e.sha256 == hash) {
                return Err(INVALID);
            }
        }
        if let Some(old) = old {
            let backup = bounded_path(&root, &format!("{}/{}", journal.backup, relative))?;
            if super::diagnostics::digest(&backup)? != old.sha256 {
                return Err(INVALID);
            }
        }
    }
    for relative in journal.intents.iter().rev() {
        let target = contained(&root, relative)?;
        let old = journal
            .before
            .as_ref()
            .and_then(|b| b.files.iter().find(|f| &f.path == relative));
        if let Some(old) = old {
            let bytes = std::fs::read(bounded_path(
                &root,
                &format!("{}/{}", journal.backup, old.path),
            )?)
            .map_err(|_| INTERNAL)?;
            super::settings::atomic_save(&target, &bytes)?;
        } else if target.exists() {
            std::fs::remove_file(target).map_err(|_| INTERNAL)?;
        }
    }
    if let Some(before) = journal.before {
        super::settings::atomic_save(
            &bounded_path(&root, "SoD2SE/install.json")?,
            &serde_json::to_vec_pretty(&before).map_err(|_| INTERNAL)?,
        )?;
    } else {
        let receipt = bounded_path(&root, "SoD2SE/install.json")?;
        if receipt.exists() {
            std::fs::remove_file(receipt).map_err(|_| INTERNAL)?;
        }
    }
    std::fs::remove_file(pending).map_err(|_| INTERNAL)?;
    Ok(())
}
pub fn uninstall(destination: &Path) -> Result<(), i32> {
    let root = destination.canonicalize().map_err(|_| INTERNAL)?;
    let pending = bounded_path(&root, "SoD2SE/install.pending.json")?;
    if pending.exists() {
        return Err(sod2se_abi::BUSY);
    }
    let receipt = installed(&root)?.ok_or(INVALID)?;
    for file in &receipt.files {
        contained(&root, &file.path)?;
    }
    let backup = format!(
        "SoD2SE/Backups/uninstall-{}",
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map_err(|_| INTERNAL)?
            .as_nanos()
    );
    for file in &receipt.files {
        let path = bounded_path(&root, &format!("{backup}/{}", file.path))?;
        std::fs::create_dir_all(path.parent().ok_or(INVALID)?).map_err(|_| INTERNAL)?;
        std::fs::copy(root.join(&file.path), &path).map_err(|_| INTERNAL)?;
        if super::diagnostics::digest(&path)? != file.sha256 {
            return Err(INVALID);
        }
    }
    let journal = Journal {
        before: Some(receipt.clone()),
        after: receipt.clone(),
        backup,
        intents: receipt.files.iter().map(|f| f.path.clone()).collect(),
    };
    super::settings::atomic_save(
        &pending,
        &serde_json::to_vec(&journal).map_err(|_| INTERNAL)?,
    )?;
    for file in &receipt.files {
        let path = contained(&root, &file.path)?;
        if super::diagnostics::digest(&path)? != file.sha256 {
            return Err(INVALID);
        }
        std::fs::remove_file(path).map_err(|_| INTERNAL)?;
    }
    std::fs::remove_file(bounded_path(&root, "SoD2SE/install.json")?).map_err(|_| INTERNAL)?;
    std::fs::remove_file(pending).map_err(|_| INTERNAL)?;
    Ok(())
}
