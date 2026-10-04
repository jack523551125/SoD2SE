//! Profile-scoped persistent Mod state; separate from Settings Registry.
use crate::{install::bounded_path, settings::atomic_save};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use sod2se_abi::{INTERNAL, INVALID, STALE, UNSUPPORTED};
use std::{
    fs,
    path::{Path, PathBuf},
};
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Document {
    pub format: u32,
    pub schema: u32,
    pub revision: u64,
    pub value: Value,
}
pub struct Store {
    root: PathBuf,
    _lock: fs::File,
}
impl Store {
    pub fn open(root: &Path) -> Result<Self, i32> {
        fs::create_dir_all(root).map_err(|_| INTERNAL)?;
        let root = root.canonicalize().map_err(|_| INTERNAL)?;
        let mut options = fs::OpenOptions::new();
        options.read(true).write(true).create(true).truncate(false);
        #[cfg(windows)]
        {
            use std::os::windows::fs::OpenOptionsExt;
            options.share_mode(0);
        }
        let lock = options
            .open(bounded_path(&root, "state.lock")?)
            .map_err(|_| sod2se_abi::BUSY)?;
        Ok(Self { root, _lock: lock })
    }
    fn path(&self, module: &str) -> Result<PathBuf, i32> {
        if !crate::valid_id(module) {
            return Err(INVALID);
        }
        bounded_path(&self.root, &format!("{module}/state.json"))
    }
    pub fn read(&self, module: &str, schema: u32) -> Result<Document, i32> {
        if schema == 0 {
            return Err(INVALID);
        }
        let path = self.path(module)?;
        if !path.exists() {
            return Ok(Document {
                format: 1,
                schema,
                revision: 0,
                value: Value::Null,
            });
        }
        let bytes = fs::read(path).map_err(|_| INTERNAL)?;
        if bytes.len() > 1024 * 1024 {
            return Err(INVALID);
        }
        let document: Document = serde_json::from_slice(&bytes).map_err(|_| INVALID)?;
        if document.format != 1 || document.schema > schema {
            return Err(UNSUPPORTED);
        }
        if document.schema == 0 {
            return Err(INVALID);
        }
        Ok(document)
    }
    pub fn write(
        &self,
        module: &str,
        schema: u32,
        revision: u64,
        value: Value,
    ) -> Result<u64, i32> {
        let previous = self.read(module, schema)?;
        if previous.revision != revision {
            return Err(STALE);
        }
        let next = Document {
            format: 1,
            schema,
            revision: revision.checked_add(1).ok_or(STALE)?,
            value,
        };
        let bytes = serde_json::to_vec(&next).map_err(|_| INVALID)?;
        if bytes.len() > 1024 * 1024 {
            return Err(INVALID);
        }
        let path = self.path(module)?;
        if path.exists() {
            atomic_save(
                &bounded_path(&self.root, &format!("{module}/last-good.json"))?,
                &fs::read(&path).map_err(|_| INTERNAL)?,
            )?;
        }
        atomic_save(&path, &bytes)?;
        Ok(next.revision)
    }
}
