use serde::{Deserialize, Serialize};
use sod2se_abi::{ABI_VERSION, INTERNAL, INVALID, UNSUPPORTED};
use std::{
    collections::BTreeSet,
    path::{Path, PathBuf},
};
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Manifest {
    pub schema: u32,
    pub abi: u32,
    pub id: String,
    pub version: String,
    pub file: String,
    pub sha256: String,
    pub capabilities: Vec<String>,
    pub permissions: Vec<String>,
    pub publish: bool,
    pub framework_revision: String,
}
impl Manifest {
    pub fn read(path: &Path) -> Result<Self, i32> {
        let m: Self = serde_json::from_slice(&std::fs::read(path).map_err(|_| INTERNAL)?)
            .map_err(|_| INVALID)?;
        m.validate()?;
        Ok(m)
    }
    pub fn validate(&self) -> Result<(), i32> {
        if self.schema != 1 || self.abi != ABI_VERSION {
            return Err(UNSUPPORTED);
        }
        if !super::valid_id(&self.id)
            || self.version.is_empty()
            || self.version.len() > 64
            || !super::install::safe_relative(&self.file)
            || self.file.contains('/')
            || !self.file.to_ascii_lowercase().ends_with(".dll")
            || self.sha256.len() != 64
            || !self.sha256.bytes().all(|b| b.is_ascii_hexdigit())
            || self.framework_revision.len() != 40
            || !self
                .framework_revision
                .bytes()
                .all(|b| b.is_ascii_hexdigit())
        {
            return Err(INVALID);
        }
        if self
            .capabilities
            .iter()
            .any(|c| !["sod2.followers.quantity", "sod2.ui.native-settings"].contains(&c.as_str()))
            || self.permissions.iter().any(|p| p != "settings.frontend")
        {
            return Err(UNSUPPORTED);
        }
        Ok(())
    }
    pub fn verify(&self, parent: &Path) -> Result<PathBuf, i32> {
        self.validate()?;
        let root = parent.canonicalize().map_err(|_| INTERNAL)?;
        // The validated filename is a single safe component. Preserve this
        // virtual namespace: USVFS resolves the file to the MO2 source, while
        // its existing parent directory may remain a physical game directory.
        let file = root.join(&self.file);
        super::overlay::no_links(&file)?;
        if super::diagnostics::digest(&file)? != self.sha256.to_ascii_lowercase() {
            return Err(INVALID);
        }
        Ok(file)
    }
}
pub fn discover(root: &Path) -> Result<Vec<(PathBuf, Manifest)>, i32> {
    if !root.exists() {
        return Ok(Vec::new());
    }
    let mut found = Vec::new();
    let mut dlls = BTreeSet::new();
    let mut declared = BTreeSet::new();
    let mut ids = BTreeSet::new();
    for entry in std::fs::read_dir(root).map_err(|_| INTERNAL)? {
        let entry = entry.map_err(|_| INTERNAL)?;
        let path = entry.path();
        if !path.is_file() {
            continue;
        }
        let name = entry.file_name().to_string_lossy().to_lowercase();
        if name.ends_with(".dll") {
            dlls.insert(name);
        } else if name.ends_with(".native.json") {
            let manifest = Manifest::read(&path)?;
            manifest.verify(root)?;
            if !ids.insert(manifest.id.clone()) || !declared.insert(manifest.file.to_lowercase()) {
                return Err(INVALID);
            }
            found.push((path, manifest));
        }
    }
    if dlls != declared {
        return Err(UNSUPPORTED);
    }
    found.sort_by(|a, b| a.0.cmp(&b.0));
    Ok(found)
}

/// Discover framework-owned builtins together with external plugins.
pub fn discover_all(game_root: &Path) -> Result<Vec<(PathBuf, Manifest)>, i32> {
    let mut found = discover(&game_root.join("SoD2SE/BuiltinPlugins"))?;
    found.extend(discover(&game_root.join("Plugins"))?);
    let mut ids = BTreeSet::new();
    if found
        .iter()
        .any(|(_, manifest)| !ids.insert(manifest.id.clone()))
    {
        return Err(INVALID);
    }
    Ok(found)
}
