use serde::{Deserialize, Serialize};
use serde_json::Value;
use sod2se_abi::{INTERNAL, INVALID, STALE};
use std::{
    collections::BTreeMap,
    fs,
    path::{Path, PathBuf},
};

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Definition {
    pub id: String,
    pub kind: String,
    pub default: Value,
    pub minimum: Option<i64>,
    pub maximum: Option<i64>,
    pub label: String,
    pub description: String,
    pub apply: String,
    pub risk: String,
}
impl Definition {
    pub fn validate(&self, value: &Value) -> Result<(), i32> {
        if !super::valid_id(&self.id)
            || self.label.is_empty()
            || self.description.is_empty()
            || !["immediate", "restart"].contains(&self.apply.as_str())
            || !["normal", "experimental", "dangerous"].contains(&self.risk.as_str())
        {
            return Err(INVALID);
        }
        match self.kind.as_str() {
            "boolean" if value.is_boolean() && self.minimum.is_none() && self.maximum.is_none() => {
                Ok(())
            }
            "integer" => {
                let n = value.as_i64().ok_or(INVALID)?;
                let (lo, hi) = (self.minimum.ok_or(INVALID)?, self.maximum.ok_or(INVALID)?);
                if lo > hi || lo < i32::MIN as i64 || hi > i32::MAX as i64 || n < lo || n > hi {
                    Err(INVALID)
                } else {
                    Ok(())
                }
            }
            _ => Err(INVALID),
        }
    }
}
#[derive(Clone, Debug, Default, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Document {
    pub schema: u32,
    pub revision: u64,
    pub values: BTreeMap<String, BTreeMap<String, Value>>,
    pub legacy_imported: bool,
    #[serde(default)]
    pub module_schemas: BTreeMap<String, u32>,
}
pub struct Registry {
    _lock: fs::File,
    path: PathBuf,
    pub document: Document,
    pub definitions: BTreeMap<String, BTreeMap<String, Definition>>,
    owners: BTreeMap<String, u64>,
    journal: Vec<(u64, String, String)>,
    declared_schemas: BTreeMap<String, u32>,
}
impl Registry {
    pub fn open(path: impl Into<PathBuf>) -> Result<Self, i32> {
        let path = path.into();
        fs::create_dir_all(path.parent().ok_or(INVALID)?).map_err(|_| INTERNAL)?;
        let mut options = fs::OpenOptions::new();
        options.read(true).write(true).create(true).truncate(false);
        #[cfg(windows)]
        {
            use std::os::windows::fs::OpenOptionsExt;
            options.share_mode(0);
        }
        let lock = options
            .open(path.with_extension("json.lock"))
            .map_err(|_| sod2se_abi::BUSY)?;
        let document = if path.exists() {
            let raw = fs::read(&path).map_err(|_| INTERNAL)?;
            let d: Document = serde_json::from_slice(&raw).map_err(|_| INVALID)?;
            if d.schema != 1 {
                return Err(STALE);
            } // Preserve unknown/corrupt input, never overwrite it.
            d
        } else {
            Document {
                schema: 1,
                ..Document::default()
            }
        };
        Ok(Self {
            _lock: lock,
            path,
            document,
            definitions: BTreeMap::new(),
            owners: BTreeMap::new(),
            journal: Vec::new(),
            declared_schemas: BTreeMap::new(),
        })
    }
    pub fn register(
        &mut self,
        owner: u64,
        module: &str,
        definitions: Vec<Definition>,
    ) -> Result<(), i32> {
        self.register_schema(owner, module, 1, definitions)
    }
    pub fn register_schema(
        &mut self,
        owner: u64,
        module: &str,
        schema: u32,
        definitions: Vec<Definition>,
    ) -> Result<(), i32> {
        if schema == 0 {
            return Err(INVALID);
        }
        let previous = self
            .document
            .module_schemas
            .get(module)
            .copied()
            .unwrap_or(1);
        if previous > schema {
            return Err(STALE);
        }
        if owner == 0
            || !super::valid_id(module)
            || self.owners.contains_key(module)
            || self.owners.len() >= crate::ui::MAX_PAGES
            || definitions.len() + self.definitions.values().map(BTreeMap::len).sum::<usize>()
                > crate::ui::MAX_OPTIONS
        {
            return Err(INVALID);
        }
        let mut map = BTreeMap::new();
        for d in definitions {
            d.validate(&d.default)?;
            if previous == schema
                && let Some(v) = self.document.values.get(module).and_then(|m| m.get(&d.id))
            {
                d.validate(v)?;
            }
            if map.insert(d.id.clone(), d).is_some() {
                return Err(INVALID);
            }
        }
        self.owners.insert(module.to_owned(), owner);
        self.definitions.insert(module.to_owned(), map);
        self.declared_schemas.insert(module.into(), schema);
        Ok(())
    }
    pub fn unregister(&mut self, owner: u64) {
        let modules: Vec<_> = self
            .owners
            .iter()
            .filter(|(_, o)| **o == owner)
            .map(|(id, _)| id.clone())
            .collect();
        for module in modules {
            self.owners.remove(&module);
            self.definitions.remove(&module);
            self.declared_schemas.remove(&module);
        }
        // Persisted values survive disabling/removing a plugin.
    }
    pub fn get(&self, module: &str, id: &str) -> Result<Value, i32> {
        self.ready_schema(module)?;
        let d = self
            .definitions
            .get(module)
            .and_then(|m| m.get(id))
            .ok_or(INVALID)?;
        Ok(self
            .document
            .values
            .get(module)
            .and_then(|m| m.get(id))
            .cloned()
            .unwrap_or_else(|| d.default.clone()))
    }
    pub fn set(
        &mut self,
        revision: u64,
        module: &str,
        id: &str,
        value: Value,
        risk_ack: bool,
    ) -> Result<u64, i32> {
        self.ready_schema(module)?;
        if revision != self.document.revision {
            return Err(STALE);
        }
        let d = self
            .definitions
            .get(module)
            .and_then(|m| m.get(id))
            .ok_or(INVALID)?;
        d.validate(&value)?;
        if d.risk == "dangerous" && value != d.default && !risk_ack {
            return Err(INVALID);
        }
        let mut next = self.document.clone();
        next.revision = next.revision.checked_add(1).ok_or(STALE)?;
        next.values
            .entry(module.into())
            .or_default()
            .insert(id.into(), value);
        next.module_schemas
            .insert(module.into(), self.declared_schemas[module]);
        self.save(&next)?;
        self.document = next;
        self.journal
            .push((self.document.revision, module.into(), id.into()));
        if self.journal.len() > 1024 {
            self.journal.remove(0);
        }
        Ok(self.document.revision)
    }
    pub fn schema(&self, module: &str) -> u32 {
        self.document
            .module_schemas
            .get(module)
            .copied()
            .unwrap_or_else(|| {
                if self.document.values.contains_key(module) {
                    1
                } else {
                    self.declared_schemas.get(module).copied().unwrap_or(1)
                }
            })
    }
    fn ready_schema(&self, module: &str) -> Result<(), i32> {
        if self.declared_schemas.get(module).copied().ok_or(INVALID)? != self.schema(module) {
            Err(STALE)
        } else {
            Ok(())
        }
    }
    pub fn migrate(
        &mut self,
        owner: u64,
        module: &str,
        revision: u64,
        from: u32,
        to: u32,
        values: BTreeMap<String, Value>,
    ) -> Result<u64, i32> {
        if self.owners.get(module) != Some(&owner) {
            return Err(INVALID);
        }
        if revision != self.document.revision
            || from != self.schema(module)
            || to <= from
            || self.declared_schemas.get(module) != Some(&to)
        {
            return Err(STALE);
        }
        let definitions = self.definitions.get(module).ok_or(INVALID)?;
        for (id, value) in &values {
            let definition = definitions.get(id).ok_or(INVALID)?;
            definition.validate(value)?;
            // A schema migration must not silently introduce a dangerous nondefault.
            // Already stored values may carry forward unchanged; new values require
            // an explicit, acknowledged settings.set after migration.
            if definition.risk == "dangerous"
                && value != &definition.default
                && self.document.values.get(module).and_then(|v| v.get(id)) != Some(value)
            {
                return Err(INVALID);
            }
        }
        let mut next = self.document.clone();
        next.revision = next.revision.checked_add(1).ok_or(STALE)?;
        next.values.insert(module.into(), values);
        next.module_schemas.insert(module.into(), to);
        self.save(&next)?;
        self.document = next;
        self.journal
            .push((self.document.revision, module.into(), "*".into()));
        if self.journal.len() > 1024 {
            self.journal.remove(0);
        }
        Ok(self.document.revision)
    }
    pub fn changes(&self, since: u64) -> Result<Vec<(u64, String, String)>, i32> {
        if since > self.document.revision
            || (self.journal.is_empty() && since != self.document.revision)
            || self
                .journal
                .first()
                .is_some_and(|v| since < v.0.saturating_sub(1))
        {
            return Err(STALE);
        }
        Ok(self
            .journal
            .iter()
            .filter(|v| v.0 > since)
            .cloned()
            .collect())
    }
    pub fn import_legacy(&mut self, source: &Path) -> Result<bool, i32> {
        if self.document.legacy_imported {
            return Ok(false);
        }
        let raw = fs::read(source).map_err(|_| INTERNAL)?;
        let text = std::str::from_utf8(&raw)
            .map_err(|_| INVALID)?
            .trim_start_matches('\u{feff}');
        let mut section = String::new();
        let mut values = BTreeMap::<String, BTreeMap<String, Value>>::new();
        for line in text
            .lines()
            .map(str::trim)
            .filter(|s| !s.is_empty() && !s.starts_with([';', '#']))
        {
            if line.starts_with('[') && line.ends_with(']') {
                section = line[1..line.len() - 1].into();
                if !super::valid_id(&section) {
                    return Err(INVALID);
                }
            } else {
                let (key, value) = line.split_once('=').ok_or(INVALID)?;
                let (module, key) = if section.is_empty() {
                    key.trim().split_once('.').ok_or(INVALID)?
                } else {
                    (section.as_str(), key.trim())
                };
                if !super::valid_id(module) || !super::valid_id(key) {
                    return Err(INVALID);
                }
                let v = match value.trim().to_ascii_lowercase().as_str() {
                    "true" => Value::Bool(true),
                    "false" => Value::Bool(false),
                    _ => value
                        .trim()
                        .parse::<i64>()
                        .map(Value::from)
                        .unwrap_or_else(|_| Value::String(value.trim().into())),
                };
                if values
                    .entry(module.into())
                    .or_default()
                    .insert(key.into(), v)
                    .is_some()
                {
                    return Err(INVALID);
                }
            }
        }
        let mut next = self.document.clone();
        for (module, items) in values {
            for (id, v) in items {
                if let Some(d) = self.definitions.get(&module).and_then(|m| m.get(&id)) {
                    d.validate(&v)?;
                }
                next.values
                    .entry(module.clone())
                    .or_default()
                    .entry(id)
                    .or_insert(v);
            }
        }
        next.legacy_imported = true;
        next.revision = next.revision.checked_add(1).ok_or(STALE)?;
        let backup = source.with_extension("ini.pre-rust-backup");
        if backup.exists() {
            if fs::read(&backup).map_err(|_| INTERNAL)? != raw {
                return Err(INVALID);
            }
        } else {
            let mut f = fs::OpenOptions::new()
                .write(true)
                .create_new(true)
                .open(&backup)
                .map_err(|_| INTERNAL)?;
            use std::io::Write;
            f.write_all(&raw)
                .and_then(|_| f.sync_all())
                .map_err(|_| INTERNAL)?;
        }
        self.save(&next)?;
        self.document = next;
        Ok(true)
    }
    fn save(&self, next: &Document) -> Result<(), i32> {
        atomic_save(
            &self.path.with_extension("json.last-good"),
            &serde_json::to_vec_pretty(&self.document).map_err(|_| INTERNAL)?,
        )?;
        atomic_save(
            &self.path,
            &serde_json::to_vec_pretty(next).map_err(|_| INTERNAL)?,
        )
    }
    pub fn recover(path: &Path) -> Result<(), i32> {
        // Obtain exclusivity before reading or preserving any recovery input.
        let mut lock_options = fs::OpenOptions::new();
        lock_options
            .read(true)
            .write(true)
            .create(true)
            .truncate(false);
        #[cfg(windows)]
        {
            use std::os::windows::fs::OpenOptionsExt;
            lock_options.share_mode(0);
        }
        let _guard = lock_options
            .open(path.with_extension("json.lock"))
            .map_err(|_| sod2se_abi::BUSY)?;
        let backup = fs::read(path.with_extension("json.last-good")).map_err(|_| INTERNAL)?;
        let document: Document = serde_json::from_slice(&backup).map_err(|_| INVALID)?;
        if document.schema != 1 {
            return Err(STALE);
        }
        if path.exists() {
            let raw = fs::read(path).map_err(|_| INTERNAL)?;
            if let Ok(current) = serde_json::from_slice::<Document>(&raw) {
                if current.schema != 1 {
                    return Err(STALE);
                }
                return Err(INVALID);
            }
            let preserved = path.with_extension(format!(
                "json.corrupt-{}",
                std::time::SystemTime::now()
                    .duration_since(std::time::UNIX_EPOCH)
                    .map_err(|_| INTERNAL)?
                    .as_nanos()
            ));
            let mut f = fs::OpenOptions::new()
                .create_new(true)
                .write(true)
                .open(preserved)
                .map_err(|_| INTERNAL)?;
            use std::io::Write;
            f.write_all(&raw)
                .and_then(|_| f.sync_all())
                .map_err(|_| INTERNAL)?;
        }
        atomic_save(path, &backup)
    }
}

