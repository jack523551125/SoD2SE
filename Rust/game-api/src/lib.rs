//! Canonical Rust fixed-build adapter. Descriptors come from the existing reviewed manifest.
use serde::Deserialize;
use sod2se_abi::{INVALID, UNSUPPORTED};
use std::path::Path;
pub const FOLLOWERS: &str = "sod2.followers.quantity";
pub const SETTINGS: &str = "sod2.ui.native-settings";
pub const GAME_BUILD: &str = "16535856";
pub const SHIPPING: &str = "StateOfDecay2-Win64-Shipping.exe";
#[derive(Clone, Deserialize)]
pub struct Patch {
    pub name: String,
    pub rva: usize,
    pub original: String,
    pub replacement: String,
    pub guard_rva: usize,
    pub guard_original: String,
}
#[derive(Deserialize)]
pub struct Target {
    pub sha256: String,
    pub steam_build_id: String,
    pub patches: Vec<Patch>,
}
pub fn target() -> Target {
    serde_json::from_str(include_str!("../../../patch-manifest.json"))
        .expect("reviewed target manifest must be valid")
}
pub fn verify_image(path: &Path) -> Result<(), i32> {
    if !path
        .file_name()
        .is_some_and(|n| n.to_string_lossy().eq_ignore_ascii_case(SHIPPING))
    {
        return Err(UNSUPPORTED);
    }
    if sod2se_services::diagnostics::digest(path)? != target().sha256.to_ascii_lowercase() {
        return Err(UNSUPPORTED);
    }
    Ok(())
}
pub fn game_root(image: &Path) -> Result<&Path, i32> {
    let win64 = image.parent().ok_or(INVALID)?;
    let binaries = win64.parent().ok_or(INVALID)?;
    let content = binaries.parent().ok_or(INVALID)?;
    if !win64
        .file_name()
        .is_some_and(|n| n.to_string_lossy().eq_ignore_ascii_case("Win64"))
        || !binaries
            .file_name()
            .is_some_and(|n| n.to_string_lossy().eq_ignore_ascii_case("Binaries"))
        || !content
            .file_name()
            .is_some_and(|n| n.to_string_lossy().eq_ignore_ascii_case("StateOfDecay2"))
    {
        return Err(INVALID);
    }
    content.parent().ok_or(INVALID)
}
pub fn decode(hex: &str) -> Result<Vec<u8>, i32> {
    if !hex.len().is_multiple_of(2) || !hex.is_ascii() {
        return Err(INVALID);
    }
    (0..hex.len())
        .step_by(2)
        .map(|i| u8::from_str_radix(&hex[i..i + 2], 16).map_err(|_| INVALID))
        .collect()
}
pub mod language;
#[cfg(windows)]
pub mod native_ui;
#[cfg(windows)]
pub mod process;

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn target_parity() {
        let t = target();
        assert_eq!(t.steam_build_id, GAME_BUILD);
        assert_eq!(t.patches.len(), 2);
        for p in t.patches {
            let a = decode(&p.original).unwrap();
            let b = decode(&p.replacement).unwrap();
            let g = decode(&p.guard_original).unwrap();
            assert_eq!(a.len(), b.len());
            assert!(p.guard_rva <= p.rva && p.rva + a.len() <= p.guard_rva + g.len());
        }
    }
    #[test]
    fn strict_hex() {
        assert!(decode("0").is_err());
        assert!(decode("é").is_err());
    }
    #[test]
    fn foreign_image_refused() {
        assert_eq!(
            verify_image(&std::env::current_exe().unwrap()),
            Err(UNSUPPORTED)
        );
    }
}
