use serde::Serialize;
use sod2se_abi::{INTERNAL, INVALID};
use std::{
    fs::{self, OpenOptions},
    io::Write,
    path::{Path, PathBuf},
};
#[derive(Serialize)]
pub struct Record<'a> {
    pub timestamp_ms: u128,
    pub pid: u32,
    pub level: u32,
    pub owner: &'a str,
    pub code: &'a str,
    pub message: &'a str,
    pub version: &'a str,
}
pub struct Logger {
    path: PathBuf,
    writer: std::sync::Mutex<()>,
}
impl Logger {
    pub fn new(path: impl Into<PathBuf>) -> Self {
        Self { path: path.into(), writer: std::sync::Mutex::new(()) }
    }
    pub fn write(&self, level: u32, owner: &str, code: &str, message: &str) -> Result<(), i32> {
        let _writer = self.writer.lock().map_err(|_| INTERNAL)?;
        if !super::valid_id(code) || message.len() > 8192 {
            return Err(INVALID);
        }
        let parent = self.path.parent().ok_or(INVALID)?;
        fs::create_dir_all(parent).map_err(|_| INTERNAL)?;
        if fs::metadata(&self.path).is_ok_and(|m| m.len() > 2 * 1024 * 1024) {
            let previous = self.path.with_extension("previous.jsonl");
            if previous.exists() {
                fs::remove_file(&previous).map_err(|_| INTERNAL)?;
            }
            fs::rename(&self.path, previous).map_err(|_| INTERNAL)?;
        }
        let record = Record {
            timestamp_ms: std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map_err(|_| INTERNAL)?
                .as_millis(),
            pid: std::process::id(),
            level,
            owner,
            code,
            message,
            version: env!("CARGO_PKG_VERSION"),
        };
        let mut bytes = serde_json::to_vec(&record).map_err(|_| INTERNAL)?;
        bytes.push(b'\n');
        OpenOptions::new()
            .append(true)
            .create(true)
            .open(&self.path)
            .and_then(|mut f| f.write_all(&bytes))
            .map_err(|_| INTERNAL)
    }
}
pub fn digest(path: &Path) -> Result<String, i32> {
    use sha2::{Digest, Sha256};
    use std::io::Read;
    let mut file = fs::File::open(path).map_err(|_| INTERNAL)?;
    let mut hash = Sha256::new();
    let mut buffer = [0; 65536];
    loop {
        let n = file.read(&mut buffer).map_err(|_| INTERNAL)?;
        if n == 0 {
            break;
        }
        hash.update(&buffer[..n]);
    }
    Ok(format!("{:x}", hash.finalize()))
}