/// Create a unique sibling, flush it, and atomically replace the destination.
pub fn atomic_save(path: &Path, bytes: &[u8]) -> Result<(), i32> {
    use std::io::Write;
    let parent = path.parent().ok_or(INVALID)?;
    fs::create_dir_all(parent).map_err(|_| INTERNAL)?;
    let temporary = parent.join(format!(
        ".sod2se-{}-{}.tmp",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map_err(|_| INTERNAL)?
            .as_nanos()
    ));
    let mut file = fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&temporary)
        .map_err(|_| INTERNAL)?;
    if file.write_all(bytes).and_then(|_| file.sync_all()).is_err() {
        drop(file);
        let _ = fs::remove_file(&temporary);
        return Err(INTERNAL);
    }
    drop(file);
    #[cfg(windows)]
    let result = {
        use std::os::windows::ffi::OsStrExt;
        let from: Vec<u16> = temporary.as_os_str().encode_wide().chain(Some(0)).collect();
        let to: Vec<u16> = path.as_os_str().encode_wide().chain(Some(0)).collect();
        unsafe {
            windows_sys::Win32::Storage::FileSystem::MoveFileExW(
                from.as_ptr(),
                to.as_ptr(),
                windows_sys::Win32::Storage::FileSystem::MOVEFILE_REPLACE_EXISTING
                    | windows_sys::Win32::Storage::FileSystem::MOVEFILE_WRITE_THROUGH,
            ) != 0
        }
    };
    #[cfg(not(windows))]
    let result = fs::rename(&temporary, path).is_ok();
    if !result {
        let _ = fs::remove_file(&temporary);
        return Err(INTERNAL);
    }
    Ok(())
}
