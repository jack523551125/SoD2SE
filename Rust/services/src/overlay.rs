//! New resource overlays use flushed temporary files and file-identity ownership receipts.
use serde::{Deserialize, Serialize};
use sod2se_abi::{INTERNAL, INVALID};
use std::{fs, io::Write, path::Path};
#[derive(Serialize, Deserialize)]
struct Receipt {
    schema: u32,
    sha256: String,
    file_id: [u64; 2],
}
pub(crate) fn no_links(path: &Path) -> Result<(), i32> {
    if !path.is_absolute() {
        return Err(INVALID);
    }
    for parent in path.ancestors() {
        if let Ok(meta) = fs::symlink_metadata(parent) {
            if meta.file_type().is_symlink() {
                return Err(INVALID);
            }
            #[cfg(windows)]
            {
                use std::os::windows::fs::MetadataExt;
                if meta.file_attributes() & 0x400 != 0 {
                    return Err(INVALID);
                }
            }
        }
    }
    Ok(())
}
pub(crate) fn identity(file: &fs::File) -> Result<[u64; 2], i32> {
    #[cfg(windows)]
    {
        use std::os::windows::io::AsRawHandle;
        use windows_sys::Win32::Storage::FileSystem::*;
        let mut info: BY_HANDLE_FILE_INFORMATION = unsafe { std::mem::zeroed() };
        if unsafe { GetFileInformationByHandle(file.as_raw_handle().cast(), &mut info) } == 0 {
            return Err(INTERNAL);
        }
        Ok([
            info.dwVolumeSerialNumber as u64,
            ((info.nFileIndexHigh as u64) << 32) | info.nFileIndexLow as u64,
        ])
    }
    #[cfg(not(windows))]
    {
        use std::os::unix::fs::MetadataExt;
        let meta = file.metadata().map_err(|_| INTERNAL)?;
        Ok([meta.dev(), meta.ino()])
    }
}
pub fn recover(target: &Path, receipt: &Path) -> Result<(), i32> {
    no_links(target)?;
    no_links(receipt)?;
    if !receipt.exists() {
        return Ok(());
    }
    let owned: Receipt =
        serde_json::from_slice(&fs::read(receipt).map_err(|_| INTERNAL)?).map_err(|_| INVALID)?;
    if owned.schema != 1 {
        return Err(INVALID);
    }
    if target.exists() {
        let file = fs::File::open(target).map_err(|_| INTERNAL)?;
        if identity(&file)? != owned.file_id || super::diagnostics::digest(target)? != owned.sha256
        {
            return Err(INVALID);
        }
        drop(file);
        fs::remove_file(target).map_err(|_| INTERNAL)?;
    }
    fs::remove_file(receipt).map_err(|_| INTERNAL)?;
    Ok(())
}
pub fn prepare(source: &Path, expected: &str, target: &Path, receipt: &Path) -> Result<(), i32> {
    no_links(target)?;
    no_links(receipt)?;
    if super::diagnostics::digest(source)? != expected {
        return Err(INVALID);
    }
    recover(target, receipt)?;
    if target.exists() {
        return Err(INVALID);
    }
    let parent = target.parent().ok_or(INVALID)?;
    fs::create_dir_all(parent).map_err(|_| INTERNAL)?;
    let bytes = fs::read(source).map_err(|_| INTERNAL)?;
    use sha2::{Digest, Sha256};
    if format!("{:x}", Sha256::digest(&bytes)) != expected {
        return Err(INVALID);
    }
    let temporary = parent.join(format!(
        ".sod2se-ui-{}-{}.tmp",
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
    let result = (|| -> Result<(), i32> {
        file.write_all(&bytes)
            .and_then(|_| file.sync_all())
            .map_err(|_| INTERNAL)?;
        let owned = Receipt {
            schema: 1,
            sha256: expected.into(),
            file_id: identity(&file)?,
        };
        super::settings::atomic_save(receipt, &serde_json::to_vec(&owned).map_err(|_| INTERNAL)?)?;
        // hard_link publishes the complete file atomically and refuses an existing destination.
        // Its identity is already recorded, so identical foreign content is not mistaken for ours.
        fs::hard_link(&temporary, target).map_err(|_| INTERNAL)?;
        Ok(())
    })();
    drop(file);
    let _ = fs::remove_file(&temporary);
    result
}
